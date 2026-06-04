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
Async HTTP client for the openFDA API.

Provides rate-limiting (token bucket) for all outbound requests.
No caching — fresh API call on every request.

openFDA rate limits:
- With API key: 240 requests/minute (4 per second)
- Without API key: 40 requests/minute

API key is optional, set via OPENFDA_API_KEY environment variable.
"""

import asyncio
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OPENFDA_BASE = "https://api.fda.gov"
API_KEY = os.environ.get("OPENFDA_API_KEY")

# Rate: 4/sec with key, 0.6/sec without
_RATE = 4.0 if API_KEY else 0.6
_CAPACITY = 4.0 if API_KEY else 2.0


# ---------------------------------------------------------------------------
# Rate limiter — token bucket
# ---------------------------------------------------------------------------
class TokenBucket:
    """Simple async-safe token-bucket rate limiter."""

    def __init__(self, rate: float, capacity: float):
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


_limiter = TokenBucket(rate=_RATE, capacity=_CAPACITY)


# ---------------------------------------------------------------------------
# Core request function
# ---------------------------------------------------------------------------
async def api_get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    GET JSON from openFDA API with rate-limiting and retry.

    Args:
        path: Endpoint path (e.g., "/drug/event.json").
        params: Query parameters.

    Returns:
        Parsed JSON dict.

    Raises:
        httpx.HTTPStatusError on 4xx/5xx after retries.
        httpx.TimeoutException on timeout after retries.
    """
    url = f"{OPENFDA_BASE}{path}"

    # Add API key if available
    if params is None:
        params = {}
    key_to_use = api_key or API_KEY
    if key_to_use:
        params["api_key"] = key_to_use

    last_exc: Optional[Exception] = None
    for attempt in range(3):
        await _limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
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
# Query builder helpers
# ---------------------------------------------------------------------------
def build_search_query(parts: List[str]) -> str:
    """Join non-empty search parts with AND."""
    valid = [p for p in parts if p]
    return " AND ".join(valid) if valid else ""


def escape_query_value(value: str) -> str:
    """Escape special characters in openFDA search values."""
    # openFDA uses Elasticsearch syntax; escape special chars
    # Escape backslash first to avoid double-escaping
    result = value.replace('\\', '\\\\')
    special = ['+', '-', '=', '&&', '||', '>', '<', '!', '(', ')', '{', '}',
               '[', ']', '^', '"', '~', '*', '?', ':', '/']
    for char in special:
        result = result.replace(char, f"\\{char}")
    return result


def quote_value(value: str) -> str:
    """Quote a value for exact matching."""
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


# ---------------------------------------------------------------------------
# Convenience wrappers for each endpoint
# ---------------------------------------------------------------------------
async def search_drug_events(
    api_key: Optional[str] = None,
    search: Optional[str] = None,
    count: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> Dict[str, Any]:
    """Search FAERS drug adverse event reports."""
    params: Dict[str, Any] = {"limit": min(limit, 100)}
    if search:
        params["search"] = search
    if count:
        params["count"] = count
    if skip > 0:
        params["skip"] = skip
    return await api_get(path="/drug/event.json", params=params, api_key=api_key)


async def search_device_events(
    api_key: Optional[str] = None,
    search: Optional[str] = None,
    count: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> Dict[str, Any]:
    """Search MAUDE device adverse event reports."""
    params: Dict[str, Any] = {"limit": min(limit, 100)}
    if search:
        params["search"] = search
    if count:
        params["count"] = count
    if skip > 0:
        params["skip"] = skip
    return await api_get(path="/device/event.json", params=params, api_key=api_key)


async def search_drug_enforcement(
    api_key: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> Dict[str, Any]:
    """Search drug recall/enforcement actions."""
    params: Dict[str, Any] = {"limit": min(limit, 100)}
    if search:
        params["search"] = search
    if skip > 0:
        params["skip"] = skip
    return await api_get(path="/drug/enforcement.json", params=params, api_key=api_key)


async def search_device_enforcement(
    api_key: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> Dict[str, Any]:
    """Search device recall/enforcement actions."""
    params: Dict[str, Any] = {"limit": min(limit, 100)}
    if search:
        params["search"] = search
    if skip > 0:
        params["skip"] = skip
    return await api_get(path="/device/enforcement.json", params=params, api_key=api_key)


async def search_510k(
    api_key: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> Dict[str, Any]:
    """Search 510(k) premarket notifications."""
    params: Dict[str, Any] = {"limit": min(limit, 100)}
    if search:
        params["search"] = search
    if skip > 0:
        params["skip"] = skip
    return await api_get(path="/device/510k.json", params=params, api_key=api_key)


async def search_device_classification(
    api_key: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> Dict[str, Any]:
    """Search FDA device classifications."""
    params: Dict[str, Any] = {"limit": min(limit, 100)}
    if search:
        params["search"] = search
    if skip > 0:
        params["skip"] = skip
    return await api_get(path="/device/classification.json", params=params, api_key=api_key)


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------
def format_api_error(exc: Exception) -> str:
    """Return a user-friendly, actionable error string."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return "Error: No results found matching your query."
        if code == 400:
            return "Error: Invalid query syntax. Check your search parameters."
        if code == 429:
            return "Error: Rate limit exceeded. The server will retry automatically — please try again in a moment."
        if code == 503:
            return "Error: openFDA API temporarily unavailable. Try again shortly."
        return f"Error: API returned status {code}."
    if isinstance(exc, httpx.TimeoutException):
        return "Error: Request timed out after 30 seconds. Try narrowing your search or try again later."
    return f"Error: {type(exc).__name__} — {exc}"
