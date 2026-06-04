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
Shared async HTTP client for RxNav and DailyMed APIs.

Provides rate-limiting (token bucket) and TTL caching for all outbound
requests.  One module-level client instance is reused across tools.
"""

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, Optional

import httpx
from cachetools import TTLCache

# ---------------------------------------------------------------------------
# Base URLs
# ---------------------------------------------------------------------------
RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
RXCLASS_BASE = "https://rxnav.nlm.nih.gov/REST/rxclass"
INTERACTION_BASE = "https://rxnav.nlm.nih.gov/REST/interaction"
DAILYMED_BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"

# ---------------------------------------------------------------------------
# Rate limiter — token bucket (20 req/s for RxNav, conservative default)
# ---------------------------------------------------------------------------
class TokenBucket:
    """Simple async-safe token-bucket rate limiter."""

    def __init__(self, rate: float = 15.0, capacity: float = 15.0):
        self._rate = rate          # tokens per second
        self._capacity = capacity  # max burst
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

# Module-level instances
_rxnav_limiter = TokenBucket(rate=15.0, capacity=15.0)   # RxNav APIs
_dailymed_limiter = TokenBucket(rate=10.0, capacity=10.0) # DailyMed (conservative)

# TTL caches — drug data changes infrequently
_cache_24h: TTLCache = TTLCache(maxsize=2048, ttl=86_400)    # 24 hours
_cache_7d: TTLCache = TTLCache(maxsize=512, ttl=604_800)     # 7 days

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
    base_url: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    cache_ttl: str = "24h",
) -> Dict[str, Any]:
    """
    GET JSON from an API with rate-limiting and caching.

    Args:
        base_url: One of the *_BASE constants above.
        path: Endpoint path (e.g., "/rxcui.json").
        params: Query parameters.
        cache_ttl: "24h" or "7d" — which cache pool to use.

    Returns:
        Parsed JSON dict.

    Raises:
        httpx.HTTPStatusError on 4xx/5xx after retries.
        httpx.TimeoutException on timeout after retries.
    """
    url = f"{base_url}{path}"
    key = _cache_key(url, params)

    # Check cache
    cache = _cache_7d if cache_ttl == "7d" else _cache_24h
    if key in cache:
        return cache[key]

    # Pick rate limiter
    limiter = _dailymed_limiter if "dailymed" in base_url else _rxnav_limiter

    # Retry with exponential backoff on 429/503
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        await limiter.acquire()
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
async def rxnorm_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await api_get(RXNORM_BASE, path, params)


async def rxclass_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await api_get(RXCLASS_BASE, path, params, cache_ttl="7d")


async def interaction_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await api_get(INTERACTION_BASE, path, params)


async def dailymed_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await api_get(DAILYMED_BASE, path, params)


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------
def format_api_error(exc: Exception) -> str:
    """Return a user-friendly, actionable error string."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return "Error: Resource not found. Verify the identifier (RxCUI, NDC, or setId) is correct."
        if code == 429:
            return "Error: Rate limit exceeded. The server will retry automatically — please try again in a moment."
        if code == 503:
            return "Error: Upstream API temporarily unavailable. Try again shortly."
        return f"Error: API returned status {code}."
    if isinstance(exc, httpx.TimeoutException):
        return "Error: Request timed out after 30 seconds. Try a simpler query or try again later."
    return f"Error: {type(exc).__name__} — {exc}"
