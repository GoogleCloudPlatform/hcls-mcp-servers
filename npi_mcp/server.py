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
NPI Registry MCP Server

Wraps the CMS NPPES NPI Registry API into an MCP server that lets LLM
agents search for healthcare providers, look up provider details by NPI
number, and validate NPI check digits.

No authentication required for the upstream API.
Designed for stateless deployment on Google Cloud Run.
"""

import json
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api_client import (
    format_api_error,
    npi_get,
    validate_npi_format,
)

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "npi_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


def _json_out(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)



# Helper: format a single provider result

def _format_provider_markdown(result: Dict[str, Any]) -> List[str]:
    """Format a single NPPES result dict into markdown lines."""
    lines = []
    number = result.get("number", "")
    basic = result.get("basic", {})
    enum_type = result.get("enumeration_type", "")

    if enum_type == "NPI-1":
        # Individual provider
        name_parts = []
        if basic.get("credential"):
            name_parts.append(f"{basic.get('first_name', '')} {basic.get('last_name', '')}, {basic['credential']}")
        else:
            name_parts.append(f"{basic.get('first_name', '')} {basic.get('last_name', '')}")
        name = " ".join(name_parts).strip()
        lines.append(f"### {name}")
        lines.append(f"**NPI**: {number} | **Type**: Individual")
        if basic.get("gender"):
            lines.append(f"**Gender**: {basic['gender']}")
        status = basic.get("status", "A")
        lines.append(f"**Status**: {'Active' if status == 'A' else 'Deactivated'}")
    else:
        # Organization
        org_name = basic.get("organization_name", "Unknown Organization")
        lines.append(f"### {org_name}")
        lines.append(f"**NPI**: {number} | **Type**: Organization")
        if basic.get("authorized_official_first_name"):
            official = f"{basic.get('authorized_official_first_name', '')} {basic.get('authorized_official_last_name', '')}"
            lines.append(f"**Authorized Official**: {official.strip()}")
        status = basic.get("status", "A")
        lines.append(f"**Status**: {'Active' if status == 'A' else 'Deactivated'}")

    # Primary taxonomy (specialty)
    taxonomies = result.get("taxonomies", [])
    primary = next((t for t in taxonomies if t.get("primary")), None)
    if primary:
        desc = primary.get("desc", "")
        state = primary.get("state", "")
        license_num = primary.get("license", "")
        lines.append(f"**Specialty**: {desc}")
        if state and license_num:
            lines.append(f"**License**: {state} {license_num}")

    # Practice address
    addresses = result.get("addresses", [])
    practice = next((a for a in addresses if a.get("address_purpose") == "LOCATION"), None)
    if practice:
        addr_parts = [practice.get("address_1", "")]
        if practice.get("address_2"):
            addr_parts.append(practice["address_2"])
        city_state = f"{practice.get('city', '')}, {practice.get('state', '')} {practice.get('postal_code', '')[:5]}"
        addr_parts.append(city_state)
        lines.append(f"**Address**: {', '.join(addr_parts)}")
        if practice.get("telephone_number"):
            lines.append(f"**Phone**: {practice['telephone_number']}")

    lines.append("")
    return lines


def _extract_provider_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a structured summary from a single NPPES result."""
    basic = result.get("basic", {})
    enum_type = result.get("enumeration_type", "")

    summary: Dict[str, Any] = {
        "npi": result.get("number", ""),
        "type": "Individual" if enum_type == "NPI-1" else "Organization",
        "status": "Active" if basic.get("status", "A") == "A" else "Deactivated",
    }

    if enum_type == "NPI-1":
        summary["first_name"] = basic.get("first_name", "")
        summary["last_name"] = basic.get("last_name", "")
        summary["credential"] = basic.get("credential", "")
        summary["gender"] = basic.get("gender", "")
    else:
        summary["organization_name"] = basic.get("organization_name", "")

    # Primary taxonomy
    taxonomies = result.get("taxonomies", [])
    primary = next((t for t in taxonomies if t.get("primary")), None)
    if primary:
        summary["primary_taxonomy"] = {
            "code": primary.get("code", ""),
            "description": primary.get("desc", ""),
            "state": primary.get("state", ""),
            "license": primary.get("license", ""),
        }

    # Practice address
    addresses = result.get("addresses", [])
    practice = next((a for a in addresses if a.get("address_purpose") == "LOCATION"), None)
    if practice:
        summary["practice_address"] = {
            "address_1": practice.get("address_1", ""),
            "address_2": practice.get("address_2", ""),
            "city": practice.get("city", ""),
            "state": practice.get("state", ""),
            "postal_code": practice.get("postal_code", ""),
            "telephone_number": practice.get("telephone_number", ""),
        }

    return summary



# Tool 1: npi_search

@mcp.tool(
    name="npi_search",
    annotations={
        "title": "Search NPI Registry",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def npi_search(
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    organization_name: Optional[str] = None,
    taxonomy_description: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    postal_code: Optional[str] = None,
    enumeration_type: Optional[str] = None,
    use_first_name_alias: Optional[bool] = None,
    limit: int = 10,
    skip: int = 0,
    response_format: str = "markdown",
) -> str:
    """Search the CMS NPPES Registry for healthcare providers by name, location, specialty, or organization.

    At least one search parameter required (besides enumeration_type/country_code).
    State cannot be the only criterion - must combine with name, specialty, or city.

    Wildcard support (min 2 characters before *):
    - first_name: 'Jo*' matches John, Joseph, Jonathan
    - last_name: 'Smi*' matches Smith, Smithson, Smitty
    - organization_name: 'Mayo*' matches Mayo Clinic, Mayo Foundation
    - taxonomy_description: 'Cardio*' matches Cardiology, Cardiovascular Disease
    - postal_code: '212*' matches all ZIP codes starting with 212

    Name alias feature (default: ON):
    Automatically expands first name searches to include common nicknames:
    - Robert -> also finds Bob, Rob, Robbie, Bobby
    - William -> also finds Bill, Will, Billy, Willy
    Set use_first_name_alias=false for exact match only.

    Args:
        first_name: Provider first name (Individual NPI-1 only). Supports trailing
                    wildcard with min 2 chars (e.g., 'Jo*').
        last_name: Provider last name (Individual NPI-1 only). Supports trailing
                   wildcard with min 2 chars (e.g., 'Smi*').
        organization_name: Organization name (Organizational NPI-2 only). Searches
                          Legal Business Name, DBA, Former LBN, Other Names.
                          Trailing wildcard supported (min 2 chars).
        taxonomy_description: Provider specialty or taxonomy description. E.g.,
                             'Internal Medicine', 'Cardiology', 'Oncology',
                             'Family Practice'. Wildcard supported (min 2 chars).
        city: City name.
        state: Two-letter US state abbreviation (e.g., 'CA', 'NY', 'TX'). Cannot
               be sole search criterion.
        postal_code: 5 or 9 digit ZIP code. Wildcard supported (e.g., '212*').
        enumeration_type: Filter by provider type: 'NPI-1' = Individual providers,
                         'NPI-2' = Organizations. Cannot be sole search criterion.
        use_first_name_alias: Expand first name to include common aliases/nicknames.
                             Default: true. Set false for exact match only.
        limit: Results per request. Default: 10, Maximum: 200.
        skip: Number of records to skip for pagination. Maximum: 1000.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Matching providers with NPI, name, specialty, address, and contact info.
    """
    try:
        params: Dict[str, Any] = {
            "version": "2.1",
            "limit": min(limit, 200),
            "skip": min(skip, 1000),
        }

        if first_name:
            params["first_name"] = first_name
        if last_name:
            params["last_name"] = last_name
        if organization_name:
            params["organization_name"] = organization_name
        if taxonomy_description:
            params["taxonomy_description"] = taxonomy_description
        if city:
            params["city"] = city
        if state:
            params["state"] = state
        if postal_code:
            params["postal_code"] = postal_code
        if enumeration_type:
            params["enumeration_type"] = enumeration_type
        if use_first_name_alias is not None:
            params["use_first_name_alias"] = "true" if use_first_name_alias else "false"

        # Must have at least one real search param
        search_params = {k for k in params if k not in ("version", "limit", "skip", "enumeration_type")}
        if not search_params:
            return "Error: At least one search parameter required (name, specialty, city, postal_code, etc.)."

        data = await npi_get(params=params, cache_ttl="15m")

        result_count = data.get("result_count", 0)
        results = data.get("results", [])

        if not results:
            return "No providers found matching your search criteria. Try broadening your search or using wildcards (e.g., 'Smi*')."

        if response_format == "json":
            summaries = [_extract_provider_summary(r) for r in results]
            return _json_out({
                "result_count": result_count,
                "returned": len(results),
                "skip": skip,
                "results": summaries,
                "next_skip": skip + len(results) if skip + len(results) < result_count else None,
            })

        lines = [f"## NPI Search Results ({result_count} total, showing {len(results)})", ""]
        for r in results:
            lines.extend(_format_provider_markdown(r))

        if skip + len(results) < result_count:
            lines.append(f"*Use skip={skip + len(results)} to see more results.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 2: npi_lookup

@mcp.tool(
    name="npi_lookup",
    annotations={
        "title": "Look Up Provider by NPI",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def npi_lookup(
    npi: str,
    response_format: str = "markdown",
) -> str:
    """Get comprehensive provider details by NPI number from the CMS NPPES Registry.

    Returns full provider information including name, credentials, specialty,
    practice address, phone number, license details, and other identifiers.

    Args:
        npi: 10-digit National Provider Identifier. Format validated before
             API call. Example: '1234567893'
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Complete provider record including:
        - Provider type (Individual or Organization)
        - Name and credentials
        - Primary specialty/taxonomy
        - Practice address and phone
        - License state and number
        - Enumeration date
        - Status (Active/Deactivated)
    """
    try:
        # Validate format first
        validation = validate_npi_format(npi)
        if not validation["valid"]:
            return f"Error: {validation['error']}"

        data = await npi_get(params={"version": "2.1", "number": npi}, cache_ttl="1h")

        results = data.get("results", [])
        if not results:
            return f"No provider found for NPI {npi}. The NPI format is valid but it may not be assigned to any provider."

        result = results[0]

        if response_format == "json":
            summary = _extract_provider_summary(result)
            # Add extra detail fields for lookup
            basic = result.get("basic", {})
            summary["enumeration_date"] = basic.get("enumeration_date", "")
            summary["last_updated"] = basic.get("last_updated", "")
            summary["all_taxonomies"] = result.get("taxonomies", [])
            summary["all_addresses"] = result.get("addresses", [])
            summary["identifiers"] = result.get("identifiers", [])
            summary["other_names"] = result.get("other_names", [])
            return _json_out({"found": True, "provider": summary})

        lines = _format_provider_markdown(result)

        # Add extra detail for single lookup
        basic = result.get("basic", {})
        if basic.get("enumeration_date"):
            lines.append(f"**Enumeration Date**: {basic['enumeration_date']}")
        if basic.get("last_updated"):
            lines.append(f"**Last Updated**: {basic['last_updated']}")

        # All taxonomies
        taxonomies = result.get("taxonomies", [])
        if len(taxonomies) > 1:
            lines.append("")
            lines.append("#### All Specialties")
            for t in taxonomies:
                primary_tag = " (primary)" if t.get("primary") else ""
                lines.append(f"- {t.get('desc', 'Unknown')}{primary_tag} — Code: {t.get('code', '')}")

        # Other identifiers
        identifiers = result.get("identifiers", [])
        if identifiers:
            lines.append("")
            lines.append("#### Other Identifiers")
            for ident in identifiers:
                lines.append(f"- {ident.get('desc', 'Unknown')}: {ident.get('identifier', '')} ({ident.get('state', '')})")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 3: npi_validate

@mcp.tool(
    name="npi_validate",
    annotations={
        "title": "Validate NPI Check Digit",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,  # Local validation, no API call
    },
)
async def npi_validate(
    npi: str,
    response_format: str = "markdown",
) -> str:
    """Validate NPI format and Luhn check digit. Instant local validation - no API call.

    Checks that the NPI is exactly 10 digits and passes the Luhn algorithm
    validation with the healthcare prefix (80840).

    IMPORTANT: A valid check digit does NOT guarantee the NPI exists!
    Many mathematically valid NPIs have never been assigned.
    Use npi_lookup after validation to confirm the NPI is in NPPES.

    Args:
        npi: 10-digit National Provider Identifier to validate. May include
             leading/trailing whitespace (will be stripped). Must contain
             only digits.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Validation result: valid/invalid with explanation.
    """
    result = validate_npi_format(npi)

    if response_format == "json":
        return _json_out(result)

    if result["valid"]:
        return f"NPI **{result['npi']}** is **valid** (correct format and check digit). Use `npi_lookup` to verify it is assigned to a provider."
    else:
        return f"NPI **{result['npi']}** is **invalid**: {result['error']}"



# Tool 4: search_organizations

@mcp.tool(
    name="search_organizations",
    annotations={
        "title": "Search Healthcare Organizations",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_organizations(
    organization_name: Optional[str] = None,
    taxonomy_description: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    postal_code: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
    response_format: str = "markdown",
) -> str:
    """Search for healthcare organizations (hospitals, clinics, pharmacies, labs) in the NPPES Registry.

    Convenience wrapper that filters to NPI-2 (organizational) providers only.
    Useful for finding facilities by name, location, or type.

    Common specialty searches (taxonomy_description):
    - 'General Acute Care Hospital'
    - 'Pharmacy'
    - 'Clinical Laboratory'
    - 'Skilled Nursing Facility'
    - 'Home Health Agency'
    - 'Ambulatory Surgical Center'

    Args:
        organization_name: Organization name. Trailing wildcard supported
                          (min 2 chars, e.g., 'Mayo*').
        taxonomy_description: Organization type/specialty. Wildcard supported.
        city: City name.
        state: Two-letter US state abbreviation.
        postal_code: 5 or 9 digit ZIP code. Wildcard supported.
        limit: Results per request. Default: 10, Maximum: 200.
        skip: Number of records to skip for pagination. Maximum: 1000.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Matching organizations with NPI, name, type, address, and contact info.
    """
    try:
        params: Dict[str, Any] = {
            "version": "2.1",
            "enumeration_type": "NPI-2",
            "limit": min(limit, 200),
            "skip": min(skip, 1000),
        }

        if organization_name:
            params["organization_name"] = organization_name
        if taxonomy_description:
            params["taxonomy_description"] = taxonomy_description
        if city:
            params["city"] = city
        if state:
            params["state"] = state
        if postal_code:
            params["postal_code"] = postal_code

        search_params = {k for k in params if k not in ("version", "limit", "skip", "enumeration_type")}
        if not search_params:
            return "Error: At least one search parameter required (organization_name, taxonomy_description, city, state, or postal_code)."

        data = await npi_get(params=params, cache_ttl="15m")

        result_count = data.get("result_count", 0)
        results = data.get("results", [])

        if not results:
            return "No organizations found matching your search criteria. Try broadening your search or using wildcards (e.g., 'Mayo*')."

        if response_format == "json":
            summaries = [_extract_provider_summary(r) for r in results]
            return _json_out({
                "result_count": result_count,
                "returned": len(results),
                "skip": skip,
                "results": summaries,
                "next_skip": skip + len(results) if skip + len(results) < result_count else None,
            })

        lines = [f"## Organization Search Results ({result_count} total, showing {len(results)})", ""]
        for r in results:
            lines.extend(_format_provider_markdown(r))

        if skip + len(results) < result_count:
            lines.append(f"*Use skip={skip + len(results)} to see more results.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Health check

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "npi_mcp"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
