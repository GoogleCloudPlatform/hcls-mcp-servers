# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Shared async HTTP client for MedlinePlus APIs.

Wraps two separate NLM services:
  1. MedlinePlus Connect — code-based health info lookup (ICD-10, RxCUI, LOINC, CPT)
  2. MedlinePlus Web Service — keyword health topic search (returns XML)

Provides rate-limiting (separate token buckets per API), TTL caching,
and XML parsing for the Web Service.
"""

import asyncio
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import httpx
from cachetools import TTLCache


# Base URLs

CONNECT_BASE = "https://connect.medlineplus.gov/service"
WEB_SERVICE_BASE = "https://wsearch.nlm.nih.gov/ws/query"


# Code system OIDs for MedlinePlus Connect

CODE_SYSTEMS = {
    "icd10": "2.16.840.1.113883.6.90",
    "icd10cm": "2.16.840.1.113883.6.90",
    "icd9": "2.16.840.1.113883.6.103",
    "icd9cm": "2.16.840.1.113883.6.103",
    "snomed": "2.16.840.1.113883.6.96",
    "snomedct": "2.16.840.1.113883.6.96",
    "rxnorm": "2.16.840.1.113883.6.88",
    "rxcui": "2.16.840.1.113883.6.88",
    "ndc": "2.16.840.1.113883.6.69",
    "loinc": "2.16.840.1.113883.6.1",
    "cpt": "2.16.840.1.113883.6.12",
}

# Human-readable names for code systems
CODE_SYSTEM_NAMES = {
    "2.16.840.1.113883.6.90": "ICD-10-CM",
    "2.16.840.1.113883.6.103": "ICD-9-CM",
    "2.16.840.1.113883.6.96": "SNOMED CT",
    "2.16.840.1.113883.6.88": "RxNorm",
    "2.16.840.1.113883.6.69": "NDC",
    "2.16.840.1.113883.6.1": "LOINC",
    "2.16.840.1.113883.6.12": "CPT",
}


# Rate limiters — separate buckets per API

class TokenBucket:
    """Simple async-safe token-bucket rate limiter."""

    def __init__(self, rate: float = 1.5, capacity: float = 5.0):
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0

# Connect: 100 req/min = ~1.67/s, use 1.5/s with burst of 5
_connect_limiter = TokenBucket(rate=1.5, capacity=5.0)
# Web Service: 85 req/min = ~1.42/s, use 1.4/s with burst of 5
_web_limiter = TokenBucket(rate=1.4, capacity=5.0)

# TTL cache — content updates daily (Tue-Sat)
_cache_24h: TTLCache = TTLCache(maxsize=2048, ttl=86_400)


# Cache key helper

def _cache_key(url: str, params: Optional[Dict[str, Any]]) -> str:
    raw = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# Core HTTP function

async def _http_get(
    url: str,
    params: Optional[Dict[str, Any]],
    limiter: TokenBucket,
    parse_json: bool = True,
) -> Any:
    """GET with rate-limiting, caching, and retry."""
    key = _cache_key(url, params)
    if key in _cache_24h:
        return _cache_24h[key]

    last_exc: Optional[Exception] = None
    for attempt in range(3):
        await limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                if parse_json:
                    data = resp.json()
                else:
                    data = resp.text
                _cache_24h[key] = data
                return data
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code in (429, 503) and attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
        except httpx.TimeoutException as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            raise

    raise last_exc  # type: ignore[misc]


# MedlinePlus Connect

async def connect_get(
    code: str,
    code_system: str,
    display_name: Optional[str] = None,
    language: str = "en",
) -> Dict[str, Any]:
    """
    Look up health information by medical code via MedlinePlus Connect.

    Args:
        code: The medical code value (e.g., "E11.65", "161354").
        code_system: Code system OID or shorthand (e.g., "icd10", "rxnorm", "loinc").
        display_name: Optional display name for the code.
        language: Language code ("en" or "es").

    Returns:
        Parsed JSON response with health information entries.
    """
    # Resolve shorthand to OID
    cs_oid = CODE_SYSTEMS.get(code_system.lower(), code_system)

    params: Dict[str, str] = {
        "mainSearchCriteria.v.cs": cs_oid,
        "mainSearchCriteria.v.c": code,
        "informationRecipient.languageCode.c": language,
        "knowledgeResponseType": "application/json",
    }
    if display_name:
        params["mainSearchCriteria.v.dn"] = display_name

    return await _http_get(CONNECT_BASE, params, _connect_limiter, parse_json=True)


# MedlinePlus Web Service (returns XML)

def _parse_web_service_xml(xml_text: str) -> Dict[str, Any]:
    """Parse the Atom-format XML from the MedlinePlus Web Service."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {"total": 0, "results": []}

    # Namespace handling — the feed uses a default namespace
    ns = {"atom": "http://www.w3.org/2005/Atom", "nlm": "http://nlm.nih.gov"}

    # Try to get count from <count> element
    count_el = root.find(".//count")
    total = int(count_el.text) if count_el is not None and count_el.text else 0

    results: List[Dict[str, Any]] = []
    for doc in root.findall(".//document"):
        entry: Dict[str, Any] = {
            "rank": doc.get("rank", ""),
            "url": doc.get("url", ""),
        }

        for content in doc.findall("content"):
            name = content.get("name", "")
            text = content.text or ""
            # Strip HTML tags from text fields
            if name in ("title", "snippet", "FullSummary", "altTitle"):
                text = _strip_html(text)
            if name in ("title", "organizationName", "snippet", "FullSummary",
                        "groupName", "altTitle"):
                entry[name] = text

        if entry.get("title") or entry.get("url"):
            results.append(entry)

    return {"total": total, "results": results}


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


async def web_search(
    term: str,
    max_results: int = 10,
    language: str = "en",
) -> Dict[str, Any]:
    """
    Search MedlinePlus health topics by keyword.

    Args:
        term: Search query (e.g., "diabetes", "high blood pressure").
        max_results: Maximum results to return (default 10).
        language: "en" for English, "es" for Spanish.

    Returns:
        Dict with 'total' count and 'results' list of health topics.
    """
    db = "healthTopicsSpanish" if language == "es" else "healthTopics"
    params: Dict[str, Any] = {
        "db": db,
        "term": term,
        "retmax": max_results,
        "rettype": "all",
    }

    xml_text = await _http_get(WEB_SERVICE_BASE, params, _web_limiter, parse_json=False)
    return _parse_web_service_xml(xml_text)


# Connect response parsing helpers

def parse_connect_entries(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract health info entries from a MedlinePlus Connect response."""
    entries: List[Dict[str, Any]] = []

    feed = data.get("feed", {})
    entry_list = feed.get("entry", [])
    if isinstance(entry_list, dict):
        entry_list = [entry_list]

    for entry in entry_list:
        parsed: Dict[str, Any] = {}
        title = entry.get("title", {})
        if isinstance(title, dict):
            parsed["title"] = title.get("_value", "")
        else:
            parsed["title"] = str(title)

        # Link
        links = entry.get("link", [])
        if isinstance(links, dict):
            links = [links]
        for link in links:
            href = link.get("href", "")
            if href:
                parsed["url"] = href
                break

        # Summary
        summary = entry.get("summary", {})
        if isinstance(summary, dict):
            parsed["summary"] = _strip_html(summary.get("_value", ""))
        else:
            parsed["summary"] = _strip_html(str(summary))

        if parsed.get("title"):
            entries.append(parsed)

    return entries


# Error formatting

def format_api_error(exc: Exception) -> str:
    """Return a user-friendly, actionable error string."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return "Error: Resource not found. Verify the code or search term is correct."
        if code == 429:
            return "Error: Rate limit exceeded. MedlinePlus allows ~100 requests per minute. Try again shortly."
        if code == 503:
            return "Error: MedlinePlus API temporarily unavailable. Try again shortly."
        return f"Error: API returned status {code}."
    if isinstance(exc, httpx.TimeoutException):
        return "Error: Request timed out after 30 seconds. Try again later."
    return f"Error: {type(exc).__name__} — {exc}"
