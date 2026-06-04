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
CMS Coverage MCP Server

Wraps the CMS Medicare Coverage Database API into an MCP server that lets
LLM agents search National Coverage Determinations (NCDs), Local Coverage
Determinations (LCDs), and coverage articles.

No authentication required for NCD endpoints.
Designed for stateless deployment on Google Cloud Run.
"""

import json
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api_client import (
    api_get,
    fetch_all_documents,
    filter_documents,
    format_api_error,
    strip_html,
)

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "cms_coverage_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


def _json_out(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)



# Tool 1: search_ncd

@mcp.tool(
    name="search_ncd",
    annotations={
        "title": "Search National Coverage Determinations",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_ncd(
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    response_format: str = "markdown",
) -> str:
    """Search CMS National Coverage Determinations (NCDs).

    NCDs are Medicare coverage policies that apply nationwide. They define
    whether Medicare will pay for specific items or services.

    Args:
        keyword: Search term to match in NCD titles (e.g., "diabetes",
                 "cardiac", "transplant"). Case-insensitive. If omitted,
                 returns all NCDs.
        page: Page number for results (default 1).
        page_size: Results per page (default 20, max 50).
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        List of matching NCDs with title, ID, last updated date,
        and link to full document.
    """
    try:
        all_docs = await fetch_all_documents("/reports/national-coverage-ncd/")
        filtered = filter_documents(all_docs, keyword=keyword)

        # Paginate
        page_size = min(page_size, 50)
        start = (page - 1) * page_size
        end = start + page_size
        page_docs = filtered[start:end]
        total = len(filtered)
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        if not page_docs:
            if keyword:
                return f"No NCDs found matching '{keyword}'. Try a broader search term."
            return "No NCDs found."

        if response_format == "json":
            return _json_out({
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "page_size": page_size,
                "results": page_docs,
            })

        lines = [f"## National Coverage Determinations"]
        if keyword:
            lines[0] += f" matching '{keyword}'"
        lines[0] += f" ({total} total, page {page}/{total_pages})"
        lines.append("")

        for doc in page_docs:
            title = doc.get("title", "Untitled")
            display_id = doc.get("document_display_id", "")
            updated = doc.get("last_updated", "")
            is_lab = " [Lab]" if doc.get("is_lab") else ""

            lines.append(f"### {title}{is_lab}")
            lines.append(f"**NCD ID**: {display_id} | **Last Updated**: {updated}")
            lines.append("")

        if page < total_pages:
            lines.append(f"*Use page={page + 1} to see more results.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 2: get_ncd

@mcp.tool(
    name="get_ncd",
    annotations={
        "title": "Get NCD Document Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_ncd(
    ncd_id: int,
    ncd_version: int = 1,
    response_format: str = "markdown",
) -> str:
    """Get full details for a specific National Coverage Determination (NCD).

    Returns the complete NCD document including coverage criteria,
    indications, limitations, benefit category, and effective dates.

    Args:
        ncd_id: NCD document ID (integer). Get this from search_ncd results.
        ncd_version: Document version (default 1). Usually 1 unless the NCD
                     has been revised.
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        Full NCD document with coverage criteria, indications/limitations,
        benefit category, effective dates, and cross-references.
    """
    try:
        data = await api_get(
            "/data/ncd",
            params={"ncdid": ncd_id, "ncdver": ncd_version},
            cache_ttl="24h",
        )

        docs = data.get("data", [])
        if not docs:
            return f"No NCD found with ID {ncd_id} (version {ncd_version}). Verify the ID from search_ncd results."

        doc = docs[0]

        if response_format == "json":
            # Clean HTML from text fields for JSON output
            cleaned = {}
            for k, v in doc.items():
                if isinstance(v, str) and ("&lt;" in v or "<" in v):
                    cleaned[k] = strip_html(v)
                else:
                    cleaned[k] = v
            return _json_out({"ncd": cleaned, "related": data.get("meta", {}).get("children", [])})

        title = doc.get("title", "Untitled")
        display_id = doc.get("document_display_id", "")
        effective = doc.get("effective_date", "")
        end_date = doc.get("effective_end_date", "N/A")
        benefit_cat = doc.get("benefit_category", "")

        lines = [f"## {title}", f"**NCD {display_id}** | **Effective**: {effective} — {end_date}", ""]

        if benefit_cat:
            lines.append(f"**Benefit Category**: {benefit_cat}")
            lines.append("")

        # Item/Service Description
        desc = strip_html(doc.get("item_service_description", ""))
        if desc:
            lines.append("### Description")
            lines.append(desc)
            lines.append("")

        # Indications and Limitations
        indications = strip_html(doc.get("indications_limitations", ""))
        if indications:
            lines.append("### Indications and Limitations of Coverage")
            lines.append(indications)
            lines.append("")

        # Reasons for Denial
        denial = strip_html(doc.get("reasons_for_denial", ""))
        if denial:
            lines.append("### Reasons for Denial")
            lines.append(denial)
            lines.append("")

        # Cross References
        xref = strip_html(doc.get("cross_reference", ""))
        if xref:
            lines.append("### Cross References")
            lines.append(xref)
            lines.append("")

        # Other text
        other = strip_html(doc.get("other_text", ""))
        if other:
            lines.append("### Additional Information")
            lines.append(other)
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 3: search_lcd

@mcp.tool(
    name="search_lcd",
    annotations={
        "title": "Search Local Coverage Determinations",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_lcd(
    keyword: Optional[str] = None,
    contractor: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    response_format: str = "markdown",
) -> str:
    """Search CMS Local Coverage Determinations (LCDs).

    LCDs are Medicare coverage policies made by local Medicare Administrative
    Contractors (MACs). They vary by region and contractor.

    Args:
        keyword: Search term to match in LCD titles (e.g., "physical therapy",
                 "genetic testing"). Case-insensitive.
        contractor: Filter by MAC contractor name (e.g., "Palmetto", "CGS",
                    "Novitas", "WPS").
        page: Page number for results (default 1).
        page_size: Results per page (default 20, max 50).
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        List of matching LCDs with title, ID, contractor, effective date,
        and link to full document.
    """
    try:
        all_docs = await fetch_all_documents("/reports/local-coverage-final-lcds")
        filtered = filter_documents(all_docs, keyword=keyword, contractor=contractor)

        page_size = min(page_size, 50)
        start = (page - 1) * page_size
        end = start + page_size
        page_docs = filtered[start:end]
        total = len(filtered)
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        if not page_docs:
            parts = []
            if keyword:
                parts.append(f"keyword '{keyword}'")
            if contractor:
                parts.append(f"contractor '{contractor}'")
            search_desc = " and ".join(parts) if parts else "your criteria"
            return f"No LCDs found matching {search_desc}. Try broader search terms."

        if response_format == "json":
            return _json_out({
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "page_size": page_size,
                "results": page_docs,
            })

        lines = [f"## Local Coverage Determinations"]
        filter_parts = []
        if keyword:
            filter_parts.append(f"'{keyword}'")
        if contractor:
            filter_parts.append(f"contractor: {contractor}")
        if filter_parts:
            lines[0] += f" ({', '.join(filter_parts)})"
        lines[0] += f" — {total} results, page {page}/{total_pages}"
        lines.append("")

        for doc in page_docs:
            title = doc.get("title", "Untitled")
            display_id = doc.get("document_display_id", "")
            contractor_info = doc.get("contractor_name_type", "").replace("\r\n", " — ")
            effective = doc.get("effective_date", "")
            note = doc.get("note", "")
            url = doc.get("url", "")

            lines.append(f"### {title}")
            lines.append(f"**LCD {display_id}** | **Effective**: {effective}")
            if contractor_info:
                lines.append(f"**Contractor**: {contractor_info}")
            if note:
                lines.append(f"*{note}*")
            if url and url.startswith("http"):
                lines.append(f"[View full LCD]({url})")
            lines.append("")

        if page < total_pages:
            lines.append(f"*Use page={page + 1} to see more results.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 4: search_coverage_articles

@mcp.tool(
    name="search_coverage_articles",
    annotations={
        "title": "Search Coverage Articles",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_coverage_articles(
    keyword: Optional[str] = None,
    contractor: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    response_format: str = "markdown",
) -> str:
    """Search CMS Local Coverage Articles.

    Coverage articles provide billing and coding guidance for LCDs. They
    include CPT/HCPCS codes, ICD-10 codes, and documentation requirements.

    Args:
        keyword: Search term to match in article titles (e.g., "billing",
                 "drug testing", "MRI"). Case-insensitive.
        contractor: Filter by MAC contractor name (e.g., "Palmetto", "CGS").
        page: Page number for results (default 1).
        page_size: Results per page (default 20, max 50).
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        List of matching coverage articles with title, ID, contractor,
        effective date, and link to full document.
    """
    try:
        all_docs = await fetch_all_documents("/reports/local-coverage-articles")
        filtered = filter_documents(all_docs, keyword=keyword, contractor=contractor)

        page_size = min(page_size, 50)
        start = (page - 1) * page_size
        end = start + page_size
        page_docs = filtered[start:end]
        total = len(filtered)
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        if not page_docs:
            parts = []
            if keyword:
                parts.append(f"keyword '{keyword}'")
            if contractor:
                parts.append(f"contractor '{contractor}'")
            search_desc = " and ".join(parts) if parts else "your criteria"
            return f"No coverage articles found matching {search_desc}."

        if response_format == "json":
            return _json_out({
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "page_size": page_size,
                "results": page_docs,
            })

        lines = [f"## Coverage Articles"]
        filter_parts = []
        if keyword:
            filter_parts.append(f"'{keyword}'")
        if contractor:
            filter_parts.append(f"contractor: {contractor}")
        if filter_parts:
            lines[0] += f" ({', '.join(filter_parts)})"
        lines[0] += f" — {total} results, page {page}/{total_pages}"
        lines.append("")

        for doc in page_docs:
            title = doc.get("title", "Untitled")
            display_id = doc.get("document_display_id", "")
            contractor_info = doc.get("contractor_name_type", "").replace("\r\n", " — ")
            effective = doc.get("effective_date", "")
            url = doc.get("url", "")

            lines.append(f"### {title}")
            lines.append(f"**Article {display_id}** | **Effective**: {effective}")
            if contractor_info:
                lines.append(f"**Contractor**: {contractor_info}")
            if url and url.startswith("http"):
                lines.append(f"[View full article]({url})")
            lines.append("")

        if page < total_pages:
            lines.append(f"*Use page={page + 1} to see more results.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Tool 5: list_coverage_updates

@mcp.tool(
    name="list_coverage_updates",
    annotations={
        "title": "List Recent Coverage Updates",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def list_coverage_updates(
    keyword: Optional[str] = None,
    document_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    response_format: str = "markdown",
) -> str:
    """List recently updated Medicare coverage documents.

    Shows NCDs, LCDs, and coverage articles that have been recently
    modified or created. Useful for tracking policy changes.

    Args:
        keyword: Optional search term to filter by title.
        document_type: Filter by type: "NCD", "LCD", or "Article".
                       Case-insensitive. If omitted, returns all types.
        page: Page number for results (default 1).
        page_size: Results per page (default 20, max 50).
        response_format: "markdown" (human-readable) or "json" (structured).

    Returns:
        List of recently updated coverage documents sorted by update date.
    """
    try:
        # Combine NCD and LCD sources, sort by update date
        all_updates: List[Dict[str, Any]] = []

        if not document_type or document_type.upper() == "NCD":
            ncds = await fetch_all_documents("/reports/national-coverage-ncd/")
            for doc in ncds:
                doc["_source_type"] = "NCD"
            all_updates.extend(ncds)

        if not document_type or document_type.upper() in ("LCD", "ARTICLE"):
            if not document_type or document_type.upper() == "LCD":
                lcds = await fetch_all_documents("/reports/local-coverage-final-lcds")
                for doc in lcds:
                    doc["_source_type"] = "LCD"
                all_updates.extend(lcds)

            if not document_type or document_type.upper() == "ARTICLE":
                articles = await fetch_all_documents("/reports/local-coverage-articles")
                for doc in articles:
                    doc["_source_type"] = "Article"
                all_updates.extend(articles)

        # Filter by keyword
        if keyword:
            all_updates = filter_documents(all_updates, keyword=keyword)

        # Sort by update date (descending)
        all_updates.sort(
            key=lambda d: d.get("last_updated_sort", d.get("updated_on_sort", "0")),
            reverse=True,
        )

        # Paginate
        page_size = min(page_size, 50)
        start = (page - 1) * page_size
        end = start + page_size
        page_docs = all_updates[start:end]
        total = len(all_updates)
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1

        if not page_docs:
            return "No recent coverage updates found."

        if response_format == "json":
            return _json_out({
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "results": page_docs,
            })

        lines = [f"## Recent Coverage Updates"]
        if keyword:
            lines[0] += f" matching '{keyword}'"
        if document_type:
            lines[0] += f" (type: {document_type.upper()})"
        lines[0] += f" — {total} total, page {page}/{total_pages}"
        lines.append("")

        for doc in page_docs:
            title = doc.get("title", "Untitled")
            display_id = doc.get("document_display_id", "")
            doc_type = doc.get("_source_type", doc.get("document_type", ""))
            updated = doc.get("last_updated", doc.get("updated_on", ""))
            url = doc.get("url", "")

            lines.append(f"- **[{doc_type}] {title}** ({display_id})")
            lines.append(f"  Updated: {updated}")
            if url and url.startswith("http"):
                lines.append(f"  [View document]({url})")

        lines.append("")
        if page < total_pages:
            lines.append(f"*Use page={page + 1} to see more results.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)



# Health check

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "cms_coverage_mcp"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
