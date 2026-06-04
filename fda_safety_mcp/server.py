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
FDA Safety MCP Server

Wraps the openFDA API into an MCP server that lets LLM agents search drug
adverse events (FAERS), device adverse events (MAUDE), drug and device recalls,
510(k) premarket notifications, and device classifications.

Optional API key via OPENFDA_API_KEY env var for higher rate limits.
Designed for stateless deployment on Google Cloud Run.

Note: openFDA data is for research use. It should not be used to generate
public safety alerts or track recall lifecycles in production.
"""

import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

try:
    from fastmcp.server.dependencies import get_http_request
    HAS_HTTP_REQUEST = True
except ImportError:
    HAS_HTTP_REQUEST = False

from api_client import (
    build_search_query,
    escape_query_value,
    format_api_error,
    quote_value,
    search_510k,
    search_device_classification,
    search_device_enforcement,
    search_device_events,
    search_drug_enforcement,
    search_drug_events,
)

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "fda_safety_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


def _get_api_key() -> Optional[str]:
    """Extract openFDA API key from the HTTP request query string or env var."""
    if HAS_HTTP_REQUEST:
        try:
            request = get_http_request()
            if request and request.url:
                url_str = str(request.url)
                parsed = urlparse(url_str)
                qs = parse_qs(parsed.query)
                key = qs.get("openfda_key", [None])[0]
                if key:
                    return key
        except Exception:
            pass
    return None


def _json_out(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 1: search_adverse_events
# ---------------------------------------------------------------------------
@mcp.tool(
    name="search_adverse_events",
    annotations={
        "title": "Search Drug Adverse Events",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_adverse_events(
    drug_name: Optional[str] = None,
    ndc: Optional[str] = None,
    reaction: Optional[str] = None,
    serious: Optional[bool] = None,
    outcome: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
    count_field: Optional[str] = None,
    response_format: str = "markdown",
) -> str:
    """Search FDA Adverse Event Reporting System (FAERS) for drug adverse events.

    FAERS contains reports of adverse events and medication errors submitted
    to FDA. Reports do not prove causation — they indicate a temporal association.

    Args:
        drug_name: Brand or generic drug name (e.g., 'metformin', 'Lipitor').
        ndc: 11-digit National Drug Code.
        reaction: Adverse reaction term (e.g., 'nausea', 'hepatotoxicity', 'death').
        serious: If True, limit to serious reports (hospitalization, death, etc.).
        outcome: Patient outcome — 'death', 'hospitalization', 'disability',
            'life-threatening', 'congenital-anomaly', 'other'.
        date_from: Start date (YYYYMMDD format).
        date_to: End date (YYYYMMDD format).
        limit: Max results (1-100, default 10).
        skip: Number of results to skip for pagination.
        count_field: If set, returns aggregation counts instead of records.
            Examples: 'patient.reaction.reactionmeddrapt.exact' (top reactions),
            'patient.drug.openfda.brand_name.exact' (top drugs).
    """
    if not any([drug_name, ndc, reaction, date_from]):
        return "Error: Provide at least one search parameter (drug_name, ndc, reaction, or date_from)."

    try:
        search_parts = []

        if drug_name:
            # Simple term - no escaping needed for basic drug names
            search_parts.append(
                f"(patient.drug.openfda.brand_name:{drug_name} OR "
                f"patient.drug.openfda.generic_name:{drug_name})"
            )
        if ndc:
            search_parts.append(f"patient.drug.openfda.ndc:{quote_value(ndc)}")
        if reaction:
            escaped = escape_query_value(reaction)
            search_parts.append(f"patient.reaction.reactionmeddrapt:{quote_value(escaped)}")
        if serious is True:
            search_parts.append("serious:1")
        if outcome:
            outcome_map = {
                "death": "seriousnessdeath:1",
                "hospitalization": "seriousnesshospitalization:1",
                "disability": "seriousnessdisabling:1",
                "life-threatening": "seriousnesslifethreatening:1",
                "congenital-anomaly": "seriousnesscongenitalanomali:1",
                "other": "seriousnessother:1",
            }
            if outcome.lower() in outcome_map:
                search_parts.append(outcome_map[outcome.lower()])
        if date_from and date_to:
            search_parts.append(f"receivedate:[{date_from} TO {date_to}]")
        elif date_from:
            search_parts.append(f"receivedate:[{date_from} TO 99991231]")
        elif date_to:
            search_parts.append(f"receivedate:[19000101 TO {date_to}]")

        search = build_search_query(search_parts)
        data = await search_drug_events(
            api_key=_get_api_key(),
            search=search if search else None,
            count=count_field,
            limit=limit,
            skip=skip,
        )

        # Handle count response
        if count_field:
            results = data.get("results", [])
            if response_format == "json":
                return _json_out(data)

            lines = [f"# Adverse Event Counts by {count_field}", ""]
            for item in results[:20]:
                term = item.get("term", "N/A")
                count = item.get("count", 0)
                lines.append(f"- **{term}**: {count:,} reports")
            if len(results) > 20:
                lines.append(f"\n*Showing top 20 of {len(results)} results*")
            return "\n".join(lines)

        # Handle regular search response
        results = data.get("results", [])
        meta = data.get("meta", {})
        total = meta.get("results", {}).get("total", len(results))

        if not results:
            return "No adverse event reports found matching your criteria."

        if response_format == "json":
            return _json_out(data)

        lines = ["# Drug Adverse Event Reports (FAERS)", ""]
        lines.append(f"**{total:,} total reports** (showing {len(results)})")
        lines.append("")

        for report in results:
            safety_id = report.get("safetyreportid", "N/A")
            receive_date = report.get("receivedate", "N/A")
            serious_flag = "Serious" if report.get("serious") == "1" else "Non-serious"
            country = report.get("occurcountry", "N/A")

            patient = report.get("patient", {})
            drugs = patient.get("drug", [])
            reactions = patient.get("reaction", [])

            drug_names = []
            for d in drugs[:3]:
                name = d.get("medicinalproduct", "")
                role = d.get("drugcharacterization", "")
                role_label = {"1": "suspect", "2": "concomitant", "3": "interacting"}.get(role, "")
                if name:
                    drug_names.append(f"{name} ({role_label})" if role_label else name)

            reaction_terms = [r.get("reactionmeddrapt", "") for r in reactions[:5] if r.get("reactionmeddrapt")]

            lines.append(f"### Report {safety_id}")
            lines.append(f"**Date:** {receive_date} | **{serious_flag}** | **Country:** {country}")
            if drug_names:
                lines.append(f"**Drugs:** {', '.join(drug_names)}")
            if reaction_terms:
                lines.append(f"**Reactions:** {', '.join(reaction_terms)}")
            lines.append("")

        if skip + len(results) < total:
            lines.append(f"*More results available. Use skip={skip + len(results)} to continue.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 2: search_device_events
# ---------------------------------------------------------------------------
@mcp.tool(
    name="search_device_events",
    annotations={
        "title": "Search Device Adverse Events",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def tool_search_device_events(
    device_name: Optional[str] = None,
    product_code: Optional[str] = None,
    event_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
    count_field: Optional[str] = None,
    response_format: str = "markdown",
) -> str:
    """Search FDA MAUDE database for medical device adverse event reports.

    MAUDE (Manufacturer and User Facility Device Experience) contains reports
    of adverse events involving medical devices.

    Args:
        device_name: Device name or brand (e.g., 'pacemaker', 'insulin pump').
        product_code: FDA 3-letter product code (e.g., 'DXY' for pacemakers).
        event_type: Type of event — 'malfunction', 'injury', 'death', 'other'.
        date_from: Start date (YYYYMMDD format).
        date_to: End date (YYYYMMDD format).
        limit: Max results (1-100, default 10).
        skip: Number of results to skip for pagination.
        count_field: If set, returns aggregation counts. Examples:
            'device.generic_name.exact', 'event_type.exact'.
    """
    if not any([device_name, product_code, event_type, date_from]):
        return "Error: Provide at least one search parameter."

    try:
        search_parts = []

        if device_name:
            escaped = escape_query_value(device_name)
            search_parts.append(f"device.generic_name:{quote_value(escaped)}")
        if product_code:
            search_parts.append(f"device.device_report_product_code:{quote_value(product_code.upper())}")
        if event_type:
            event_map = {
                "malfunction": "Malfunction",
                "injury": "Injury",
                "death": "Death",
                "other": "Other",
            }
            if event_type.lower() in event_map:
                search_parts.append(f"event_type:{quote_value(event_map[event_type.lower()])}")
        if date_from and date_to:
            search_parts.append(f"date_received:[{date_from} TO {date_to}]")
        elif date_from:
            search_parts.append(f"date_received:[{date_from} TO 99991231]")
        elif date_to:
            search_parts.append(f"date_received:[19000101 TO {date_to}]")

        search = build_search_query(search_parts)
        data = await search_device_events(
            api_key=_get_api_key(),
            search=search if search else None,
            count=count_field,
            limit=limit,
            skip=skip,
        )

        if count_field:
            results = data.get("results", [])
            if response_format == "json":
                return _json_out(data)

            lines = [f"# Device Event Counts by {count_field}", ""]
            for item in results[:20]:
                term = item.get("term", "N/A")
                count = item.get("count", 0)
                lines.append(f"- **{term}**: {count:,} reports")
            return "\n".join(lines)

        results = data.get("results", [])
        meta = data.get("meta", {})
        total = meta.get("results", {}).get("total", len(results))

        if not results:
            return "No device adverse event reports found matching your criteria."

        if response_format == "json":
            return _json_out(data)

        lines = ["# Device Adverse Event Reports (MAUDE)", ""]
        lines.append(f"**{total:,} total reports** (showing {len(results)})")
        lines.append("")

        for report in results:
            report_num = report.get("mdr_report_key", report.get("report_number", "N/A"))
            event_date = report.get("date_received", "N/A")
            event_type_val = report.get("event_type", "N/A")

            devices = report.get("device", [])
            device_info = devices[0] if devices else {}
            device_name_val = device_info.get("generic_name", device_info.get("brand_name", "N/A"))
            manufacturer = device_info.get("manufacturer_d_name", "N/A")

            description = ""
            text_entries = report.get("mdr_text", [])
            for entry in text_entries:
                if entry.get("text_type_code") == "Description of Event or Problem":
                    description = entry.get("text", "")[:300]
                    break

            lines.append(f"### Report {report_num}")
            lines.append(f"**Date:** {event_date} | **Event Type:** {event_type_val}")
            lines.append(f"**Device:** {device_name_val}")
            lines.append(f"**Manufacturer:** {manufacturer}")
            if description:
                lines.append(f"**Description:** {description}...")
            lines.append("")

        if skip + len(results) < total:
            lines.append(f"*More results available. Use skip={skip + len(results)} to continue.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 3: search_drug_recalls
# ---------------------------------------------------------------------------
@mcp.tool(
    name="search_drug_recalls",
    annotations={
        "title": "Search Drug Recalls",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_drug_recalls(
    drug_name: Optional[str] = None,
    reason: Optional[str] = None,
    classification: Optional[str] = None,
    status: Optional[str] = None,
    firm: Optional[str] = None,
    state: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
    response_format: str = "markdown",
) -> str:
    """Search FDA drug recall and enforcement actions.

    Returns recall actions including voluntary recalls, market withdrawals,
    and FDA-mandated recalls. Classification indicates severity:
    - Class I: Serious health consequences or death
    - Class II: Temporary or reversible health consequences
    - Class III: Not likely to cause adverse health consequences

    Args:
        drug_name: Product name (e.g., 'metformin', 'aspirin').
        reason: Reason for recall (e.g., 'contamination', 'mislabeling').
        classification: 'I', 'II', or 'III' (severity).
        status: 'Ongoing', 'Completed', or 'Terminated'.
        firm: Recalling firm name.
        state: Two-letter state code of recalling firm.
        date_from: Start date (YYYYMMDD format).
        date_to: End date (YYYYMMDD format).
        limit: Max results (1-100, default 10).
        skip: Number of results to skip for pagination.
    """
    try:
        search_parts = []

        if drug_name:
            escaped = escape_query_value(drug_name)
            search_parts.append(f"product_description:{quote_value(escaped)}")
        if reason:
            escaped = escape_query_value(reason)
            search_parts.append(f"reason_for_recall:{quote_value(escaped)}")
        if classification:
            class_val = f"Class {classification.upper()}"
            search_parts.append(f"classification:{quote_value(class_val)}")
        if status:
            search_parts.append(f"status:{quote_value(status)}")
        if firm:
            escaped = escape_query_value(firm)
            search_parts.append(f"recalling_firm:{quote_value(escaped)}")
        if state:
            search_parts.append(f"state:{quote_value(state.upper())}")
        if date_from and date_to:
            search_parts.append(f"report_date:[{date_from} TO {date_to}]")
        elif date_from:
            search_parts.append(f"report_date:[{date_from} TO 99991231]")
        elif date_to:
            search_parts.append(f"report_date:[19000101 TO {date_to}]")

        search = build_search_query(search_parts)
        data = await search_drug_enforcement(
            api_key=_get_api_key(),
            search=search if search else None,
            limit=limit,
            skip=skip,
        )

        results = data.get("results", [])
        meta = data.get("meta", {})
        total = meta.get("results", {}).get("total", len(results))

        if not results:
            return "No drug recall actions found matching your criteria."

        if response_format == "json":
            return _json_out(data)

        lines = ["# Drug Recall Actions", ""]
        lines.append(f"**{total:,} total recalls** (showing {len(results)})")
        lines.append("")

        for recall in results:
            recall_num = recall.get("recall_number", "N/A")
            report_date = recall.get("report_date", "N/A")
            classification_val = recall.get("classification", "N/A")
            status_val = recall.get("status", "N/A")
            product = recall.get("product_description", "N/A")[:200]
            reason_val = recall.get("reason_for_recall", "N/A")[:200]
            firm_val = recall.get("recalling_firm", "N/A")
            distribution = recall.get("distribution_pattern", "N/A")

            lines.append(f"### {recall_num}")
            lines.append(f"**Date:** {report_date} | **{classification_val}** | **Status:** {status_val}")
            lines.append(f"**Firm:** {firm_val}")
            lines.append(f"**Product:** {product}")
            lines.append(f"**Reason:** {reason_val}")
            lines.append(f"**Distribution:** {distribution}")
            lines.append("")

        if skip + len(results) < total:
            lines.append(f"*More results available. Use skip={skip + len(results)} to continue.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 4: search_device_recalls
# ---------------------------------------------------------------------------
@mcp.tool(
    name="search_device_recalls",
    annotations={
        "title": "Search Device Recalls",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def tool_search_device_recalls(
    device_name: Optional[str] = None,
    reason: Optional[str] = None,
    classification: Optional[str] = None,
    status: Optional[str] = None,
    firm: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
    response_format: str = "markdown",
) -> str:
    """Search FDA medical device recall and enforcement actions.

    Classification indicates severity:
    - Class I: Serious health consequences or death
    - Class II: Temporary or reversible health consequences
    - Class III: Not likely to cause adverse health consequences

    Args:
        device_name: Device or product name.
        reason: Reason for recall.
        classification: 'I', 'II', or 'III' (severity).
        status: 'Ongoing', 'Completed', or 'Terminated'.
        firm: Recalling firm name.
        date_from: Start date (YYYYMMDD format).
        date_to: End date (YYYYMMDD format).
        limit: Max results (1-100, default 10).
        skip: Number of results to skip for pagination.
    """
    try:
        search_parts = []

        if device_name:
            escaped = escape_query_value(device_name)
            search_parts.append(f"product_description:{quote_value(escaped)}")
        if reason:
            escaped = escape_query_value(reason)
            search_parts.append(f"reason_for_recall:{quote_value(escaped)}")
        if classification:
            class_val = f"Class {classification.upper()}"
            search_parts.append(f"classification:{quote_value(class_val)}")
        if status:
            search_parts.append(f"status:{quote_value(status)}")
        if firm:
            escaped = escape_query_value(firm)
            search_parts.append(f"recalling_firm:{quote_value(escaped)}")
        if date_from and date_to:
            search_parts.append(f"report_date:[{date_from} TO {date_to}]")
        elif date_from:
            search_parts.append(f"report_date:[{date_from} TO 99991231]")
        elif date_to:
            search_parts.append(f"report_date:[19000101 TO {date_to}]")

        search = build_search_query(search_parts)
        data = await search_device_enforcement(
            api_key=_get_api_key(),
            search=search if search else None,
            limit=limit,
            skip=skip,
        )

        results = data.get("results", [])
        meta = data.get("meta", {})
        total = meta.get("results", {}).get("total", len(results))

        if not results:
            return "No device recall actions found matching your criteria."

        if response_format == "json":
            return _json_out(data)

        lines = ["# Device Recall Actions", ""]
        lines.append(f"**{total:,} total recalls** (showing {len(results)})")
        lines.append("")

        for recall in results:
            recall_num = recall.get("recall_number", "N/A")
            report_date = recall.get("report_date", "N/A")
            classification_val = recall.get("classification", "N/A")
            status_val = recall.get("status", "N/A")
            product = recall.get("product_description", "N/A")[:200]
            reason_val = recall.get("reason_for_recall", "N/A")[:200]
            firm_val = recall.get("recalling_firm", "N/A")

            lines.append(f"### {recall_num}")
            lines.append(f"**Date:** {report_date} | **{classification_val}** | **Status:** {status_val}")
            lines.append(f"**Firm:** {firm_val}")
            lines.append(f"**Product:** {product}")
            lines.append(f"**Reason:** {reason_val}")
            lines.append("")

        if skip + len(results) < total:
            lines.append(f"*More results available. Use skip={skip + len(results)} to continue.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 5: get_510k
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_510k",
    annotations={
        "title": "Get 510(k) Premarket Notification",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_510k(
    k_number: Optional[str] = None,
    device_name: Optional[str] = None,
    applicant: Optional[str] = None,
    product_code: Optional[str] = None,
    decision: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
    response_format: str = "markdown",
) -> str:
    """Search FDA 510(k) premarket notifications for medical devices.

    510(k) clearance demonstrates that a device is substantially equivalent
    to a legally marketed predicate device. Most Class II devices require
    510(k) clearance before marketing.

    Args:
        k_number: 510(k) number (e.g., 'K212345').
        device_name: Device name.
        applicant: Applicant/company name.
        product_code: FDA 3-letter product code.
        decision: Decision — 'SESE' (substantially equivalent),
            'SESP' (substantially equivalent with post-market surveillance),
            'SEKI' (substantially equivalent per 513(i)), 'SEKD' (denied).
        date_from: Decision date start (YYYYMMDD).
        date_to: Decision date end (YYYYMMDD).
        limit: Max results (1-100, default 10).
        skip: Number of results to skip for pagination.
    """
    try:
        search_parts = []

        if k_number:
            search_parts.append(f"k_number:{quote_value(k_number.upper())}")
        if device_name:
            escaped = escape_query_value(device_name)
            search_parts.append(f"device_name:{quote_value(escaped)}")
        if applicant:
            escaped = escape_query_value(applicant)
            search_parts.append(f"applicant:{quote_value(escaped)}")
        if product_code:
            search_parts.append(f"product_code:{quote_value(product_code.upper())}")
        if decision:
            search_parts.append(f"decision_code:{quote_value(decision.upper())}")
        if date_from and date_to:
            search_parts.append(f"decision_date:[{date_from} TO {date_to}]")
        elif date_from:
            search_parts.append(f"decision_date:[{date_from} TO 99991231]")
        elif date_to:
            search_parts.append(f"decision_date:[19000101 TO {date_to}]")

        search = build_search_query(search_parts)
        data = await search_510k(
            api_key=_get_api_key(),
            search=search if search else None,
            limit=limit,
            skip=skip,
        )

        results = data.get("results", [])
        meta = data.get("meta", {})
        total = meta.get("results", {}).get("total", len(results))

        if not results:
            return "No 510(k) records found matching your criteria."

        if response_format == "json":
            return _json_out(data)

        lines = ["# 510(k) Premarket Notifications", ""]
        lines.append(f"**{total:,} total records** (showing {len(results)})")
        lines.append("")

        for record in results:
            k_num = record.get("k_number", "N/A")
            device = record.get("device_name", "N/A")
            applicant_name = record.get("applicant", "N/A")
            decision_val = record.get("decision_code", "N/A")
            decision_date = record.get("decision_date", "N/A")
            product_code_val = record.get("product_code", "N/A")
            statement = record.get("statement_or_summary", "N/A")

            decision_label = {
                "SESE": "Substantially Equivalent",
                "SESP": "SE with Post-Market Surveillance",
                "SEKI": "SE per 513(i)",
                "SEKD": "Not Substantially Equivalent",
            }.get(decision_val, decision_val)

            lines.append(f"### {k_num}: {device}")
            lines.append(f"**Applicant:** {applicant_name}")
            lines.append(f"**Decision:** {decision_label} | **Date:** {decision_date}")
            lines.append(f"**Product Code:** {product_code_val}")
            if statement and statement != "N/A":
                lines.append(f"**Summary:** {statement[:200]}...")
            lines.append("")

        if skip + len(results) < total:
            lines.append(f"*More results available. Use skip={skip + len(results)} to continue.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 6: get_device_classification
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_device_classification",
    annotations={
        "title": "Get Device Classification",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_device_classification(
    device_name: Optional[str] = None,
    product_code: Optional[str] = None,
    device_class: Optional[str] = None,
    regulation_number: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
    response_format: str = "markdown",
) -> str:
    """Search FDA device classification database.

    Returns regulatory classification for medical devices:
    - Class I: Low risk, general controls (e.g., bandages)
    - Class II: Moderate risk, special controls (e.g., powered wheelchairs)
    - Class III: High risk, premarket approval required (e.g., pacemakers)

    Args:
        device_name: Device name or type (e.g., 'stent', 'glucose meter').
        product_code: FDA 3-letter product code (e.g., 'DXY').
        device_class: '1', '2', or '3'.
        regulation_number: CFR regulation number (e.g., '870.1025').
        limit: Max results (1-100, default 10).
        skip: Number of results to skip for pagination.
    """
    if not any([device_name, product_code, device_class, regulation_number]):
        return "Error: Provide at least one search parameter."

    try:
        search_parts = []

        if device_name:
            escaped = escape_query_value(device_name)
            search_parts.append(f"device_name:{quote_value(escaped)}")
        if product_code:
            search_parts.append(f"product_code:{quote_value(product_code.upper())}")
        if device_class:
            search_parts.append(f"device_class:{quote_value(device_class)}")
        if regulation_number:
            search_parts.append(f"regulation_number:{quote_value(regulation_number)}")

        search = build_search_query(search_parts)
        data = await search_device_classification(
            api_key=_get_api_key(),
            search=search if search else None,
            limit=limit,
            skip=skip,
        )

        results = data.get("results", [])
        meta = data.get("meta", {})
        total = meta.get("results", {}).get("total", len(results))

        if not results:
            return "No device classifications found matching your criteria."

        if response_format == "json":
            return _json_out(data)

        lines = ["# FDA Device Classifications", ""]
        lines.append(f"**{total:,} total records** (showing {len(results)})")
        lines.append("")

        for record in results:
            device = record.get("device_name", "N/A")
            product_code_val = record.get("product_code", "N/A")
            device_class_val = record.get("device_class", "N/A")
            reg_num = record.get("regulation_number", "N/A")
            definition = record.get("definition", "")
            review_panel = record.get("review_panel", "N/A")
            submission_type = record.get("submission_type_id", "N/A")

            class_label = {
                "1": "Class I (Low Risk)",
                "2": "Class II (Moderate Risk)",
                "3": "Class III (High Risk)",
            }.get(str(device_class_val), f"Class {device_class_val}")

            lines.append(f"### {device}")
            lines.append(f"**Product Code:** {product_code_val} | **{class_label}**")
            lines.append(f"**Regulation:** {reg_num} | **Review Panel:** {review_panel}")
            lines.append(f"**Submission Type:** {submission_type}")
            if definition:
                lines.append(f"**Definition:** {definition[:300]}...")
            lines.append("")

        if skip + len(results) < total:
            lines.append(f"*More results available. Use skip={skip + len(results)} to continue.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "fda_safety_mcp"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
