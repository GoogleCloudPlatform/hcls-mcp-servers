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
Shared async HTTP client for CMS drug data APIs.

Wraps the new DKAN API (Data.Medicaid.gov) and CMS Data API (data.cms.gov).
Provides dkan_query() and cms_query() with rate-limiting and caching.
"""

import asyncio
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from cachetools import TTLCache

# ---------------------------------------------------------------------------
# Host URLs and dataset IDs
# ---------------------------------------------------------------------------
MEDICAID_HOST = "https://data.medicaid.gov"
CMS_HOST = "https://data.cms.gov"

# NADAC — National Average Drug Acquisition Cost (weekly updates)
NADAC_2026 = "fbb83258-11c7-47f5-8b18-5f8e79f7e704"
NADAC_2025 = "f38d0706-1239-442c-a3cc-40ef1b686ac0"
NADAC_2024 = "99315a95-37ac-4eee-946a-3c523b4c481e"

# State Drug Utilization Data
SDUD_2025 = "158a1baa-5506-400a-8ec3-97756f0b0536"
SDUD_2024 = "61729e5a-7aa8-448c-8903-ba3e0cd0ea3c"
SDUD_2023 = "d890d3a9-6b00-43fd-8b31-fcba4c8e2909"
SDUD_2022 = "200c2cba-e58d-4a95-aa60-14b99736808d"

# Medicaid Drug Rebate Program — Drug Products
DRUG_REBATE = "0ad65fe5-3ad3-5d79-a3f9-7893ded7963a"

# Default datasets
NADAC_DEFAULT = NADAC_2026

# CMS Medicare Part D
PART_D_SPENDING_ID = "7e0b4365-fd63-4a29-8f5e-e0ac9f66a81b"
PART_D_PRESCRIBER_ID = "9552739e-3d05-4c1b-8eff-ecabf391e2e5"


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
class TokenBucket:
    """Simple async-safe token-bucket rate limiter."""

    def __init__(self, rate: float = 5.0, capacity: float = 5.0):
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


_limiter = TokenBucket(rate=5.0, capacity=5.0)

# TTL caches — NADAC updates weekly, spending data quarterly
_cache_1h: TTLCache = TTLCache(maxsize=2048, ttl=3_600)
_cache_24h: TTLCache = TTLCache(maxsize=1024, ttl=86_400)
_cache_7d: TTLCache = TTLCache(maxsize=512, ttl=604_800)

# ---------------------------------------------------------------------------
# Cache key helper
# ---------------------------------------------------------------------------
def _cache_key(url: str, params: Optional[Dict[str, Any]]) -> str:
    raw = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# DKAN Query (Medicaid)
# ---------------------------------------------------------------------------
async def dkan_query(
    dataset_id: str,
    params: Optional[Dict[str, Any]] = None,
    cache_ttl: str = "24h",
) -> List[Dict[str, Any]]:
    """
    Query a DKAN Datastore dataset on Data.Medicaid.gov.
    """
    url = f"{MEDICAID_HOST}/api/1/datastore/query/{dataset_id}/0"
    
    # Restructure our custom params to DKAN datastore query params
    query_params: Dict[str, str] = {}
    if params:
        if "limit" in params:
            query_params["limit"] = str(params["limit"])
        if "offset" in params:
            query_params["offset"] = str(params["offset"])
        
        # conditions list: [{"property": p, "value": v, "operator": o}]
        for i, cond in enumerate(params.get("conditions", [])):
            query_params[f"conditions[{i}][property]"] = cond["property"]
            query_params[f"conditions[{i}][value]"] = cond["value"]
            if "operator" in cond:
                query_params[f"conditions[{i}][operator]"] = cond["operator"]
        
        # sorts list: [{"property": p, "order": o}]
        for i, sort in enumerate(params.get("sorts", [])):
            query_params[f"sorts[{i}][property]"] = sort["property"]
            query_params[f"sorts[{i}][order]"] = sort["order"]

    return await _execute_request(url, query_params, cache_ttl, is_dkan=True)


# ---------------------------------------------------------------------------
# CMS API Query
# ---------------------------------------------------------------------------
async def cms_query(
    dataset_id: str,
    params: Optional[Dict[str, Any]] = None,
    cache_ttl: str = "24h",
) -> List[Dict[str, Any]]:
    """
    Query the CMS Data API on data.cms.gov.
    """
    url = f"{CMS_HOST}/data-api/v1/dataset/{dataset_id}/data"
    
    query_params: Dict[str, str] = {}
    if params:
        if "size" in params:
            query_params["size"] = str(params["size"])
        if "offset" in params:
            query_params["offset"] = str(params["offset"])
        if "keyword" in params:
            query_params["keyword"] = str(params["keyword"])
            
        for k, v in params.get("filter", {}).items():
            if isinstance(v, dict) and "like" in v:
                query_params[f"filter[{k}][$like]"] = v["like"]
            else:
                query_params[f"filter[{k}]"] = str(v)
        
        for k, v in params.get("sort", {}).items():
            query_params[f"sort[{k}]"] = v

    return await _execute_request(url, query_params, cache_ttl, is_dkan=False)


# ---------------------------------------------------------------------------
# Internal executor
# ---------------------------------------------------------------------------
async def _execute_request(
    url: str,
    params: Dict[str, str],
    cache_ttl: str,
    is_dkan: bool,
) -> List[Dict[str, Any]]:
    key = _cache_key(url, params)
    
    cache_map = {"1h": _cache_1h, "24h": _cache_24h, "7d": _cache_7d}
    cache = cache_map.get(cache_ttl, _cache_24h)
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
                
                # DKAN wraps in {"results": [...]}, CMS API returns list directly
                results = data.get("results", []) if is_dkan and isinstance(data, dict) else data
                
                cache[key] = results
                return results
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


# ---------------------------------------------------------------------------
# Convenience wrappers for each dataset
# ---------------------------------------------------------------------------
async def nadac_query(
    params: Dict[str, Any],
    dataset_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query NADAC data — cached 24 hours (updates weekly)."""
    return await dkan_query(dataset_id or NADAC_DEFAULT, params, cache_ttl="24h")


async def sdud_query(
    params: Dict[str, Any],
    dataset_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query State Drug Utilization Data — cached 7 days (updates quarterly)."""
    return await dkan_query(dataset_id or SDUD_2025, params, cache_ttl="7d")


async def rebate_query(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Query Medicaid Drug Rebate Program — cached 7 days (updates quarterly)."""
    return await dkan_query(DRUG_REBATE, params, cache_ttl="7d")


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------
def format_api_error(exc: Exception) -> str:
    """Return a user-friendly, actionable error string."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 400:
            return "Error: Invalid query. Check field names and query syntax."
        if code == 403:
            return "Error: Access denied. The dataset may require authentication."
        if code == 404:
            return "Error: Dataset not found. The dataset ID may have changed."
        if code == 429:
            return "Error: Rate limit exceeded. Try again in a moment."
        if code == 503:
            return "Error: CMS data service temporarily unavailable. Try again shortly."
        return f"Error: API returned status {code}."
    if isinstance(exc, httpx.TimeoutException):
        return "Error: Request timed out after 30 seconds. Try narrowing your query."
    return f"Error: {type(exc).__name__} — {exc}"
