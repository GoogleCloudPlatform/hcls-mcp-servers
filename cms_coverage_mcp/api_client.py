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
Shared async HTTP client for the CMS Coverage Database API.

Provides rate-limiting (token bucket), TTL caching, and client-side
keyword filtering for coverage determination searches.

The CMS Coverage API report endpoints return all documents without
server-side filtering. This client caches the full document lists
and performs keyword matching locally.
"""

import asyncio
import hashlib
import json
import re
import time
from typing import Any, Dict, List, Optional

import httpx
from cachetools import TTLCache


# Base URL

CMS_BASE = "https://api.coverage.cms.gov/v1"


# Rate limiter — 20 req/s (conservative; API allows 10k/s)

class TokenBucket:
    """Simple async-safe token-bucket rate limiter."""

    def __init__(self, rate: float = 20.0, capacity: float = 20.0):
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

_limiter = TokenBucket(rate=20.0, capacity=20.0)

# TTL caches
_cache_24h: TTLCache = TTLCache(maxsize=512, ttl=86_400)   # document lists, NCD details
_cache_1h: TTLCache = TTLCache(maxsize=1024, ttl=3_600)    # search results


# Cache key helper

def _cache_key(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    raw = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# Core request function

async def api_get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    cache_ttl: str = "24h",
) -> Dict[str, Any]:
    """
    GET JSON from the CMS Coverage API with rate-limiting and caching.

    Args:
        path: Endpoint path (e.g., "/reports/national-coverage-ncd/").
        params: Query parameters.
        cache_ttl: "24h" or "1h".

    Returns:
        Parsed JSON dict.
    """
    url = f"{CMS_BASE}{path}"
    key = _cache_key(url, params)

    cache = _cache_1h if cache_ttl == "1h" else _cache_24h
    if key in cache:
        return cache[key]

    last_exc: Optional[Exception] = None
    for attempt in range(3):
        await _limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                cache[key] = data
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


# Fetch all documents from a report endpoint (paginated)

async def fetch_all_documents(endpoint: str, max_pages: int = 20) -> List[Dict[str, Any]]:
    """
    Fetch all documents from a CMS report endpoint, handling pagination.

    The report endpoints don't support server-side filtering, so we fetch
    all documents and cache them for client-side filtering.

    Args:
        endpoint: Report endpoint path (e.g., "/reports/national-coverage-ncd/").
        max_pages: Maximum pages to fetch (safety limit).

    Returns:
        List of all document dicts.
    """
    cache_key_str = f"all_docs:{endpoint}"
    if cache_key_str in _cache_24h:
        return _cache_24h[cache_key_str]

    all_docs: List[Dict[str, Any]] = []
    page = 1
    page_size = 200

    while page <= max_pages:
        data = await api_get(endpoint, params={"page": page, "pageSize": page_size})
        docs = data.get("data", [])
        if not docs:
            break
        all_docs.extend(docs)
        # If we got fewer than page_size, we're done
        if len(docs) < page_size:
            break
        page += 1

    _cache_24h[cache_key_str] = all_docs
    return all_docs


# Client-side keyword filtering

def filter_documents(
    docs: List[Dict[str, Any]],
    keyword: Optional[str] = None,
    state: Optional[str] = None,
    contractor: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Filter documents by keyword, state, or contractor (case-insensitive).

    Args:
        docs: List of document dicts.
        keyword: Search term to match in title or description fields.
        state: Two-letter state abbreviation (for LCDs/Articles with contractor info).
        contractor: Contractor name substring (for LCDs/Articles).

    Returns:
        Filtered list of documents.
    """
    results = docs

    if keyword:
        kw = keyword.lower()
        results = [
            d for d in results
            if kw in d.get("title", "").lower()
            or kw in d.get("note", "").lower()
            or kw in d.get("document_display_id", "").lower()
        ]

    if state:
        st = state.upper()
        results = [
            d for d in results
            if st in d.get("contractor_name_type", "").upper()
            or st in d.get("state", "").upper()
        ]

    if contractor:
        ct = contractor.lower()
        results = [
            d for d in results
            if ct in d.get("contractor_name_type", "").lower()
        ]

    return results


# HTML entity/tag stripping for NCD detail content

def strip_html(text: str) -> str:
    """Strip HTML tags and decode common HTML entities."""
    if not text:
        return ""
    # Decode HTML entities
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"')
    text = text.replace("&#39;", "'").replace("&sol;", "/")
    text = text.replace("&apos;", "'")
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Clean up whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Error formatting

def format_api_error(exc: Exception) -> str:
    """Return a user-friendly, actionable error string."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return "Error: Resource not found. Verify the document ID is correct."
        if code == 429:
            return "Error: Rate limit exceeded. Try again in a moment."
        if code == 503:
            return "Error: CMS Coverage API temporarily unavailable. Try again shortly."
        return f"Error: API returned status {code}."
    if isinstance(exc, httpx.TimeoutException):
        return "Error: Request timed out after 30 seconds. Try again later."
    return f"Error: {type(exc).__name__} — {exc}"
