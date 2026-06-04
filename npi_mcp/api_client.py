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
Shared async HTTP client for the NPPES NPI Registry API.

Provides rate-limiting (token bucket), TTL caching, and NPI validation
for all outbound requests.  One module-level client instance is reused
across tools.
"""

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

import httpx
from cachetools import TTLCache


# Base URL

NPPES_BASE = "https://npiregistry.cms.hhs.gov/api"


# Rate limiter — token bucket (10 req/s, conservative)

class TokenBucket:
    """Simple async-safe token-bucket rate limiter."""

    def __init__(self, rate: float = 10.0, capacity: float = 10.0):
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

_limiter = TokenBucket(rate=10.0, capacity=10.0)

# TTL caches
_cache_1h: TTLCache = TTLCache(maxsize=2048, ttl=3_600)     # single lookups
_cache_15m: TTLCache = TTLCache(maxsize=1024, ttl=900)       # search results


# Cache key helper

def _cache_key(url: str, params: Optional[Dict[str, Any]]) -> str:
    raw = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# Core request function

async def api_get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    cache_ttl: str = "1h",
) -> Dict[str, Any]:
    """
    GET JSON from the NPPES API with rate-limiting and caching.

    Args:
        path: Endpoint path (e.g., "/" for the main search).
        params: Query parameters.
        cache_ttl: "1h" or "15m" — which cache pool to use.

    Returns:
        Parsed JSON dict.

    Raises:
        httpx.HTTPStatusError on 4xx/5xx after retries.
        httpx.TimeoutException on timeout after retries.
    """
    url = f"{NPPES_BASE}{path}"
    key = _cache_key(url, params)

    cache = _cache_15m if cache_ttl == "15m" else _cache_1h
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


# Convenience wrapper

async def npi_get(params: Optional[Dict[str, Any]] = None, cache_ttl: str = "15m") -> Dict[str, Any]:
    """Search or lookup the NPPES registry."""
    return await api_get("/", params=params, cache_ttl=cache_ttl)


# NPI Luhn validation (local, no API call)

def validate_npi_format(npi: str) -> Dict[str, Any]:
    """
    Validate NPI format and Luhn check digit.

    The NPI is a 10-digit number. Validation uses the Luhn algorithm
    with the healthcare prefix '80840' prepended.

    Returns:
        Dict with 'valid' (bool), 'npi' (str), and 'error' (str or None).
    """
    npi = npi.strip()

    if not npi.isdigit():
        return {"valid": False, "npi": npi, "error": "NPI must contain only digits."}
    if len(npi) != 10:
        return {"valid": False, "npi": npi, "error": f"NPI must be exactly 10 digits (got {len(npi)})."}

    # Luhn check with healthcare prefix 80840
    prefixed = "80840" + npi
    total = 0
    for i, ch in enumerate(reversed(prefixed)):
        digit = int(ch)
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit

    if total % 10 != 0:
        return {"valid": False, "npi": npi, "error": "Invalid check digit (Luhn validation failed)."}

    return {"valid": True, "npi": npi, "error": None}


# Error formatting

def format_api_error(exc: Exception) -> str:
    """Return a user-friendly, actionable error string."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return "Error: Resource not found. Verify the NPI number is correct."
        if code == 429:
            return "Error: Rate limit exceeded. Try again in a moment."
        if code == 503:
            return "Error: NPPES API temporarily unavailable. Try again shortly."
        return f"Error: API returned status {code}."
    if isinstance(exc, httpx.TimeoutException):
        return "Error: Request timed out after 30 seconds. Try a simpler query or try again later."
    return f"Error: {type(exc).__name__} — {exc}"
