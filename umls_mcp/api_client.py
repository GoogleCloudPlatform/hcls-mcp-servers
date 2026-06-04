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
Thin async wrapper around the UMLS REST API.
Docs: https://documentation.uts.nlm.nih.gov/rest/home.html

Authentication: API key passed as `apiKey` query parameter on every request.
Rate limit: 20 requests/second per IP.
"""

import asyncio
import os
import time
import hashlib
import httpx
from cachetools import TTLCache

# ---------------------------------------------------------------------------
# Rate limiter – token-bucket, 20 req/s
# ---------------------------------------------------------------------------

class _TokenBucket:
    def __init__(self, rate: float = 20.0):
        self._rate = rate
        self._tokens = rate
        self._ts = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self._rate, self._tokens + (now - self._ts) * self._rate)
            self._ts = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


_bucket = _TokenBucket(20.0)

# ---------------------------------------------------------------------------
# Caches – keyed on (endpoint + params hash)
# ---------------------------------------------------------------------------

_search_cache: TTLCache = TTLCache(maxsize=512, ttl=3600)       # 1 hour
_concept_cache: TTLCache = TTLCache(maxsize=1024, ttl=86400)    # 24 hours
_relation_cache: TTLCache = TTLCache(maxsize=512, ttl=86400)    # 24 hours

BASE_URL = "https://uts-ws.nlm.nih.gov/rest"


def _cache_key(path: str, params: dict) -> str:
    """Deterministic cache key from path + sorted params (excluding apiKey)."""
    filtered = {k: v for k, v in sorted(params.items()) if k != "apiKey"}
    raw = f"{path}|{filtered}"
    return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Core HTTP helper
# ---------------------------------------------------------------------------

async def _get(path: str, params: dict, api_key: str, cache: TTLCache | None = None) -> dict:
    """Issue a GET to the UMLS REST API with rate limiting and optional caching."""
    params["apiKey"] = api_key

    if cache is not None:
        ck = _cache_key(path, params)
        if ck in cache:
            return cache[ck]

    await _bucket.acquire()

    url = f"{BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    if cache is not None:
        cache[ck] = data

    return data


# ---------------------------------------------------------------------------
# Public helpers – each maps to a UMLS REST endpoint
# ---------------------------------------------------------------------------

async def search(api_key: str, term: str, *,
                 sabs: str | None = None,
                 search_type: str = "words",
                 return_type: str = "concept",
                 page_size: int = 25,
                 page_number: int = 1) -> dict:
    """Search UMLS for concepts matching a term."""
    params: dict = {
        "string": term,
        "searchType": search_type,
        "returnIdType": return_type,
        "pageSize": min(page_size, 200),
        "pageNumber": page_number,
    }
    if sabs:
        params["sabs"] = sabs
    return await _get("/search/current", params, api_key, _search_cache)


async def get_concept(api_key: str, cui: str) -> dict:
    """Retrieve full concept info by CUI."""
    return await _get(f"/content/current/CUI/{cui}", {}, api_key, _concept_cache)


async def get_definitions(api_key: str, cui: str) -> dict:
    """Retrieve all definitions of a CUI across vocabularies."""
    return await _get(f"/content/current/CUI/{cui}/definitions", {}, api_key, _concept_cache)


async def get_relations(api_key: str, cui: str, *, page_size: int = 25, page_number: int = 1) -> dict:
    """Retrieve relationships of a CUI to other concepts."""
    params = {"pageSize": min(page_size, 200), "pageNumber": page_number}
    return await _get(f"/content/current/CUI/{cui}/relations", params, api_key, _relation_cache)


async def get_atoms(api_key: str, cui: str, *,
                    sabs: str | None = None,
                    page_size: int = 25,
                    page_number: int = 1) -> dict:
    """Retrieve atoms (source terms) for a CUI, optionally filtered by vocabulary."""
    params: dict = {"pageSize": min(page_size, 200), "pageNumber": page_number}
    if sabs:
        params["sabs"] = sabs
    return await _get(f"/content/current/CUI/{cui}/atoms", params, api_key, _concept_cache)


async def get_source_concept(api_key: str, source: str, source_id: str) -> dict:
    """Look up a source-asserted concept (e.g., SNOMEDCT_US / 44054006)."""
    return await _get(f"/content/current/source/{source}/{source_id}", {}, api_key, _concept_cache)


async def get_source_relations(api_key: str, source: str, source_id: str, *,
                               page_size: int = 25, page_number: int = 1) -> dict:
    """Get relations of a source concept (parents, children, etc.)."""
    params = {"pageSize": min(page_size, 200), "pageNumber": page_number}
    return await _get(f"/content/current/source/{source}/{source_id}/relations", params, api_key, _relation_cache)


async def get_source_parents(api_key: str, source: str, source_id: str) -> dict:
    """Get immediate parents of a source concept."""
    return await _get(f"/content/current/source/{source}/{source_id}/parents", {}, api_key, _relation_cache)


async def get_source_children(api_key: str, source: str, source_id: str) -> dict:
    """Get immediate children of a source concept."""
    return await _get(f"/content/current/source/{source}/{source_id}/children", {}, api_key, _relation_cache)


async def get_source_ancestors(api_key: str, source: str, source_id: str) -> dict:
    """Get all ancestors of a source concept (path to root)."""
    return await _get(f"/content/current/source/{source}/{source_id}/ancestors", {}, api_key, _relation_cache)


async def crosswalk(api_key: str, source: str, source_id: str, *,
                    target_source: str | None = None,
                    page_size: int = 25, page_number: int = 1) -> dict:
    """Map a code from one vocabulary to equivalent codes in other vocabularies."""
    params: dict = {"pageSize": min(page_size, 200), "pageNumber": page_number}
    if target_source:
        params["targetSource"] = target_source
    return await _get(f"/crosswalk/current/source/{source}/{source_id}", params, api_key, _search_cache)


async def get_semantic_type(api_key: str, tui: str) -> dict:
    """Look up a semantic type by its TUI."""
    return await _get(f"/semantic-network/current/TUI/{tui}", {}, api_key, _concept_cache)


async def get_semantic_types_list(api_key: str) -> dict:
    """List all UMLS semantic types."""
    return await _get("/semantic-network/current", {}, api_key, _concept_cache)
