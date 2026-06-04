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
RxNorm & Drug Labels MCP Server

Wraps four public NIH APIs — RxNorm, RxClass, DailyMed v2, and MED-RT —
into a single MCP server that lets LLM agents normalize drug names,
retrieve label data, check interactions, and browse drug classifications.

No authentication required for any upstream API.
Designed for stateless deployment on Google Cloud Run.
"""

import json
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api_client import (
    dailymed_get,
    format_api_error,
    interaction_get,
    rxclass_get,
    rxnorm_get,
)
PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "rxnorm_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


def _json_out(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


@mcp.tool(
    name="normalize_drug",
    annotations={
        "title": "Normalize Drug Name to RxCUI",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def normalize_drug(
    name: str,
    search_type: int = 2,
    response_format: str = "markdown",
) -> str:
    """Resolve a brand or generic drug name to its RxNorm Concept ID (RxCUI).

    This is typically the first step in any drug-related workflow. The RxCUI
    returned here is the primary key used by get_drug_info, check_interactions,
    get_drug_class, get_drug_label, and get_indications.

    Args:
        name: Drug name to normalize — brand or generic (e.g. "Lipitor",
              "atorvastatin", "metformin 500mg tablet").
        search_type: Search precision. 0=Exact, 1=Normalized, 2=Approximate
                     (default). Approximate is best for user-supplied names.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Matched drug concepts with RxCUI, name, and term type (TTY).
        TTY values: IN=Ingredient, BN=Brand Name, SCD=Semantic Clinical Drug,
        SBD=Semantic Branded Drug, GPCK=Generic Pack, BPCK=Branded Pack.
    """
    try:
        data = await rxnorm_get("/rxcui.json", params={
            "name": name,
            "search": search_type,
        })

        id_group = data.get("idGroup", {})
        candidates: List[Dict[str, str]] = []

        if "rxnormId" in id_group:
            rxcui_list = id_group["rxnormId"]
            if isinstance(rxcui_list, list):
                for rxcui in rxcui_list:
                    candidates.append({"rxcui": rxcui, "name": id_group.get("name", name), "tty": ""})
            else:
                candidates.append({"rxcui": rxcui_list, "name": id_group.get("name", name), "tty": ""})

        if not candidates:
            drug_group = data.get("drugGroup", {})
            for concept_group in drug_group.get("conceptGroup", []):
                for prop in concept_group.get("conceptProperties", []):
                    candidates.append({
                        "rxcui": prop.get("rxcui", ""),
                        "name": prop.get("name", ""),
                        "tty": prop.get("tty", ""),
                    })

        if not candidates:
            approx = await rxnorm_get("/approximateTerm.json", params={"term": name, "maxEntries": 5})
            for group in approx.get("approximateGroup", {}).get("candidate", []):
                candidates.append({
                    "rxcui": group.get("rxcui", ""),
                    "name": group.get("name", ""),
                    "tty": group.get("tty", ""),
                    "score": group.get("score", ""),
                })

        if not candidates:
            return f"No RxNorm concepts found for '{name}'. Try a different spelling or a more common drug name."

        if response_format == "json":
            return _json_out({"query": name, "results": candidates})

        lines = [f"## Drug Normalization: '{name}'", ""]
        for c in candidates[:10]:
            tty = f" ({c['tty']})" if c.get("tty") else ""
            score = f" — score {c['score']}" if c.get("score") else ""
            lines.append(f"- **RxCUI {c['rxcui']}**: {c['name']}{tty}{score}")
        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


@mcp.tool(
    name="get_drug_info",
    annotations={
        "title": "Get Drug Properties and NDCs",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_drug_info(
    rxcui: str,
    response_format: str = "markdown",
) -> str:
    """Get ingredients, dosage forms, strength, and National Drug Codes (NDCs) for an RxCUI.

    Returns RxNorm properties (ingredients, dose form, strength, route) and
    associated NDC codes that can be used for drug pricing lookups.

    Args:
        rxcui: RxNorm Concept Unique Identifier (e.g. "161354" for atorvastatin
               calcium). Use normalize_drug first if you only have a name.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Drug properties including name, TTY, ingredients, dose form,
        available strengths, and up to 20 associated NDC codes.
    """
    try:
        props_data = await rxnorm_get(f"/rxcui/{rxcui}/allProperties.json", params={
            "prop": "attributes",
        })
        ndcs_data = await rxnorm_get(f"/rxcui/{rxcui}/ndcs.json")
        concept_data = await rxnorm_get(f"/rxcui/{rxcui}/properties.json")

        concept = concept_data.get("properties", {})
        drug_name = concept.get("name", "Unknown")
        tty = concept.get("tty", "")

        prop_list = props_data.get("propConceptGroup", {}).get("propConcept", [])
        properties: Dict[str, List[str]] = {}
        for p in prop_list:
            cat = p.get("propCategory", "Other")
            val = p.get("propValue", "")
            if val:
                properties.setdefault(cat, []).append(val)

        ndc_list = ndcs_data.get("ndcGroup", {}).get("ndcList", {}).get("ndc", [])

        result = {
            "rxcui": rxcui,
            "name": drug_name,
            "tty": tty,
            "properties": properties,
            "ndcs": ndc_list[:20],
            "total_ndcs": len(ndc_list),
        }

        if response_format == "json":
            return _json_out(result)

        lines = [f"## {drug_name}", f"**RxCUI**: {rxcui} | **Term Type**: {tty}", ""]
        for cat, vals in properties.items():
            lines.append(f"### {cat}")
            for v in vals[:10]:
                lines.append(f"- {v}")
            lines.append("")
        if ndc_list:
            lines.append(f"### NDC Codes ({len(ndc_list)} total, showing first 20)")
            for ndc in ndc_list[:20]:
                lines.append(f"- {ndc}")
        else:
            lines.append("*No NDC codes found for this concept.*")
        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


@mcp.tool(
    name="check_interactions",
    annotations={
        "title": "Check Drug-Drug Interactions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def check_interactions(
    rxcuis: List[str],
    response_format: str = "markdown",
) -> str:
    """Check known drug-drug interactions for one or more drugs.

    For a single RxCUI, returns all known interactions for that drug.
    For multiple RxCUIs, returns interactions between the specified drugs.
    Sources: ONCHigh (oncology high-severity) and DrugBank.

    Args:
        rxcuis: One or more RxCUIs to check (e.g. ["207106", "152923"]).
                Provide 2+ to check a specific pair, or 1 to see all known
                interactions for that drug.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        List of interaction pairs with severity, description, and source.
    """
    try:
        try:
            if len(rxcuis) == 1:
                data = await interaction_get("/interaction.json", params={
                    "rxcui": rxcuis[0],
                })
            else:
                data = await interaction_get("/list.json", params={
                    "rxcuis": "+".join(rxcuis),
                })
        except Exception as exc:
            import httpx as _httpx
            if isinstance(exc, _httpx.HTTPStatusError) and exc.response.status_code == 404:
                return f"No known interactions found for RxCUI(s): {', '.join(rxcuis)}."
            raise

        interactions: List[Dict[str, str]] = []

        for group in data.get("interactionTypeGroup", []):
            source = group.get("sourceName", "")
            for itype in group.get("interactionType", []):
                for pair in itype.get("interactionPair", []):
                    desc = pair.get("description", "")
                    severity = pair.get("severity", "N/A")
                    concepts = pair.get("interactionConcept", [])
                    drug_names = [c.get("minConceptItem", {}).get("name", "") for c in concepts]
                    interactions.append({
                        "drugs": " ↔ ".join(drug_names),
                        "description": desc,
                        "severity": severity,
                        "source": source,
                    })

        for group in data.get("fullInteractionTypeGroup", []):
            source = group.get("sourceName", "")
            for itype in group.get("fullInteractionType", []):
                for pair in itype.get("interactionPair", []):
                    desc = pair.get("description", "")
                    severity = pair.get("severity", "N/A")
                    concepts = pair.get("interactionConcept", [])
                    drug_names = [c.get("minConceptItem", {}).get("name", "") for c in concepts]
                    interactions.append({
                        "drugs": " ↔ ".join(drug_names),
                        "description": desc,
                        "severity": severity,
                        "source": source,
                    })

        if not interactions:
            rxcui_str = ", ".join(rxcuis)
            return f"No known interactions found for RxCUI(s): {rxcui_str}."

        if response_format == "json":
            return _json_out({"rxcuis": rxcuis, "interaction_count": len(interactions), "interactions": interactions})

        lines = [f"## Drug Interactions ({len(interactions)} found)", ""]
        for ix in interactions[:30]:
            lines.append(f"### {ix['drugs']}")
            lines.append(f"- **Severity**: {ix['severity']}")
            lines.append(f"- **Source**: {ix['source']}")
            lines.append(f"- {ix['description']}")
            lines.append("")
        if len(interactions) > 30:
            lines.append(f"*… and {len(interactions) - 30} more. Use JSON format for full results.*")
        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


_CLASS_RELA_MAP = {
    "therapeutic": [("ATC", None), ("MEDRT", "has_PE")],
    "moa": [("MEDRT", "has_MoA")],
    "pk": [("MEDRT", "has_PK")],
    "pe": [("MEDRT", "has_PE")],
    "chem": [("MEDRT", "has_Chem")],
    "all": [("ATC", None), ("MEDRT", None)],
}


@mcp.tool(
    name="get_drug_class",
    annotations={
        "title": "Get Drug Classification",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_drug_class(
    rxcui: str,
    class_type: str = "all",
    response_format: str = "markdown",
) -> str:
    """Get therapeutic class, mechanism of action, or pharmacokinetics for a drug.

    Uses ATC classification and MED-RT ontology via the RxClass API.

    Args:
        rxcui: RxNorm Concept ID (e.g. "161354"). Use normalize_drug first
               if you only have a name.
        class_type: Which classification to return. One of: "all" (default),
                    "therapeutic", "moa", "pk", "pe", "chem".
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Drug classification data grouped by source and relationship type.
    """
    try:
        query_params: Dict[str, str] = {"rxcui": rxcui}
        sources = _CLASS_RELA_MAP.get(class_type, _CLASS_RELA_MAP["all"])

        all_classes: List[Dict[str, str]] = []
        for source, rela in sources:
            p = {**query_params, "relaSource": source}
            if rela:
                p["relas"] = rela
            data = await rxclass_get("/class/byRxcui.json", params=p)

            for group in data.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", []):
                cls_info = group.get("rxclassMinConceptItem", {})
                rela_info = group.get("rela", "")
                all_classes.append({
                    "class_id": cls_info.get("classId", ""),
                    "class_name": cls_info.get("className", ""),
                    "class_type": cls_info.get("classType", ""),
                    "source": source,
                    "relationship": rela_info,
                })

        if not all_classes:
            return f"No classifications found for RxCUI {rxcui} with type '{class_type}'."

        if response_format == "json":
            return _json_out({"rxcui": rxcui, "class_type": class_type, "classes": all_classes})

        lines = [f"## Drug Classification for RxCUI {rxcui}", ""]
        by_source: Dict[str, List[Dict[str, str]]] = {}
        for c in all_classes:
            key = f"{c['source']} — {c['relationship']}" if c["relationship"] else c["source"]
            by_source.setdefault(key, []).append(c)

        for src, classes in by_source.items():
            lines.append(f"### {src}")
            for c in classes:
                lines.append(f"- **{c['class_name']}** (ID: {c['class_id']}, type: {c['class_type']})")
            lines.append("")
        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


@mcp.tool(
    name="get_drug_label",
    annotations={
        "title": "Get FDA Drug Label (SPL)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_drug_label(
    rxcui: Optional[str] = None,
    set_id: Optional[str] = None,
    response_format: str = "markdown",
) -> str:
    """Get an FDA-approved drug label from DailyMed (Structured Product Label).

    Returns the label title, effective date, and link to the full label.
    Provide either an RxCUI or a DailyMed setId.

    Args:
        rxcui: RxCUI to look up the label for. Provide either rxcui or set_id.
        set_id: DailyMed SPL setId (UUID). Provide either rxcui or set_id.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        SPL metadata: title, setId, version, published date,
        and a URL to the full label on DailyMed.
    """
    try:
        if not rxcui and not set_id:
            return "Error: Provide either rxcui or set_id. Use normalize_drug to get an RxCUI from a drug name."

        if set_id:
            data = await dailymed_get(f"/spls/{set_id}.json")
            spls = [data] if data else []
        else:
            data = await dailymed_get("/spls.json", params={"rxcui": rxcui, "pagesize": 5})
            spls = data.get("data", [])

        if not spls:
            key = set_id or rxcui
            return f"No drug labels found for {'setId' if set_id else 'RxCUI'} '{key}'."

        results = []
        for spl in spls[:5]:
            sid = spl.get("setid", spl.get("spl_set_id", ""))
            results.append({
                "set_id": sid,
                "title": spl.get("title", ""),
                "published_date": spl.get("published_date", ""),
                "spl_version": spl.get("spl_version", ""),
                "dailymed_url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={sid}",
            })

        if response_format == "json":
            return _json_out({"results": results})

        lines = []
        for r in results:
            lines.append(f"## {r['title']}")
            lines.append(f"- **Set ID**: {r['set_id']}")
            lines.append(f"- **Published**: {r['published_date']}")
            lines.append(f"- **Version**: {r['spl_version']}")
            lines.append(f"- **Full label**: {r['dailymed_url']}")
            lines.append("")
        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


@mcp.tool(
    name="search_drug_labels",
    annotations={
        "title": "Search DailyMed Drug Labels",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_drug_labels(
    drug_name: Optional[str] = None,
    boxed_warning: Optional[bool] = None,
    page: int = 1,
    page_size: int = 10,
    response_format: str = "markdown",
) -> str:
    """Search DailyMed drug labels by drug name or boxed warning status.

    Returns a paginated list of matching SPL labels with links to full text.

    Args:
        drug_name: Drug name to search (e.g. "metformin"). At least one of
                   drug_name or boxed_warning is required.
        boxed_warning: If true, filter to drugs with a boxed (black box) warning.
        page: Page number for pagination (starts at 1, default 1).
        page_size: Results per page (default 10, max 100).
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Paginated list of matching drug labels with title, setId, date,
        and DailyMed URL.
    """
    try:
        if not drug_name and boxed_warning is None:
            return "Error: Provide at least drug_name or boxed_warning=true to search."

        query: Dict[str, Any] = {
            "pagesize": page_size,
            "page": page,
        }
        if drug_name:
            query["drug_name"] = drug_name
        if boxed_warning is not None:
            query["boxed_warning"] = "1" if boxed_warning else "0"

        data = await dailymed_get("/spls.json", params=query)

        metadata = data.get("metadata", {})
        spls = data.get("data", [])

        results = []
        for spl in spls:
            sid = spl.get("setid", spl.get("spl_set_id", ""))
            results.append({
                "set_id": sid,
                "title": spl.get("title", ""),
                "published_date": spl.get("published_date", ""),
                "dailymed_url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={sid}",
            })

        total = metadata.get("total_elements", len(results))
        total_pages = metadata.get("total_pages", 1)

        if response_format == "json":
            return _json_out({
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "count": len(results),
                "results": results,
            })

        if not results:
            return "No drug labels found matching your search criteria."

        lines = [f"## Drug Label Search Results (page {page}/{total_pages}, {total} total)", ""]
        for r in results:
            lines.append(f"- **{r['title']}**")
            lines.append(f"  Set ID: {r['set_id']} | Published: {r['published_date']}")
            lines.append(f"  [View full label]({r['dailymed_url']})")
            lines.append("")
        if page < total_pages:
            lines.append(f"*Use page={page + 1} to see more results.*")
        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


@mcp.tool(
    name="get_indications",
    annotations={
        "title": "Get Disease-Drug Indications (MED-RT)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_indications(
    rxcui: str,
    response_format: str = "markdown",
) -> str:
    """Get disease-drug indication relationships from the MED-RT ontology.

    Returns the diseases/conditions that a drug is indicated for, and
    contraindications, using MED-RT data via the RxClass API.

    Args:
        rxcui: RxNorm Concept ID (e.g. "161354"). Use normalize_drug first
               if you only have a name.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        List of indicated diseases and contraindications with MED-RT class IDs.
    """
    try:
        indication_data = await rxclass_get("/class/byRxcui.json", params={
            "rxcui": rxcui,
            "relaSource": "MEDRT",
            "relas": "may_treat",
        })

        ci_data = await rxclass_get("/class/byRxcui.json", params={
            "rxcui": rxcui,
            "relaSource": "MEDRT",
            "relas": "CI_with",
        })

        indications: List[Dict[str, str]] = []
        for group in indication_data.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", []):
            cls = group.get("rxclassMinConceptItem", {})
            indications.append({
                "class_id": cls.get("classId", ""),
                "disease": cls.get("className", ""),
                "relationship": "may_treat",
            })

        contraindications: List[Dict[str, str]] = []
        for group in ci_data.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", []):
            cls = group.get("rxclassMinConceptItem", {})
            contraindications.append({
                "class_id": cls.get("classId", ""),
                "disease": cls.get("className", ""),
                "relationship": "CI_with",
            })

        if not indications and not contraindications:
            return f"No indication or contraindication data found for RxCUI {rxcui} in MED-RT."

        if response_format == "json":
            return _json_out({
                "rxcui": rxcui,
                "indications": indications,
                "contraindications": contraindications,
            })

        lines = [f"## Indications for RxCUI {rxcui}", ""]
        if indications:
            lines.append("### Indicated For (may_treat)")
            for ind in indications:
                lines.append(f"- {ind['disease']} (MED-RT: {ind['class_id']})")
            lines.append("")
        if contraindications:
            lines.append("### Contraindicated With (CI_with)")
            for ci in contraindications:
                lines.append(f"- {ci['disease']} (MED-RT: {ci['class_id']})")
            lines.append("")
        if not indications:
            lines.append("*No 'may_treat' indications found in MED-RT.*\n")
        if not contraindications:
            lines.append("*No contraindications found in MED-RT.*\n")
        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "rxnorm_mcp"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
