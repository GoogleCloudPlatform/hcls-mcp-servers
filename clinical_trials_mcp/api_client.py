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
Shared async HTTP client for the ClinicalTrials.gov v2 API.

Provides rate-limiting (token bucket) and TTL caching for all outbound
requests. One module-level client instance is reused across tools.
"""

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

import httpx
from cachetools import TTLCache

# ---------------------------------------------------------------------------
# Base URL
# ---------------------------------------------------------------------------
CTGOV_BASE = "https://clinicaltrials.gov/api/v2"

# ---------------------------------------------------------------------------
# Rate limiter — token bucket
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

# TTL caches — trial data changes daily
_cache_15m: TTLCache = TTLCache(maxsize=1024, ttl=900)       # 15 min (search)
_cache_1h: TTLCache = TTLCache(maxsize=2048, ttl=3_600)      # 1 hour (records)
_cache_24h: TTLCache = TTLCache(maxsize=512, ttl=86_400)      # 24 hours (results)

# ---------------------------------------------------------------------------
# Cache key helper
# ---------------------------------------------------------------------------
def _cache_key(url: str, params: Optional[Dict[str, Any]]) -> str:
    raw = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Core request function
# ---------------------------------------------------------------------------
async def api_get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    cache_ttl: str = "1h",
) -> Dict[str, Any]:
    """
    GET JSON from ClinicalTrials.gov v2 API with rate-limiting and caching.

    Args:
        path: Endpoint path (e.g., "/studies").
        params: Query parameters.
        cache_ttl: "15m", "1h", or "24h" — which cache pool to use.

    Returns:
        Parsed JSON dict.

    Raises:
        httpx.HTTPStatusError on 4xx/5xx after retries.
        httpx.TimeoutException on timeout after retries.
    """
    url = f"{CTGOV_BASE}{path}"
    key = _cache_key(url, params)

    cache_map = {"15m": _cache_15m, "1h": _cache_1h, "24h": _cache_24h}
    cache = cache_map.get(cache_ttl, _cache_1h)
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


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------
async def search_studies(params: Dict[str, Any]) -> Dict[str, Any]:
    """Search studies — cached 15 min (results change with recruitment)."""
    return await api_get("/studies", params, cache_ttl="15m")


async def get_study(nct_id: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
    """Fetch a single study record — cached 1 hour."""
    params: Dict[str, Any] = {}
    if fields:
        params["fields"] = "|".join(fields)
    return await api_get(f"/studies/{nct_id}", params, cache_ttl="1h")


async def get_study_results(nct_id: str) -> Dict[str, Any]:
    """Fetch a study with results section — cached 24 hours (results are static)."""
    return await api_get(f"/studies/{nct_id}", cache_ttl="24h")


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------
def format_api_error(exc: Exception) -> str:
    """Return a user-friendly, actionable error string."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return "Error: Study not found. Verify the NCT ID is correct (format: NCT + 8 digits, e.g., NCT04567890)."
        if code == 429:
            return "Error: Rate limit exceeded. The server will retry automatically — please try again in a moment."
        if code == 503:
            return "Error: ClinicalTrials.gov API temporarily unavailable. Try again shortly."
        return f"Error: API returned status {code}."
    if isinstance(exc, httpx.TimeoutException):
        return "Error: Request timed out after 30 seconds. Try narrowing your search or try again later."
    return f"Error: {type(exc).__name__} — {exc}"
