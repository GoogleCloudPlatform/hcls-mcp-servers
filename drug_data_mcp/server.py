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
Drug Data MCP Server

Wraps CMS drug pricing and utilization datasets — NADAC, Medicare Part D
spending, Part D prescriber data, State Drug Utilization (Medicaid), and the
Medicaid Drug Rebate Program — into a single MCP server for LLM agents.

All datasets are hosted on Data.Medicaid.gov and data.cms.gov via the
new DKAN and CMS APIs.

Designed for stateless deployment on Google Cloud Run.
"""

import json
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api_client import (
    cms_query,
    format_api_error,
    nadac_query,
    rebate_query,
    sdud_query,
    CMS_HOST,
    MEDICAID_HOST,
    NADAC_2024,
    NADAC_2025,
    NADAC_2026,
    NADAC_DEFAULT,
    SDUD_2022,
    SDUD_2023,
    PART_D_SPENDING_ID,
    PART_D_PRESCRIBER_ID,
)

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "drug_data_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


def _json_out(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 1: get_nadac_price
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_nadac_price",
    annotations={
        "title": "Get NADAC Drug Price",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_nadac_price(
    drug_name: Optional[str] = None,
    ndc: Optional[str] = None,
    limit: int = 20,
    response_format: str = "markdown",
) -> str:
    """Get the current National Average Drug Acquisition Cost (NADAC) for a drug.

    NADAC represents the average price pharmacies pay to acquire drugs.
    Updated weekly by CMS. Search by drug name or NDC code.

    Args:
        drug_name: Drug name to search (case-insensitive, partial match).
            Examples: 'metformin', 'atorvastatin', 'Lipitor'.
        ndc: 11-digit National Drug Code. Example: '00093069211'.
        limit: Max results (default 20, max 1000).
    """
    if not drug_name and not ndc:
        return "Error: Provide either drug_name or ndc to search NADAC prices."

    try:
        conditions = []
        if ndc:
            conditions.append({"property": "ndc", "value": ndc})
        if drug_name:
            conditions.append({"property": "ndc_description", "value": f"%{drug_name.upper()}%", "operator": "LIKE"})

        params: Dict[str, Any] = {
            "limit": min(limit, 1000),
            "sorts": [{"property": "as_of_date", "order": "desc"}],
            "conditions": conditions
        }

        data = await nadac_query(params)

        if not data:
            return f"No NADAC pricing data found for {'NDC ' + ndc if ndc else drug_name}."

        if response_format == "json":
            return _json_out(data)

        lines = ["# NADAC Drug Pricing", ""]
        for record in data:
            name = record.get("ndc_description", "N/A")
            ndc_code = record.get("ndc", "N/A")
            price = record.get("nadac_per_unit", "N/A")
            unit = record.get("pricing_unit", "N/A")
            date = record.get("as_of_date", "N/A")
            otc = "OTC" if record.get("otc") == "Y" else "Rx"
            classification = record.get("classification_for_rate_setting", "N/A")

            lines.append(f"### {name}")
            lines.append(f"**NDC:** {ndc_code} | **NADAC:** ${price}/{unit} | **Date:** {date}")
            lines.append(f"**Type:** {otc} | **Classification:** {classification}")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 2: search_nadac
# ---------------------------------------------------------------------------
@mcp.tool(
    name="search_nadac",
    annotations={
        "title": "Search NADAC Pricing",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_nadac(
    drug_name: Optional[str] = None,
    classification: Optional[str] = None,
    otc: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
    response_format: str = "markdown",
) -> str:
    """Search NADAC pricing data with advanced filters.

    Filter by drug name, classification (generic/brand), OTC status,
    date range, and price range. Results sorted by most recent date.

    Args:
        drug_name: Drug name (case-insensitive, partial match).
        classification: 'G' for generic, 'B' for brand.
        otc: True for over-the-counter, False for prescription.
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        min_price: Minimum NADAC per unit.
        max_price: Maximum NADAC per unit.
        limit: Max results (default 50, max 1000).
        offset: Starting record for pagination.
    """
    try:
        conditions = []
        if drug_name:
            conditions.append({"property": "ndc_description", "value": f"%{drug_name.upper()}%", "operator": "LIKE"})
        if classification:
            conditions.append({"property": "classification_for_rate_setting", "value": classification.upper()})
        if otc is not None:
            conditions.append({"property": "otc", "value": "Y" if otc else "N"})
        if date_from:
            conditions.append({"property": "effective_date", "value": date_from, "operator": ">="})
        if date_to:
            conditions.append({"property": "effective_date", "value": date_to, "operator": "<="})
        if min_price is not None:
            conditions.append({"property": "nadac_per_unit", "value": min_price, "operator": ">="})
        if max_price is not None:
            conditions.append({"property": "nadac_per_unit", "value": max_price, "operator": "<="})

        params: Dict[str, Any] = {
            "limit": min(limit, 1000),
            "offset": offset,
            "sorts": [{"property": "as_of_date", "order": "desc"}],
            "conditions": conditions
        }

        data = await nadac_query(params)

        if not data:
            return "No NADAC records match your filters."

        if response_format == "json":
            return _json_out(data)

        lines = [f"# NADAC Search Results ({len(data)} records)", ""]
        for record in data:
            name = record.get("ndc_description", "N/A")
            ndc_code = record.get("ndc", "N/A")
            price = record.get("nadac_per_unit", "N/A")
            unit = record.get("pricing_unit", "N/A")
            date = record.get("as_of_date", "N/A")
            lines.append(f"- **{name}** (NDC: {ndc_code}) — ${price}/{unit} — {date}")

        if len(data) == limit:
            lines.append(f"\n*More results may be available. Use offset={offset + limit} to continue.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 3: get_price_history
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_price_history",
    annotations={
        "title": "Get Drug Price History",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_price_history(
    ndc: Optional[str] = None,
    drug_name: Optional[str] = None,
    limit: int = 100,
    response_format: str = "markdown",
) -> str:
    """Get NADAC price history over time for a specific drug.

    Shows price trends by returning historical pricing records sorted
    chronologically. Search by NDC (preferred for exact match) or drug name.
    Queries both 2025 and 2024 datasets for longer history.

    Args:
        ndc: 11-digit NDC code (preferred for exact match).
        drug_name: Drug name (case-insensitive, partial match).
        limit: Max records per dataset year (default 100).
    """
    if not ndc and not drug_name:
        return "Error: Provide either ndc or drug_name to get price history."

    try:
        conditions = []
        if ndc:
            conditions.append({"property": "ndc", "value": ndc})
        if drug_name:
            conditions.append({"property": "ndc_description", "value": f"%{drug_name.upper()}%", "operator": "LIKE"})

        params: Dict[str, Any] = {
            "limit": min(limit, 1000),
            "sorts": [{"property": "as_of_date", "order": "asc"}],
            "conditions": conditions
        }

        # Query both years for longer history
        import asyncio as aio
        results_2026, results_2025 = await aio.gather(
            nadac_query(params, dataset_id=NADAC_2026),
            nadac_query(params, dataset_id=NADAC_2025),
            return_exceptions=True,
        )

        all_records = []
        if isinstance(results_2025, list):
            all_records.extend(results_2025)
        if isinstance(results_2026, list):
            all_records.extend(results_2026)

        if not all_records:
            return f"No price history found for {'NDC ' + ndc if ndc else drug_name}."

        if response_format == "json":
            return _json_out(all_records)

        # Group by drug name for display
        drug_groups: Dict[str, List[Dict]] = {}
        for r in all_records:
            name = r.get("ndc_description", "Unknown")
            drug_groups.setdefault(name, []).append(r)

        lines = ["# Drug Price History", ""]

        for name, records in drug_groups.items():
            lines.append(f"## {name}")
            prices = []
            for r in records:
                date = r.get("as_of_date", "N/A")
                price = r.get("nadac_per_unit", "N/A")
                unit = r.get("pricing_unit", "EA")
                prices.append((date, price, unit))
                lines.append(f"- {date}: ${price}/{unit}")

            if len(prices) >= 2:
                try:
                    first_price = float(prices[0][1])
                    last_price = float(prices[-1][1])
                    if first_price > 0:
                        pct_change = ((last_price - first_price) / first_price) * 100
                        direction = "increased" if pct_change > 0 else "decreased"
                        lines.append(f"\n**Trend:** Price {direction} {abs(pct_change):.1f}% from {prices[0][0]} to {prices[-1][0]}")
                except (ValueError, ZeroDivisionError):
                    pass
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 4: compare_drug_prices
# ---------------------------------------------------------------------------
@mcp.tool(
    name="compare_drug_prices",
    annotations={
        "title": "Compare Drug Prices",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def compare_drug_prices(
    drug_names: List[str],
    response_format: str = "markdown",
) -> str:
    """Compare current NADAC pricing for multiple drugs side by side.

    Useful for comparing generic vs brand pricing or therapeutic alternatives.
    Provide 2-10 drug names; returns the most recent price for each.

    Args:
        drug_names: List of drug names to compare (2-10).
            Examples: ['metformin', 'glipizide', 'pioglitazone']
    """
    if len(drug_names) < 2 or len(drug_names) > 10:
        return "Error: Provide between 2 and 10 drug names for comparison."

    try:
        import asyncio as aio

        async def _get_latest(name: str) -> Dict[str, Any]:
            params = {
                "limit": 5,
                "sorts": [{"property": "as_of_date", "order": "desc"}],
                "conditions": [{"property": "ndc_description", "value": f"%{name.upper()}%", "operator": "LIKE"}]
            }
            records = await nadac_query(params)
            return {"drug": name, "records": records}

        results = await aio.gather(*[_get_latest(n) for n in drug_names])

        if response_format == "json":
            return _json_out(results)

        lines = ["# Drug Price Comparison", ""]

        # Build comparison table
        lines.append("| Drug | NDC | NADAC/Unit | Unit | Classification | Date |")
        lines.append("|------|-----|-----------|------|---------------|------|")

        for result in results:
            drug = result["drug"]
            records = result["records"]
            if records:
                for r in records[:3]:
                    name = r.get("ndc_description", drug)
                    ndc = r.get("ndc", "N/A")
                    price = r.get("nadac_per_unit", "N/A")
                    unit = r.get("pricing_unit", "N/A")
                    cls = r.get("classification_for_rate_setting", "N/A")
                    date = r.get("as_of_date", "N/A")
                    lines.append(f"| {name} | {ndc} | ${price} | {unit} | {cls} | {date} |")
            else:
                lines.append(f"| {drug} | — | Not found | — | — | — |")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 5: get_part_d_spending
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_part_d_spending",
    annotations={
        "title": "Get Medicare Part D Drug Spending",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_part_d_spending(
    drug_name: Optional[str] = None,
    brand_name: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 20,
    response_format: str = "markdown",
) -> str:
    """Get Medicare Part D spending data for a drug.

    Shows total Medicare spending, number of beneficiaries, average cost per
    beneficiary, and utilization metrics. Data is aggregated nationally.

    Args:
        drug_name: Generic drug name (case-insensitive, partial match).
        brand_name: Brand/trade name (case-insensitive, partial match).
        year: Specific year to query.
        limit: Max results (default 20).
    """
    if not drug_name and not brand_name:
        return "Error: Provide either drug_name or brand_name."

    try:
        filters = {}
        if brand_name:
            filters["Brnd_Name"] = {"like": f"%{brand_name}%"}
        if year:
            filters["Tot_Year"] = str(year)

        params: Dict[str, Any] = {
            "size": min(limit, 1000),
            "sort": {"Tot_Spndng_2023": "desc"}
        }
        
        if drug_name:
            params["keyword"] = drug_name
            
        if filters:
            params["filter"] = filters

        data = await cms_query(PART_D_SPENDING_ID, params, cache_ttl="7d")

        if not data:
            return f"No Part D spending data found for {'brand: ' + brand_name if brand_name else drug_name}."

        if response_format == "json":
            return _json_out(data)

        lines = ["# Medicare Part D Drug Spending", ""]

        for record in data:
            brnd = record.get("brnd_name", record.get("Brnd_Name", "N/A"))
            gnrc = record.get("gnrc_name", record.get("Gnrc_Name", "N/A"))
            yr = record.get("tot_year", record.get("Tot_Year", "N/A"))
            total_spending = record.get("tot_spndng", record.get("Tot_Spndng", "N/A"))
            total_claims = record.get("tot_clms", record.get("Tot_Clms", "N/A"))
            total_benes = record.get("tot_benes", record.get("Tot_Benes", "N/A"))
            avg_spend_per_bene = record.get("avg_spnd_per_bene", record.get("Avg_Spnd_Per_Bene", "N/A"))
            avg_cost_per_claim = record.get("avg_spnd_per_clm", record.get("Avg_Spnd_Per_Clm", "N/A"))

            lines.append(f"### {brnd} ({gnrc})")
            lines.append(f"**Year:** {yr}")
            lines.append(f"**Total Spending:** ${total_spending}")
            lines.append(f"**Total Claims:** {total_claims} | **Beneficiaries:** {total_benes}")
            lines.append(f"**Avg Cost/Beneficiary:** ${avg_spend_per_bene} | **Avg Cost/Claim:** ${avg_cost_per_claim}")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 6: get_prescriber_data
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_prescriber_data",
    annotations={
        "title": "Get Part D Prescriber Data",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_prescriber_data(
    npi: Optional[str] = None,
    drug_name: Optional[str] = None,
    state: Optional[str] = None,
    specialty: Optional[str] = None,
    limit: int = 20,
    response_format: str = "markdown",
) -> str:
    """Get Medicare Part D prescriber-level data.

    Find what drugs a provider prescribes (by NPI) or which providers
    prescribe a specific drug. Includes prescription counts, total cost,
    and beneficiary counts.

    Args:
        npi: 10-digit National Provider Identifier.
        drug_name: Generic drug name (case-insensitive, partial match).
        state: Two-letter state code (e.g., 'CA', 'NY').
        specialty: Provider specialty (partial match, e.g., 'Cardiology').
        limit: Max results (default 20).
    """
    if not npi and not drug_name:
        return "Error: Provide either npi or drug_name."

    try:
        filters = {}
        if npi:
            filters["Prscrbr_NPI"] = str(npi)
        if state:
            filters["Prscrbr_State_Abrvtn"] = state.upper()
        if specialty:
            filters["Prscrbr_Type"] = {"like": f"%{specialty}%"}
        
        params: Dict[str, Any] = {
            "size": min(limit, 1000),
            "sort": {"Tot_Clms": "desc"}
        }
        
        if drug_name:
            params["keyword"] = drug_name
            
        if filters:
            params["filter"] = filters

        data = await cms_query(PART_D_PRESCRIBER_ID, params, cache_ttl="7d")

        if not data:
            query_desc = f"NPI {npi}" if npi else drug_name
            return f"No prescriber data found for {query_desc}."

        if response_format == "json":
            return _json_out(data)

        lines = ["# Medicare Part D Prescriber Data", ""]

        if npi:
            lines.append(f"**Provider NPI:** {npi}")
            if data:
                first = data[0]
                last_name = first.get('prscrbr_last_org_name', first.get('Prscrbr_Last_Org_Name', ''))
                first_name = first.get('prscrbr_first_name', first.get('Prscrbr_First_Name', ''))
                lines.append(f"**Name:** {last_name} {first_name}")
                lines.append(f"**Specialty:** {first.get('prscrbr_type', first.get('Prscrbr_Type', 'N/A'))}")
                lines.append(f"**Location:** {first.get('prscrbr_city', first.get('Prscrbr_City', ''))}, {first.get('prscrbr_state_abrvtn', first.get('Prscrbr_State_Abrvtn', ''))}")
            lines.append("")

        for record in data:
            last_name = record.get('prscrbr_last_org_name', record.get('Prscrbr_Last_Org_Name', ''))
            first_name = record.get('prscrbr_first_name', record.get('Prscrbr_First_Name', ''))
            provider_name = f"{last_name} {first_name}".strip()
            gnrc = record.get("gnrc_name", record.get("Gnrc_Name", "N/A"))
            brnd = record.get("brnd_name", record.get("Brnd_Name", "N/A"))
            claims = record.get("tot_clms", record.get("Tot_Clms", "N/A"))
            cost = record.get("tot_drug_cst", record.get("Tot_Drug_Cst", "N/A"))
            benes = record.get("tot_benes", record.get("Tot_Benes", "N/A"))
            prov_state = record.get("prscrbr_state_abrvtn", record.get("Prscrbr_State_Abrvtn", ""))

            if npi:
                lines.append(f"- **{brnd}** ({gnrc}) — {claims} claims, ${cost} total, {benes} beneficiaries")
            else:
                lines.append(f"- **{provider_name}** ({prov_state}) — {gnrc}: {claims} claims, ${cost} total")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 7: get_state_utilization
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_state_utilization",
    annotations={
        "title": "Get State Drug Utilization",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_state_utilization(
    drug_name: Optional[str] = None,
    ndc: Optional[str] = None,
    state: Optional[str] = None,
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    limit: int = 50,
    response_format: str = "markdown",
) -> str:
    """Get Medicaid state-level drug utilization data.

    Shows prescriptions filled and dollars reimbursed by state for Medicaid
    programs. Useful for understanding regional drug utilization patterns.

    Args:
        drug_name: Product name (case-insensitive, partial match).
        ndc: 11-digit NDC code.
        state: Two-letter state code (e.g., 'CA', 'TX').
        year: Year (e.g., 2023).
        quarter: Quarter (1-4).
        limit: Max results (default 50).
    """
    if not drug_name and not ndc and not state:
        return "Error: Provide at least one of drug_name, ndc, or state."

    try:
        conditions = []
        if ndc:
            conditions.append({"property": "ndc", "value": ndc})
        if drug_name:
            conditions.append({"property": "product_name", "value": f"%{drug_name.upper()}%", "operator": "LIKE"})
        if state:
            conditions.append({"property": "state", "value": state.upper()})
        if year:
            conditions.append({"property": "year", "value": str(year)})
        if quarter:
            conditions.append({"property": "quarter", "value": str(quarter)})

        params: Dict[str, Any] = {
            "limit": min(limit, 1000),
            "sorts": [{"property": "total_amount_reimbursed", "order": "desc"}],
            "conditions": conditions
        }

        # Choose dataset based on year
        dataset_id = None
        if year and year <= 2022:
            dataset_id = SDUD_2022

        data = await sdud_query(params, dataset_id=dataset_id)

        if not data:
            return "No state utilization data found for your criteria."

        if response_format == "json":
            return _json_out(data)

        lines = ["# Medicaid State Drug Utilization", ""]

        for record in data:
            name = record.get("product_name", "N/A")
            st = record.get("state", "N/A")
            yr = record.get("year", "N/A")
            qtr = record.get("quarter", "N/A")
            rx_count = record.get("number_of_prescriptions", "N/A")
            reimbursed = record.get("total_amount_reimbursed", "N/A")
            units = record.get("units_reimbursed", "N/A")
            suppression = record.get("suppression_used", "")

            if suppression:
                lines.append(f"- **{name}** ({st}, {yr} Q{qtr}) — *Data suppressed*")
            else:
                lines.append(f"- **{name}** ({st}, {yr} Q{qtr}) — {rx_count} Rx, ${reimbursed} reimbursed, {units} units")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 8: search_rebate_drugs
# ---------------------------------------------------------------------------
@mcp.tool(
    name="search_rebate_drugs",
    annotations={
        "title": "Search Medicaid Drug Rebate Program",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_rebate_drugs(
    drug_name: Optional[str] = None,
    ndc: Optional[str] = None,
    labeler_name: Optional[str] = None,
    limit: int = 20,
    response_format: str = "markdown",
) -> str:
    """Search the Medicaid Drug Rebate Program drug product list.

    Check if a drug participates in the rebate program, find manufacturer
    (labeler) information, and view product details. Drugs in this program
    have negotiated rebates between manufacturers and state Medicaid programs.

    Args:
        drug_name: Product name (case-insensitive, partial match).
        ndc: NDC code.
        labeler_name: Manufacturer/labeler name (partial match).
        limit: Max results (default 20).
    """
    if not drug_name and not ndc and not labeler_name:
        return "Error: Provide at least one of drug_name, ndc, or labeler_name."

    try:
        conditions = []
        if drug_name:
            conditions.append({"property": "drug_name", "value": f"%{drug_name.upper()}%", "operator": "LIKE"})
        if ndc:
            conditions.append({"property": "ndc", "value": ndc})
        if labeler_name:
            conditions.append({"property": "labeler_name", "value": f"%{labeler_name.upper()}%", "operator": "LIKE"})

        params: Dict[str, Any] = {
            "limit": min(limit, 1000),
            "conditions": conditions
        }

        data = await rebate_query(params)

        if not data:
            search_term = drug_name or ndc or labeler_name
            return f"No drugs found in the Medicaid Drug Rebate Program matching '{search_term}'."

        if response_format == "json":
            return _json_out(data)

        lines = ["# Medicaid Drug Rebate Program", ""]
        lines.append(f"Found {len(data)} products")
        lines.append("")

        for record in data:
            name = record.get("product_name", "N/A")
            ndc_code = record.get("ndc", "N/A")
            labeler = record.get("labeler_name", "N/A")
            strength = record.get("fda_product_name", "") or record.get("strength", "N/A")
            form = record.get("dosage_form", "N/A")
            fda_date = record.get("fda_approval_date", "N/A")
            market_date = record.get("market_date", "N/A")
            category = record.get("drug_category", "N/A")

            lines.append(f"### {name}")
            lines.append(f"**NDC:** {ndc_code} | **Labeler:** {labeler}")
            lines.append(f"**Form:** {form} | **Category:** {category}")
            if fda_date != "N/A":
                lines.append(f"**FDA Approval:** {fda_date} | **Market Date:** {market_date}")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "drug_data_mcp"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
