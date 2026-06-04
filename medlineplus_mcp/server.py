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
MedlinePlus MCP Server

Wraps two NLM services — MedlinePlus Connect and MedlinePlus Web Service —
into a single MCP server that lets LLM agents look up patient-friendly
health information by medical code or keyword search.

No authentication required for either upstream API.
Designed for stateless deployment on Google Cloud Run.
"""

import json
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api_client import (
    CODE_SYSTEM_NAMES,
    CODE_SYSTEMS,
    connect_get,
    format_api_error,
    parse_connect_entries,
    web_search,
)

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "medlineplus_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


def _json_out(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)



# Tool 1: search_health_topics

@mcp.tool(
    name="search_health_topics",
    annotations={
        "title": "Search MedlinePlus Health Topics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_health_topics(
    term: str,
    max_results: int = 10,
    language: str = "en",
    response_format: str = "markdown",
) -> str:
    """Search MedlinePlus health topics by keyword.

    Returns ranked health topics from MedlinePlus with titles, summaries,
    and links to full articles. Useful for finding patient-friendly health
    education materials.

    Args:
        term: Search query (e.g., "diabetes", "high blood pressure",
              "asthma in children"). Natural language queries work well.
        max_results: Maximum results to return (default 10, max 50).
        language: Language for results. "en" for English (default),
                  "es" for Spanish.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Ranked list of health topics with titles, summaries, and URLs
        to full MedlinePlus articles.
    """
    try:
        data = await web_search(
            term=term,
            max_results=min(max_results, 50),
            language=language,
        )

        results = data.get("results", [])
        total = data.get("total", len(results))

        if not results:
            return f"No health topics found for '{term}'. Try a broader search term or check spelling."

        if response_format == "json":
            return _json_out({
                "query": term,
                "total": total,
                "returned": len(results),
                "language": language,
                "results": results,
            })

        lines = [f"## MedlinePlus Health Topics: '{term}' ({total} results)", ""]
        for r in results:
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            org = r.get("organizationName", "")

            lines.append(f"### {title}")
            if snippet:
                lines.append(f"{snippet}")
            if org:
                lines.append(f"*Source: {org}*")
            if url:
                lines.append(f"[Read more]({url})")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 2: get_health_info_by_code

@mcp.tool(
    name="get_health_info_by_code",
    annotations={
        "title": "Get Health Info by Medical Code",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_health_info_by_code(
    code: str,
    code_system: str,
    display_name: Optional[str] = None,
    language: str = "en",
    response_format: str = "markdown",
) -> str:
    """Look up patient-friendly health information by medical code.

    Uses MedlinePlus Connect to find health education materials for a
    specific diagnosis, medication, lab test, or procedure code.

    Supported code systems (use shorthand or full OID):
    - "icd10" — ICD-10-CM diagnosis codes (e.g., "E11.65")
    - "snomed" — SNOMED CT codes
    - "rxnorm" — RxNorm drug codes (RxCUI, e.g., "161354")
    - "ndc" — National Drug Codes
    - "loinc" — LOINC lab test codes (e.g., "2339-0")
    - "cpt" — CPT procedure codes

    Args:
        code: The medical code value (e.g., "E11.65", "161354", "2339-0").
        code_system: Code system shorthand or OID. Shorthands: "icd10",
                     "snomed", "rxnorm", "ndc", "loinc", "cpt".
        display_name: Optional display name for the code (helps improve
                      matching).
        language: "en" for English (default), "es" for Spanish.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Patient-friendly health information entries with titles, summaries,
        and links to full MedlinePlus articles.
    """
    try:
        # Validate code system
        cs_lower = code_system.lower()
        if cs_lower not in CODE_SYSTEMS and not code_system.startswith("2.16."):
            valid = ", ".join(sorted(set(k for k in CODE_SYSTEMS.keys()
                                        if k not in ("icd10cm", "icd9cm", "snomedct", "rxcui"))))
            return f"Error: Unknown code system '{code_system}'. Valid options: {valid}"

        data = await connect_get(
            code=code,
            code_system=code_system,
            display_name=display_name,
            language=language,
        )

        entries = parse_connect_entries(data)

        if not entries:
            cs_name = CODE_SYSTEM_NAMES.get(
                CODE_SYSTEMS.get(cs_lower, code_system), code_system
            )
            return f"No health information found for {cs_name} code '{code}'. The code may not have associated MedlinePlus content."

        if response_format == "json":
            return _json_out({
                "code": code,
                "code_system": code_system,
                "language": language,
                "entries": entries,
            })

        cs_oid = CODE_SYSTEMS.get(cs_lower, code_system)
        cs_name = CODE_SYSTEM_NAMES.get(cs_oid, code_system)
        lines = [f"## Health Info for {cs_name} Code: {code}", ""]

        for entry in entries:
            title = entry.get("title", "Untitled")
            url = entry.get("url", "")
            summary = entry.get("summary", "")

            lines.append(f"### {title}")
            if summary:
                # Truncate long summaries
                if len(summary) > 500:
                    summary = summary[:497] + "..."
                lines.append(summary)
            if url:
                lines.append(f"[Read full article]({url})")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 3: get_drug_information

@mcp.tool(
    name="get_drug_information",
    annotations={
        "title": "Get Consumer Drug Information",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_drug_information(
    code: str,
    code_system: str = "rxnorm",
    display_name: Optional[str] = None,
    language: str = "en",
    response_format: str = "markdown",
) -> str:
    """Get patient-friendly drug information from MedlinePlus.

    Looks up consumer-oriented drug information including uses, side effects,
    precautions, and interactions in plain language.

    Args:
        code: Drug code — RxCUI (e.g., "161354") or NDC (e.g., "0069-1540-66").
        code_system: "rxnorm" (default) or "ndc".
        display_name: Optional drug name to improve matching (e.g., "atorvastatin").
        language: "en" for English (default), "es" for Spanish.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Patient-friendly drug information with links to full MedlinePlus
        drug pages covering uses, dosage, side effects, and warnings.
    """
    try:
        if code_system.lower() not in ("rxnorm", "rxcui", "ndc"):
            return "Error: code_system must be 'rxnorm' or 'ndc' for drug lookups."

        data = await connect_get(
            code=code,
            code_system=code_system,
            display_name=display_name,
            language=language,
        )

        entries = parse_connect_entries(data)

        if not entries:
            return f"No drug information found for {code_system.upper()} code '{code}'. Try using an RxCUI from the normalize_drug tool."

        if response_format == "json":
            return _json_out({
                "code": code,
                "code_system": code_system,
                "entries": entries,
            })

        lines = [f"## Drug Information: {code_system.upper()} {code}", ""]
        for entry in entries:
            title = entry.get("title", "Untitled")
            url = entry.get("url", "")
            summary = entry.get("summary", "")

            lines.append(f"### {title}")
            if summary:
                if len(summary) > 500:
                    summary = summary[:497] + "..."
                lines.append(summary)
            if url:
                lines.append(f"[Read full article]({url})")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 4: get_lab_test_information

@mcp.tool(
    name="get_lab_test_information",
    annotations={
        "title": "Get Lab Test Information",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_lab_test_information(
    loinc_code: str,
    display_name: Optional[str] = None,
    language: str = "en",
    response_format: str = "markdown",
) -> str:
    """Get patient-friendly lab test information from MedlinePlus.

    Looks up consumer-oriented information about laboratory tests including
    what the test measures, why it's ordered, and what results mean.

    Args:
        loinc_code: LOINC code for the lab test (e.g., "2339-0" for glucose,
                    "2093-3" for cholesterol, "718-7" for hemoglobin).
        display_name: Optional test name to improve matching (e.g., "Glucose").
        language: "en" for English (default), "es" for Spanish.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Patient-friendly lab test information with links to full MedlinePlus
        articles about the test.
    """
    try:
        data = await connect_get(
            code=loinc_code,
            code_system="loinc",
            display_name=display_name,
            language=language,
        )

        entries = parse_connect_entries(data)

        if not entries:
            return f"No lab test information found for LOINC code '{loinc_code}'. Verify the code is correct."

        if response_format == "json":
            return _json_out({
                "loinc_code": loinc_code,
                "entries": entries,
            })

        lines = [f"## Lab Test Information: LOINC {loinc_code}", ""]
        for entry in entries:
            title = entry.get("title", "Untitled")
            url = entry.get("url", "")
            summary = entry.get("summary", "")

            lines.append(f"### {title}")
            if summary:
                if len(summary) > 500:
                    summary = summary[:497] + "..."
                lines.append(summary)
            if url:
                lines.append(f"[Read full article]({url})")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 5: get_procedure_information

@mcp.tool(
    name="get_procedure_information",
    annotations={
        "title": "Get Procedure Information",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_procedure_information(
    code: str,
    code_system: str = "cpt",
    display_name: Optional[str] = None,
    language: str = "en",
    response_format: str = "markdown",
) -> str:
    """Get patient-friendly procedure information from MedlinePlus.

    Looks up consumer-oriented information about medical procedures including
    what to expect, preparation, risks, and recovery.

    Args:
        code: Procedure code — CPT (e.g., "43239") or SNOMED CT code.
        code_system: "cpt" (default) or "snomed".
        display_name: Optional procedure name to improve matching
                      (e.g., "Upper GI endoscopy with biopsy").
        language: "en" for English (default), "es" for Spanish.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Patient-friendly procedure information with links to full MedlinePlus
        articles about the procedure.
    """
    try:
        if code_system.lower() not in ("cpt", "snomed", "snomedct"):
            return "Error: code_system must be 'cpt' or 'snomed' for procedure lookups."

        data = await connect_get(
            code=code,
            code_system=code_system,
            display_name=display_name,
            language=language,
        )

        entries = parse_connect_entries(data)

        if not entries:
            cs_name = "CPT" if code_system.lower() == "cpt" else "SNOMED CT"
            return f"No procedure information found for {cs_name} code '{code}'. The code may not have associated MedlinePlus content."

        if response_format == "json":
            return _json_out({
                "code": code,
                "code_system": code_system,
                "entries": entries,
            })

        cs_name = "CPT" if code_system.lower() == "cpt" else "SNOMED CT"
        lines = [f"## Procedure Information: {cs_name} {code}", ""]
        for entry in entries:
            title = entry.get("title", "Untitled")
            url = entry.get("url", "")
            summary = entry.get("summary", "")

            lines.append(f"### {title}")
            if summary:
                if len(summary) > 500:
                    summary = summary[:497] + "..."
                lines.append(summary)
            if url:
                lines.append(f"[Read full article]({url})")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Health check

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "medlineplus_mcp"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
