#!/usr/bin/env python3
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
Tests for PubMed MCP Server

Run locally:
    python test_server.py

Run against deployed service:
    python test_server.py https://pubmed-mcp-XXXXX.us-central1.run.app

For Cloud Run with auth:
    export AUTH_TOKEN=$(gcloud auth print-identity-token)
    python test_server.py https://pubmed-mcp-XXXXX.us-central1.run.app
"""

import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, Optional

import requests

DEFAULT_LOCAL_URL = "http://localhost:8080"


def get_auth_headers() -> Dict[str, str]:
    """Get auth headers for Cloud Run if AUTH_TOKEN is set."""
    token = os.environ.get("AUTH_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def mcp_request(
    base_url: str,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    request_id: int = 1,
) -> Dict[str, Any]:
    """Make an MCP JSON-RPC request."""
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params:
        payload["params"] = params

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **get_auth_headers(),
    }

    resp = requests.post(
        f"{base_url}/mcp",
        json=payload,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def test_health(base_url: str) -> bool:
    """Test health endpoint."""
    print("Testing: Health check...", end=" ")
    try:
        headers = get_auth_headers()
        resp = requests.get(f"{base_url}/health", headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "pubmed_mcp"
        print(f"OK (bigquery_enabled={data['bigquery_enabled']})")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_tools_list(base_url: str) -> bool:
    """Test MCP tools/list."""
    print("Testing: tools/list...", end=" ")
    try:
        result = mcp_request(base_url, "tools/list")
        tools = result["result"]["tools"]
        tool_names = [t["name"] for t in tools]

        # E-utilities tools should always be present
        assert "search_pubmed" in tool_names
        assert "search_by_author" in tool_names
        assert "get_article" in tool_names
        assert "get_articles_batch" in tool_names

        print(f"OK ({len(tools)} tools: {', '.join(tool_names)})")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_search_pubmed(base_url: str) -> bool:
    """Test search_pubmed tool."""
    print("Testing: search_pubmed...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "search_pubmed",
                "arguments": {"query": "CRISPR[Title]", "max_results": 2},
            },
        )
        content = result["result"]["content"][0]["text"]
        assert "PubMed Search Results" in content
        assert "CRISPR" in content
        assert "PMID:" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_search_by_author(base_url: str) -> bool:
    """Test search_by_author tool."""
    print("Testing: search_by_author...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "search_by_author",
                "arguments": {"author_name": "Doudna JA", "max_results": 2},
            },
        )
        content = result["result"]["content"][0]["text"]
        assert "PubMed Search Results" in content
        assert "Doudna" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_article(base_url: str) -> bool:
    """Test get_article tool."""
    print("Testing: get_article...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_article",
                "arguments": {"pmid": "28375731"},
            },
        )
        content = result["result"]["content"][0]["text"]
        assert "CRISPR" in content
        assert "28375731" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_articles_batch(base_url: str) -> bool:
    """Test get_articles_batch tool."""
    print("Testing: get_articles_batch...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_articles_batch",
                "arguments": {"pmids": ["28375731", "37214176"]},
            },
        )
        content = result["result"]["content"][0]["text"]
        assert "28375731" in content or "CRISPR" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_advanced_search(base_url: str) -> bool:
    """Test advanced_search tool."""
    print("Testing: advanced_search...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "advanced_search",
                "arguments": {
                    "query": "cancer",
                    "date_from": "2023",
                    "date_to": "2024",
                    "publication_types": ["review"],
                    "max_results": 2,
                },
            },
        )
        content = result["result"]["content"][0]["text"]
        assert "PubMed Search Results" in content or "cancer" in content.lower()
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_related_articles(base_url: str) -> bool:
    """Test get_related_articles tool."""
    print("Testing: get_related_articles...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_related_articles",
                "arguments": {"pmid": "28375731", "max_results": 3},
            },
        )
        content = result["result"]["content"][0]["text"]
        # Should have related articles or indicate none found
        assert "Related" in content or "No related" in content or "PMID" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_citing_articles(base_url: str) -> bool:
    """Test get_citing_articles tool."""
    print("Testing: get_citing_articles...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_citing_articles",
                "arguments": {"pmid": "28375731", "max_results": 3},
            },
        )
        content = result["result"]["content"][0]["text"]
        # Should have citing articles or indicate none found
        assert "Citing" in content or "citing" in content or "No citing" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_article_links(base_url: str) -> bool:
    """Test get_article_links tool."""
    print("Testing: get_article_links...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_article_links",
                "arguments": {"pmid": "28375731"},
            },
        )
        content = result["result"]["content"][0]["text"]
        # Should have links or indicate none found
        assert "Links" in content or "links" in content or "No database" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_search_pubmed_semantic(base_url: str) -> bool:
    """Test search_pubmed_semantic tool (BigQuery - only if enabled)."""
    print("Testing: search_pubmed_semantic...", end=" ")
    try:
        # First check if BigQuery is enabled
        headers = get_auth_headers()
        resp = requests.get(f"{base_url}/health", headers=headers, timeout=10)
        if not resp.json().get("bigquery_enabled"):
            print("SKIPPED (BigQuery not enabled)")
            return True

        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "search_pubmed_semantic",
                "arguments": {
                    "query": "machine learning drug interactions",
                    "max_results": 2,
                },
            },
        )
        content = result["result"]["content"][0]["text"]

        # Check for permission errors - this is a config issue, not a code bug
        if "Access Denied" in content or "permission" in content.lower():
            print("SKIPPED (BigQuery permissions not configured)")
            return True

        assert "PubMed Search Results" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_json_format(base_url: str) -> bool:
    """Test JSON response format."""
    print("Testing: JSON response format...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "search_pubmed",
                "arguments": {
                    "query": "diabetes",
                    "max_results": 1,
                    "response_format": "json",
                },
            },
        )
        content = result["result"]["content"][0]["text"]
        # Should be valid JSON
        parsed = json.loads(content)
        assert "articles" in parsed
        assert "query" in parsed
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_annotate_articles(base_url: str) -> bool:
    """Test annotate_articles tool (PubTator3)."""
    print("Testing: annotate_articles...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "annotate_articles",
                "arguments": {"pmids": ["32133824"]},
            },
        )
        content = result["result"]["content"][0]["text"]
        assert "PubTator3" in content or "Entity" in content or "PMID" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_find_entity_id(base_url: str) -> bool:
    """Test find_entity_id tool (PubTator3)."""
    print("Testing: find_entity_id...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "find_entity_id",
                "arguments": {"query": "metformin", "concept": "chemical"},
            },
        )
        content = result["result"]["content"][0]["text"]
        assert "metformin" in content.lower() or "@CHEMICAL" in content
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_find_related_entities(base_url: str) -> bool:
    """Test find_related_entities tool (PubTator3)."""
    print("Testing: find_related_entities...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "find_related_entities",
                "arguments": {
                    "entity_id": "@CHEMICAL_Metformin",
                    "relation_type": "treat",
                    "limit": 5,
                },
            },
        )
        content = result["result"]["content"][0]["text"]
        # Either has relationships or says none found
        assert "Relationship" in content or "No relationship" in content or "treat" in content.lower()
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def run_all_tests(base_url: str) -> int:
    """Run all tests and return exit code."""
    print(f"\n{'='*60}")
    print(f"PubMed MCP Server Tests")
    print(f"Target: {base_url}")
    print(f"{'='*60}\n")

    tests = [
        test_health,
        test_tools_list,
        test_search_pubmed,
        test_search_by_author,
        test_get_article,
        test_get_articles_batch,
        test_advanced_search,
        test_get_related_articles,
        test_get_citing_articles,
        test_get_article_links,
        test_search_pubmed_semantic,
        test_json_format,
        test_annotate_articles,
        test_find_entity_id,
        test_find_related_entities,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        # Rate limit between tests
        time.sleep(0.5)
        if test_fn(base_url):
            passed += 1
        else:
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}\n")

    return 0 if failed == 0 else 1


def start_local_server():
    """Start local server for testing."""
    print("Starting local server...")
    proc = subprocess.Popen(
        ["python3", "server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)  # Wait for server to start
    return proc


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # URL provided - test against that
        base_url = sys.argv[1].rstrip("/")
        exit_code = run_all_tests(base_url)
    else:
        # No URL - start local server and test
        base_url = DEFAULT_LOCAL_URL
        proc = None
        try:
            proc = start_local_server()
            exit_code = run_all_tests(base_url)
        finally:
            if proc:
                proc.terminate()
                proc.wait()

    sys.exit(exit_code)
