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
ICD-10 MCP Server

Provides ICD-10-CM (diagnosis) and ICD-10-PCS (procedure) code lookup,
search, validation, and hierarchy navigation.

Data is bundled from CMS at build time. No external API dependencies.
"""

import json
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api_client import (
    build_pcs_code,
    check_cm_specificity,
    ensure_loaded,
    get_cm_code,
    get_cm_hierarchy,
    get_code_counts,
    get_pcs_code,
    get_related_cm_codes,
    search_cm_codes,
    search_pcs_codes,
    validate_cm_code,
)

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "icd10_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


def _json_out(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _format_cm_results(results: Dict[str, Any], response_format: str) -> str:
    """Format ICD-10-CM results as markdown or JSON."""
    if results.get("error"):
        return _json_out(results)

    if response_format == "json":
        return _json_out(results)

    codes = results.get("codes", [])
    total = results.get("total_results", len(codes))
    returned = results.get("returned_results", len(codes))
    query = results.get("query", "")

    lines = ["## ICD-10-CM Search Results"]
    if query:
        lines.append(f"**Query:** {query}")
    lines.append(f"**Results:** {returned} of {total}")
    lines.append("")

    if not codes:
        lines.append("No codes found.")
    else:
        for code in codes:
            billable = "Yes" if code.get("billable") else "No"
            lines.append(f"### {code['code']}")
            lines.append(f"**{code.get('long_description', code.get('short_description', ''))}**")
            lines.append(f"Billable: {billable}")
            lines.append("")

    return "\n".join(lines)


def _format_pcs_results(results: Dict[str, Any], response_format: str) -> str:
    """Format ICD-10-PCS results as markdown or JSON."""
    if results.get("error"):
        return _json_out(results)

    if response_format == "json":
        return _json_out(results)

    codes = results.get("codes", [])
    total = results.get("total_results", len(codes))
    returned = results.get("returned_results", len(codes))
    query = results.get("query", "")

    lines = ["## ICD-10-PCS Search Results"]
    if query:
        lines.append(f"**Query:** {query}")
    lines.append(f"**Results:** {returned} of {total}")
    lines.append("")

    if not codes:
        lines.append("No codes found.")
    else:
        for code in codes:
            lines.append(f"### {code['code']}")
            lines.append(f"**{code.get('description', '')}**")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ICD-10-CM Tools (Diagnosis Codes)
# ---------------------------------------------------------------------------

@mcp.tool(
    name="search_codes",
    annotations={
        "title": "Search ICD-10-CM Diagnosis Codes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def search_codes(
    query: str,
    max_results: int = 20,
    billable_only: bool = False,
    response_format: str = "markdown",
) -> str:
    """Search ICD-10-CM diagnosis codes by keyword or phrase.

    Searches code values and descriptions. Use natural language terms
    like "heart attack", "type 2 diabetes", or "broken arm".

    Args:
        query: Search term (e.g., "diabetes", "chest pain", "E11")
        max_results: Maximum results to return (default: 20)
        billable_only: If True, only return codes valid for billing
        response_format: Output format - "markdown" or "json"

    Returns:
        Matching ICD-10-CM codes with descriptions and billable status.
    """
    results = search_cm_codes(query, max_results, billable_only)
    return _format_cm_results(results, response_format)


@mcp.tool(
    name="get_code",
    annotations={
        "title": "Get ICD-10-CM Code Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_code(
    code: str,
    response_format: str = "markdown",
) -> str:
    """Get full details for a specific ICD-10-CM diagnosis code.

    Returns the code's short and long descriptions, and whether it's
    billable (valid for claims submission).

    Args:
        code: ICD-10-CM code (e.g., "E11.9", "I21.0", "S52.501A")
        response_format: Output format - "markdown" or "json"

    Returns:
        Code details including descriptions and billable status.
    """
    result = get_cm_code(code)

    if result.get("error"):
        return _json_out(result)

    if response_format == "json":
        return _json_out(result)

    code_data = result["code"]
    billable = "Yes" if code_data.get("billable") else "No"

    lines = [
        f"## {code_data['code']}",
        f"**{code_data.get('long_description', '')}**",
        "",
        f"**Short Description:** {code_data.get('short_description', '')}",
        f"**Billable:** {billable}",
    ]

    return "\n".join(lines)


@mcp.tool(
    name="get_hierarchy",
    annotations={
        "title": "Get ICD-10-CM Code Hierarchy",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_hierarchy(
    code: str,
    response_format: str = "markdown",
) -> str:
    """Get parent and child codes for an ICD-10-CM code.

    Shows the code's position in the ICD-10-CM hierarchy - its parent
    categories and more specific child codes.

    Args:
        code: ICD-10-CM code (e.g., "E11", "I21")
        response_format: Output format - "markdown" or "json"

    Returns:
        Parent codes (categories) and child codes (more specific).
    """
    result = get_cm_hierarchy(code)

    if result.get("error"):
        return _json_out(result)

    if response_format == "json":
        return _json_out(result)

    current = result["code"]
    parents = result.get("parents", [])
    children = result.get("children", [])

    lines = [
        f"## Hierarchy for {current['code']}",
        f"**{current.get('long_description', '')}**",
        "",
    ]

    if parents:
        lines.append("### Parent Categories")
        for p in parents:
            lines.append(f"- **{p['code']}** - {p.get('short_description', '')}")
        lines.append("")

    if children:
        lines.append("### Child Codes (More Specific)")
        for c in children:
            billable = "(billable)" if c.get("billable") else ""
            lines.append(f"- **{c['code']}** - {c.get('short_description', '')} {billable}")
    else:
        lines.append("*No more specific codes - this is a leaf code.*")

    return "\n".join(lines)


@mcp.tool(
    name="validate_code",
    annotations={
        "title": "Validate ICD-10-CM Code",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def validate_code(
    code: str,
    response_format: str = "markdown",
) -> str:
    """Validate an ICD-10-CM code for billing.

    Checks if the code exists, is billable, and suggests more specific
    codes if needed.

    Args:
        code: ICD-10-CM code to validate
        response_format: Output format - "markdown" or "json"

    Returns:
        Validation result with billable status and suggestions.
    """
    result = validate_cm_code(code)

    if response_format == "json":
        return _json_out(result)

    lines = [f"## Validation: {code}"]

    if not result.get("valid"):
        lines.append(f"**Status:** Invalid - {result.get('message', 'Code not found')}")
        suggestions = result.get("suggestions", [])
        if suggestions:
            lines.append("")
            lines.append("**Did you mean:**")
            for s in suggestions:
                lines.append(f"- {s['code']} - {s.get('short_description', '')}")
    else:
        code_data = result.get("code", {})
        billable = result.get("billable", False)

        if billable:
            lines.append("**Status:** Valid and billable")
        else:
            lines.append("**Status:** Valid but NOT billable (category code)")
            lines.append("")
            lines.append("Use one of these more specific codes:")
            for s in result.get("more_specific_codes", [])[:10]:
                lines.append(f"- **{s['code']}** - {s.get('short_description', '')}")

    return "\n".join(lines)


@mcp.tool(
    name="get_related_codes",
    annotations={
        "title": "Get Related ICD-10-CM Codes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_related_codes_tool(
    code: str,
    max_results: int = 20,
    response_format: str = "markdown",
) -> str:
    """Find ICD-10-CM codes related to a given code.

    Returns other codes in the same category that may be relevant
    for documentation or differential diagnosis.

    Args:
        code: ICD-10-CM code
        max_results: Maximum related codes to return
        response_format: Output format - "markdown" or "json"

    Returns:
        Related codes in the same category.
    """
    result = get_related_cm_codes(code, max_results)

    if result.get("error"):
        return _json_out(result)

    if response_format == "json":
        return _json_out(result)

    current = result["code"]
    category = result.get("category", "")
    related = result.get("related_codes", [])
    total = result.get("total_in_category", 0)

    lines = [
        f"## Related Codes for {current['code']}",
        f"**Category:** {category}",
        f"**Total in category:** {total}",
        "",
    ]

    if related:
        for r in related:
            billable = "(billable)" if r.get("billable") else ""
            lines.append(f"- **{r['code']}** - {r.get('short_description', '')} {billable}")
    else:
        lines.append("No related codes found.")

    return "\n".join(lines)


@mcp.tool(
    name="check_specificity",
    annotations={
        "title": "Check Code Specificity",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def check_specificity_tool(
    code: str,
    response_format: str = "markdown",
) -> str:
    """Check if an ICD-10-CM code has specificity issues.

    Identifies codes that are "unspecified" or not billable and
    suggests more specific alternatives.

    Args:
        code: ICD-10-CM code to check
        response_format: Output format - "markdown" or "json"

    Returns:
        Specificity analysis with recommendations.
    """
    result = check_cm_specificity(code)

    if result.get("error"):
        return _json_out(result)

    if response_format == "json":
        return _json_out(result)

    code_data = result.get("code", {})
    passes = result.get("passes_specificity", False)
    issues = result.get("issues", [])
    recommendations = result.get("recommendations", [])

    lines = [
        f"## Specificity Check: {code_data.get('code', code)}",
        f"**Description:** {code_data.get('long_description', '')}",
        "",
    ]

    if passes:
        lines.append("**Result:** Passes specificity requirements")
    else:
        lines.append("**Result:** Specificity issues found")
        lines.append("")

        if issues:
            lines.append("### Issues")
            for issue in issues:
                lines.append(f"- {issue}")
            lines.append("")

        if recommendations:
            lines.append("### Recommendations")
            for rec in recommendations:
                lines.append(f"**{rec.get('issue', '')}**")
                for opt in rec.get("options", [])[:5]:
                    lines.append(f"- {opt['code']} - {opt.get('short_description', '')}")
                lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ICD-10-PCS Tools (Procedure Codes)
# ---------------------------------------------------------------------------

@mcp.tool(
    name="search_procedures",
    annotations={
        "title": "Search ICD-10-PCS Procedure Codes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def search_procedures(
    query: str,
    max_results: int = 20,
    response_format: str = "markdown",
) -> str:
    """Search ICD-10-PCS inpatient procedure codes.

    Use terms like "appendectomy", "hip replacement", or "bypass".

    Args:
        query: Search term (e.g., "appendectomy", "knee replacement")
        max_results: Maximum results to return
        response_format: Output format - "markdown" or "json"

    Returns:
        Matching ICD-10-PCS procedure codes.
    """
    results = search_pcs_codes(query, max_results)
    return _format_pcs_results(results, response_format)


@mcp.tool(
    name="get_procedure",
    annotations={
        "title": "Get ICD-10-PCS Procedure Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_procedure(
    code: str,
    response_format: str = "markdown",
) -> str:
    """Get details for a specific ICD-10-PCS procedure code.

    Returns the code description and breaks down the 7-character
    structure (section, body system, operation, etc.).

    Args:
        code: 7-character ICD-10-PCS code
        response_format: Output format - "markdown" or "json"

    Returns:
        Procedure details including code structure breakdown.
    """
    result = get_pcs_code(code)

    if result.get("error"):
        return _json_out(result)

    if response_format == "json":
        return _json_out(result)

    code_data = result["code"]
    structure = code_data.get("structure", {})

    lines = [
        f"## {code_data['code']}",
        f"**{code_data.get('description', '')}**",
        "",
    ]

    if structure:
        lines.append("### Code Structure")
        lines.append(f"1. **Section:** {structure.get('section', '')}")
        lines.append(f"2. **Body System:** {structure.get('body_system', '')}")
        lines.append(f"3. **Root Operation:** {structure.get('root_operation', '')}")
        lines.append(f"4. **Body Part:** {structure.get('body_part', '')}")
        lines.append(f"5. **Approach:** {structure.get('approach', '')}")
        lines.append(f"6. **Device:** {structure.get('device', '')}")
        lines.append(f"7. **Qualifier:** {structure.get('qualifier', '')}")

    return "\n".join(lines)


@mcp.tool(
    name="build_pcs_code",
    annotations={
        "title": "Build ICD-10-PCS Code",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def build_pcs_code_tool(
    section: Optional[str] = None,
    body_system: Optional[str] = None,
    root_operation: Optional[str] = None,
    body_part: Optional[str] = None,
    approach: Optional[str] = None,
    device: Optional[str] = None,
    qualifier: Optional[str] = None,
    response_format: str = "markdown",
) -> str:
    """Build an ICD-10-PCS code step by step.

    Provide values for each position to see valid options for the
    next position. All 7 positions are needed for a complete code.

    Args:
        section: Position 1 - Section (e.g., "0" for Medical/Surgical)
        body_system: Position 2 - Body System
        root_operation: Position 3 - Root Operation
        body_part: Position 4 - Body Part
        approach: Position 5 - Approach
        device: Position 6 - Device
        qualifier: Position 7 - Qualifier
        response_format: Output format - "markdown" or "json"

    Returns:
        Valid options for the next position, or final code if complete.
    """
    result = build_pcs_code(
        section=section,
        body_system=body_system,
        root_operation=root_operation,
        body_part=body_part,
        approach=approach,
        device=device,
        qualifier=qualifier,
    )

    if response_format == "json":
        return _json_out(result)

    if result.get("complete"):
        code_data = result["code"]
        lines = [
            "## Complete PCS Code",
            f"**Code:** {code_data['code']}",
            f"**Description:** {code_data.get('description', '')}",
        ]
        return "\n".join(lines)

    if result.get("error"):
        return f"Error: {result['error']}"

    partial = result.get("partial_code", "")
    next_pos = result.get("next_position", 1)
    next_name = result.get("next_position_name", "")
    options = result.get("valid_options", [])
    examples = result.get("example_codes", [])

    lines = [
        f"## Building PCS Code",
        f"**Partial code:** {partial if partial else '(empty)'}",
        f"**Next position:** {next_pos} ({next_name})",
        "",
        f"**Valid options for position {next_pos}:** {', '.join(options)}",
        "",
    ]

    if examples:
        lines.append("**Example codes with this prefix:**")
        for ex in examples[:3]:
            lines.append(f"- {ex['code']} - {ex.get('description', '')[:60]}...")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for Cloud Run."""
    counts = get_code_counts()
    return JSONResponse({
        "status": "healthy",
        "service": "icd10_mcp",
        "icd10cm_codes": counts.get("icd10cm_codes", 0),
        "icd10pcs_codes": counts.get("icd10pcs_codes", 0),
    })


if __name__ == "__main__":
    # Pre-load data on startup
    print("Loading ICD-10 code data...")
    ensure_loaded()

    print(f"Starting ICD-10 MCP Server on port {PORT}")
    print(f"MCP endpoint: http://localhost:{PORT}/mcp")
    mcp.run(transport="streamable-http")
