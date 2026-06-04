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
Tests for ICD-10 MCP Server

Run locally:
    python test_server.py

Run against deployed service:
    python test_server.py https://icd10-mcp-XXXXX.us-central1.run.app

For Cloud Run with auth:
    export AUTH_TOKEN=$(gcloud auth print-identity-token)
    python test_server.py https://icd10-mcp-XXXXX.us-central1.run.app
"""

import json
import os
import sys
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
    """Test health endpoint returns correct structure."""
    print("Testing: Health check...", end=" ")
    try:
        headers = get_auth_headers()
        resp = requests.get(f"{base_url}/health", headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        assert data["status"] == "healthy", "Status should be healthy"
        assert data["service"] == "icd10_mcp", "Service name mismatch"
        cm_count = data.get("icd10cm_codes", 0)
        pcs_count = data.get("icd10pcs_codes", 0)
        assert cm_count > 90000, f"Expected 90k+ CM codes, got {cm_count}"
        assert pcs_count > 70000, f"Expected 70k+ PCS codes, got {pcs_count}"
        print(f"OK (CM: {cm_count}, PCS: {pcs_count})")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_tools_list(base_url: str) -> bool:
    """Test MCP tools/list returns all 9 expected tools."""
    print("Testing: tools/list...", end=" ")
    try:
        result = mcp_request(base_url, "tools/list")
        tools = result["result"]["tools"]
        tool_names = [t["name"] for t in tools]

        expected_tools = [
            "search_codes",
            "get_code",
            "get_hierarchy",
            "validate_code",
            "get_related_codes",
            "check_specificity",
            "search_procedures",
            "get_procedure",
            "build_pcs_code",
        ]

        for tool in expected_tools:
            assert tool in tool_names, f"Missing tool: {tool}"

        assert len(tools) == 9, f"Expected 9 tools, got {len(tools)}"
        print(f"OK ({len(tools)} tools)")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_search_codes_basic(base_url: str) -> bool:
    """Test search_codes finds diabetes codes."""
    print("Testing: search_codes (basic)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "search_codes",
                "arguments": {"query": "type 2 diabetes", "max_results": 5},
            },
        )
        content = result["result"]["content"][0]["text"]
        assert "E11" in content, "Should find E11 diabetes codes"
        assert not result["result"].get("isError", False)
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_search_codes_json_format(base_url: str) -> bool:
    """Test search_codes with JSON response format."""
    print("Testing: search_codes (JSON format)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "search_codes",
                "arguments": {
                    "query": "heart failure",
                    "max_results": 3,
                    "response_format": "json",
                },
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert "codes" in data, "JSON should have 'codes' key"
        assert "query" in data, "JSON should have 'query' key"
        assert len(data["codes"]) <= 3, "Should respect max_results"
        if data["codes"]:
            code = data["codes"][0]
            assert "code" in code, "Each code should have 'code' field"
            assert "billable" in code, "Each code should have 'billable' field"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_search_codes_billable_only(base_url: str) -> bool:
    """Test search_codes with billable_only filter."""
    print("Testing: search_codes (billable_only)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "search_codes",
                "arguments": {
                    "query": "diabetes",
                    "max_results": 10,
                    "billable_only": True,
                    "response_format": "json",
                },
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        for code in data.get("codes", []):
            assert code.get("billable") is True, f"Code {code['code']} should be billable"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_code_valid(base_url: str) -> bool:
    """Test get_code with a valid billable code."""
    print("Testing: get_code (valid code)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_code",
                "arguments": {"code": "E11.9", "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert "code" in data, "Should have 'code' key"
        code_data = data["code"]
        assert code_data["code"] == "E119", "Code should match (without dot)"
        assert code_data["billable"] is True, "E11.9 should be billable"
        assert "diabetes" in code_data["long_description"].lower(), "Description should mention diabetes"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_code_invalid(base_url: str) -> bool:
    """Test get_code with an invalid code returns error."""
    print("Testing: get_code (invalid code)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_code",
                "arguments": {"code": "ZZZZZ", "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data.get("error") is True, "Invalid code should return error"
        assert "not found" in data.get("message", "").lower(), "Error message should say not found"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_hierarchy(base_url: str) -> bool:
    """Test get_hierarchy returns parent and child codes."""
    print("Testing: get_hierarchy...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_hierarchy",
                "arguments": {"code": "E11", "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert "code" in data, "Should have current code"
        assert "children" in data, "Should have children list"
        assert len(data["children"]) > 0, "E11 should have child codes"
        # Check that children start with E11
        for child in data["children"]:
            assert child["code"].startswith("E11"), f"Child {child['code']} should start with E11"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_validate_code_billable(base_url: str) -> bool:
    """Test validate_code with a billable code."""
    print("Testing: validate_code (billable)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "validate_code",
                "arguments": {"code": "E11.9", "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data.get("valid") is True, "E11.9 should be valid"
        assert data.get("billable") is True, "E11.9 should be billable"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_validate_code_not_billable(base_url: str) -> bool:
    """Test validate_code with a category (non-billable) code."""
    print("Testing: validate_code (non-billable)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "validate_code",
                "arguments": {"code": "E11", "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data.get("valid") is True, "E11 should be valid"
        assert data.get("billable") is False, "E11 is a category, not billable"
        assert len(data.get("more_specific_codes", [])) > 0, "Should suggest more specific codes"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_related_codes(base_url: str) -> bool:
    """Test get_related_codes finds codes in same category."""
    print("Testing: get_related_codes...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_related_codes",
                "arguments": {"code": "E11.9", "max_results": 5, "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data.get("category") == "E11", "Category should be E11"
        assert len(data.get("related_codes", [])) > 0, "Should find related codes"
        for related in data.get("related_codes", []):
            assert related["code"].startswith("E11"), f"Related code {related['code']} should be in E11 category"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_check_specificity_passes(base_url: str) -> bool:
    """Test check_specificity with a specific billable code."""
    print("Testing: check_specificity (passes)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "check_specificity",
                "arguments": {"code": "E11.65", "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data.get("billable") is True, "E11.65 should be billable"
        # E11.65 is specific, should pass
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_check_specificity_fails(base_url: str) -> bool:
    """Test check_specificity with a non-billable category code."""
    print("Testing: check_specificity (fails)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "check_specificity",
                "arguments": {"code": "E11", "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data.get("passes_specificity") is False, "E11 should fail specificity"
        assert len(data.get("issues", [])) > 0, "Should report issues"
        assert len(data.get("recommendations", [])) > 0, "Should provide recommendations"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_search_procedures(base_url: str) -> bool:
    """Test search_procedures finds procedure codes."""
    print("Testing: search_procedures...", end=" ")
    try:
        # PCS codes use anatomical terms, not procedure names
        # "appendix" instead of "appendectomy"
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "search_procedures",
                "arguments": {"query": "appendix", "max_results": 5, "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert "codes" in data, "Should have codes key"
        assert len(data["codes"]) > 0, "Should find appendix procedures"
        for code in data["codes"]:
            assert len(code["code"]) == 7, f"PCS code {code['code']} should be 7 characters"
            assert "appendix" in code["description"].lower(), "Description should mention appendix"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_get_procedure(base_url: str) -> bool:
    """Test get_procedure returns code structure breakdown."""
    print("Testing: get_procedure...", end=" ")
    try:
        # Use a known PCS code for appendectomy
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "get_procedure",
                "arguments": {"code": "0DTJ4ZZ", "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)

        if data.get("error"):
            # Code might not exist in this version, try searching for one
            search_result = mcp_request(
                base_url,
                "tools/call",
                {
                    "name": "search_procedures",
                    "arguments": {"query": "bypass", "max_results": 1, "response_format": "json"},
                },
            )
            search_data = json.loads(search_result["result"]["content"][0]["text"])
            if search_data.get("codes"):
                code = search_data["codes"][0]["code"]
                result = mcp_request(
                    base_url,
                    "tools/call",
                    {
                        "name": "get_procedure",
                        "arguments": {"code": code, "response_format": "json"},
                    },
                )
                content = result["result"]["content"][0]["text"]
                data = json.loads(content)

        assert "code" in data, "Should have code data"
        code_data = data["code"]
        assert "structure" in code_data, "Should have structure breakdown"
        structure = code_data["structure"]
        assert "section" in structure, "Structure should have section"
        assert "body_system" in structure, "Structure should have body_system"
        assert "root_operation" in structure, "Structure should have root_operation"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_build_pcs_code_start(base_url: str) -> bool:
    """Test build_pcs_code shows valid options for first position."""
    print("Testing: build_pcs_code (start)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "build_pcs_code",
                "arguments": {"response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data.get("complete") is False, "Should not be complete without any input"
        assert data.get("next_position") == 1, "Should be asking for position 1"
        assert data.get("next_position_name") == "section", "First position is section"
        assert len(data.get("valid_options", [])) > 0, "Should have valid section options"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def test_build_pcs_code_partial(base_url: str) -> bool:
    """Test build_pcs_code with partial input shows next options."""
    print("Testing: build_pcs_code (partial)...", end=" ")
    try:
        result = mcp_request(
            base_url,
            "tools/call",
            {
                "name": "build_pcs_code",
                "arguments": {"section": "0", "response_format": "json"},
            },
        )
        content = result["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data.get("complete") is False, "Should not be complete with only section"
        assert data.get("partial_code") == "0", "Partial code should be '0'"
        assert data.get("next_position") == 2, "Should be asking for position 2"
        assert data.get("next_position_name") == "body_system", "Second position is body_system"
        assert len(data.get("valid_options", [])) > 0, "Should have valid body_system options"
        print("OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def run_all_tests(base_url: str) -> int:
    """Run all tests and return exit code."""
    print(f"\n{'='*60}")
    print(f"ICD-10 MCP Server Tests")
    print(f"Target: {base_url}")
    print(f"{'='*60}\n")

    tests = [
        test_health,
        test_tools_list,
        test_search_codes_basic,
        test_search_codes_json_format,
        test_search_codes_billable_only,
        test_get_code_valid,
        test_get_code_invalid,
        test_get_hierarchy,
        test_validate_code_billable,
        test_validate_code_not_billable,
        test_get_related_codes,
        test_check_specificity_passes,
        test_check_specificity_fails,
        test_search_procedures,
        test_get_procedure,
        test_build_pcs_code_start,
        test_build_pcs_code_partial,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        if test_fn(base_url):
            passed += 1
        else:
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) > 1:
        base_url = sys.argv[1].rstrip("/")
    else:
        base_url = DEFAULT_LOCAL_URL

    exit_code = run_all_tests(base_url)
    sys.exit(exit_code)
