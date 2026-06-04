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
PubMed MCP Server

Wraps PubMed/PMC into an MCP server with two backends:
- E-utilities (FREE): Always available, standard PubMed search
- BigQuery (PAID): Optional, semantic vector search on PMC full text

No authentication required for E-utilities. BigQuery requires GOOGLE_CLOUD_PROJECT.
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
    export_publications,
    find_entity_id,
    find_related_entities,
    get_article_by_pmid,
    get_article_links,
    get_citing_articles,
    is_bigquery_available,
    search_advanced,
    search_by_author_bq,
    search_by_author_eutils,
    search_eutils,
    search_fulltext,
    search_semantic,
)

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "pubmed_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


def _json_out(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _get_api_key() -> Optional[str]:
    """Extract PubMed API key from the HTTP request query string or env var.

    Priority: query param 'pubmed_api_key' > env var PUBMED_API_KEY.
    """
    if HAS_HTTP_REQUEST:
        try:
            request = get_http_request()
            if request and request.url:
                url_str = str(request.url)
                parsed = urlparse(url_str)
                qs = parse_qs(parsed.query)
                key = qs.get("pubmed_api_key", [None])[0]
                if key:
                    return key
        except Exception:
            pass

    return os.environ.get("PUBMED_API_KEY")


def _md_article_summary(article: Dict[str, Any]) -> str:
    """Format a single article as a concise markdown block."""
    pmid = article.get("pmid", "N/A")
    title = article.get("title", "Untitled")
    authors = article.get("authors", [])
    if isinstance(authors, list):
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += f" et al. ({len(authors)} authors)"
    else:
        author_str = str(authors) if authors else "Unknown"

    journal = article.get("journal", "")
    year = article.get("year", "")
    pub_info = f"{journal} ({year})" if journal and year else journal or year or ""

    url = article.get("pubmed_url") or article.get("pmc_link") or ""

    lines = [f"### {title}"]
    if author_str:
        lines.append(f"**Authors:** {author_str}")
    if pub_info:
        lines.append(f"**Published:** {pub_info}")
    if pmid and pmid != "N/A":
        lines.append(f"**PMID:** {pmid}")
    if url:
        lines.append(f"**Link:** {url}")

    abstract = article.get("abstract", "")
    if abstract:
        # Truncate long abstracts
        if len(abstract) > 500:
            abstract = abstract[:500] + "..."
        lines.append(f"\n{abstract}")

    return "\n".join(lines)


def _format_results(
    results: Dict[str, Any],
    response_format: str = "markdown",
) -> str:
    """Format search results as markdown or JSON."""
    if results.get("error"):
        return _json_out(results)

    if response_format == "json":
        return _json_out(results)

    # Markdown format
    articles = results.get("articles", [])
    total = results.get("total_results", len(articles))
    returned = results.get("returned_results", len(articles))
    query = results.get("query", "")
    backend = results.get("backend", "eutils")

    lines = [f"## PubMed Search Results"]
    if query:
        lines.append(f"**Query:** {query}")
    lines.append(f"**Results:** {returned} of {total} | **Backend:** {backend}")
    lines.append("")

    if not articles:
        lines.append("No articles found.")
    else:
        for article in articles:
            lines.append(_md_article_summary(article))
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# E-utilities Tools (FREE - Always Available)
# ---------------------------------------------------------------------------

@mcp.tool(
    name="search_pubmed",
    annotations={
        "title": "Search PubMed (E-utilities)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_pubmed(
    query: str,
    max_results: int = 10,
    sort: str = "relevance",
    response_format: str = "markdown",
) -> str:
    """Search PubMed for scientific articles using NCBI E-utilities (FREE).

    This is the default search tool - use it for most PubMed searches.
    Supports standard PubMed search syntax.

    Args:
        query: Search query using PubMed syntax.
               Examples:
               - "diabetes AND GLP-1 agonists"
               - "CRISPR[Title]"
               - "cancer immunotherapy AND 2020:2024[PDAT]"
               - "Smith J[Author]"
        max_results: Maximum number of articles to return (1-100, default: 10)
        sort: Sort order - "relevance" or "date" (default: relevance)
        response_format: Output format - "markdown" or "json"

    Returns:
        Search results with article titles, authors, abstracts, and PubMed links.
    """
    api_key = _get_api_key()
    results = await search_eutils(query, max_results, sort, api_key=api_key)
    results["backend"] = "eutils"
    return _format_results(results, response_format)


@mcp.tool(
    name="search_by_author",
    annotations={
        "title": "Search by Author (E-utilities)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_by_author(
    author_name: str,
    max_results: int = 10,
    response_format: str = "markdown",
) -> str:
    """Search PubMed for articles by a specific author (FREE).

    Args:
        author_name: Author name to search for.
                     Examples: "Smith J", "Doe Jane", "Einstein Albert"
        max_results: Maximum number of articles to return (1-100, default: 10)
        response_format: Output format - "markdown" or "json"

    Returns:
        Articles by the specified author, sorted by date (newest first).
    """
    api_key = _get_api_key()
    results = await search_by_author_eutils(author_name, max_results, api_key=api_key)
    results["backend"] = "eutils"
    return _format_results(results, response_format)


@mcp.tool(
    name="get_article",
    annotations={
        "title": "Get Article by PMID",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_article(
    pmid: str,
    response_format: str = "markdown",
) -> str:
    """Get a specific PubMed article by its PMID (FREE).

    Args:
        pmid: PubMed ID (e.g., "12345678")
        response_format: Output format - "markdown" or "json"

    Returns:
        Full article details including title, authors, abstract, journal, and year.
    """
    api_key = _get_api_key()
    result = await get_article_by_pmid(pmid, api_key=api_key)

    if result.get("error"):
        return _json_out(result)

    if response_format == "json":
        return _json_out(result)

    article = result.get("article", {})
    return _md_article_summary(article)


@mcp.tool(
    name="advanced_search",
    annotations={
        "title": "Advanced PubMed Search",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def advanced_search_tool(
    query: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    publication_types: Optional[List[str]] = None,
    mesh_terms: Optional[List[str]] = None,
    journal: Optional[str] = None,
    title_only: bool = False,
    max_results: int = 10,
    sort: str = "relevance",
    response_format: str = "markdown",
) -> str:
    """Advanced PubMed search with filters for dates, publication types, MeSH terms (FREE).

    Use this for precise searches with specific filters. Combines multiple
    criteria with AND logic.

    Args:
        query: Base search query (optional if using other filters)
        date_from: Start date (YYYY/MM/DD or YYYY). Example: "2020" or "2023/01/01"
        date_to: End date (YYYY/MM/DD or YYYY). Example: "2024"
        publication_types: Filter by type(s). Options: "review", "clinical trial",
            "meta-analysis", "randomized controlled trial", "systematic review",
            "case reports", "editorial", "letter"
        mesh_terms: List of MeSH terms to search.
            Examples: ["Diabetes Mellitus", "Metformin"]
        journal: Journal name or abbreviation. Example: "Nature Medicine"
        title_only: If True, search only in title (not abstract)
        max_results: Maximum results (1-100, default: 10)
        sort: Sort order - "relevance" or "date"
        response_format: Output format - "markdown" or "json"

    Returns:
        Articles matching all specified criteria.
    """
    api_key = _get_api_key()
    results = await search_advanced(
        query=query,
        date_from=date_from,
        date_to=date_to,
        publication_types=publication_types,
        mesh_terms=mesh_terms,
        journal=journal,
        title_only=title_only,
        max_results=max_results,
        sort=sort,
        api_key=api_key,
    )
    results["backend"] = "eutils"
    return _format_results(results, response_format)


@mcp.tool(
    name="get_citing_articles",
    annotations={
        "title": "Get Citing Articles",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_citing_articles_tool(
    pmid: str,
    max_results: int = 20,
    response_format: str = "markdown",
) -> str:
    """Find articles that cite a given PubMed article (FREE).

    Useful for forward citation tracking - seeing how a paper has
    influenced subsequent research.

    Args:
        pmid: PubMed ID to find citing articles for. Example: "28375731"
        max_results: Maximum citing articles to return (default: 20)
        response_format: Output format - "markdown" or "json"

    Returns:
        Articles that cite the given PMID, sorted by recency.
    """
    api_key = _get_api_key()
    result = await get_citing_articles(pmid, max_results, api_key=api_key)

    if result.get("error"):
        return _json_out(result)

    articles = result.get("citing_articles", [])
    if response_format == "json":
        return _json_out(result)

    if not articles:
        return f"No citing articles found for PMID {pmid}. This article may be new or rarely cited."

    lines = [f"## Articles Citing PMID {pmid}\n"]
    lines.append(f"**Found:** {len(articles)} citing articles\n")

    for article in articles:
        lines.append(_md_article_summary(article))
        lines.append("")

    return "\n".join(lines)


@mcp.tool(
    name="get_article_links",
    annotations={
        "title": "Get Article Database Links",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_article_links_tool(
    pmid: str,
    target_db: str = "all",
) -> str:
    """Get links from a PubMed article to other NCBI databases (FREE).

    Finds connections to full text (PMC), genes, proteins, nucleotide
    sequences, structures, and external resources like publishers.

    Args:
        pmid: PubMed ID. Example: "28375731"
        target_db: Target database - "all" (default), "pmc", "gene",
                   "protein", "nucleotide", "structure", "taxonomy"

    Returns:
        Links to related resources in other databases.
    """
    api_key = _get_api_key()
    result = await get_article_links(pmid, target_db, api_key=api_key)

    if result.get("error"):
        return _json_out(result)

    links = result.get("links", {})
    if not links:
        return f"No database links found for PMID {pmid}."

    lines = [f"## Database Links for PMID {pmid}\n"]

    for db, db_links in links.items():
        lines.append(f"### {db}")
        for link in db_links[:10]:
            if isinstance(link, dict):
                if "url" in link:
                    lines.append(f"- [{link.get('category', 'Link')}]({link['url']})")
                elif "id" in link:
                    lines.append(f"- ID: {link['id']}")
            else:
                lines.append(f"- {link}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# BigQuery Tools (PAID - Only Available if GOOGLE_CLOUD_PROJECT is set)
# ---------------------------------------------------------------------------

if is_bigquery_available():

    @mcp.tool(
        name="search_pubmed_semantic",
        annotations={
            "title": "Semantic Search (BigQuery)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def search_pubmed_semantic(
        query: str,
        max_results: int = 10,
        include_full_text: bool = False,
        response_format: str = "markdown",
    ) -> str:
        """Search PubMed Central using semantic vector search (PAID - BigQuery).

        COST: ~$0.08 per query, ~$0.69 if include_full_text=True

        Use this for complex conceptual queries where keyword matching isn't enough.
        Returns results from PMC Open Access subset (full-text articles).

        Args:
            query: Natural language query describing what you're looking for.
                   Example: "machine learning approaches for predicting drug interactions"
            max_results: Maximum number of articles to return (default: 10)
            include_full_text: Include article full text in results.
                              WARNING: Increases cost 9x! Only use if needed.
            response_format: Output format - "markdown" or "json"

        Returns:
            Semantically relevant articles ranked by embedding similarity.
        """
        results = await search_semantic(query, max_results, include_full_text)
        return _format_results(results, response_format)

    @mcp.tool(
        name="search_fulltext",
        annotations={
            "title": "Full-Text Search (BigQuery)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def search_fulltext_tool(
        query: str,
        max_results: int = 10,
        response_format: str = "markdown",
    ) -> str:
        """Search within the full text of PMC articles (PAID - BigQuery).

        COST: ~$0.62 per query (searches ~100GB of article text)

        Use this when you need to find specific terms, methods, or concepts
        mentioned in the body of articles (not just titles/abstracts).

        Args:
            query: Keywords to search for in article full text.
            max_results: Maximum number of articles to return (default: 10)
            response_format: Output format - "markdown" or "json"

        Returns:
            Articles containing the search terms with text snippets.
        """
        results = await search_fulltext(query, max_results)
        return _format_results(results, response_format)

    @mcp.tool(
        name="search_author_pmc",
        annotations={
            "title": "Author Search PMC (BigQuery)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def search_author_pmc(
        author_name: str,
        max_results: int = 10,
        response_format: str = "markdown",
    ) -> str:
        """Search PMC for articles by author name (PAID - BigQuery).

        COST: ~$0.003 per query

        Searches the PMC Open Access subset, which includes full-text articles.

        Args:
            author_name: Author name to search for.
            max_results: Maximum number of articles to return (default: 10)
            response_format: Output format - "markdown" or "json"

        Returns:
            PMC articles by the specified author.
        """
        results = await search_by_author_bq(author_name, max_results)
        return _format_results(results, response_format)


# ---------------------------------------------------------------------------
# PubTator3 Tools (FREE - Entity Annotation)
# ---------------------------------------------------------------------------

@mcp.tool(
    name="annotate_articles",
    annotations={
        "title": "Annotate Articles (PubTator3)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def annotate_articles(
    pmids: List[str],
    full_text: bool = False,
) -> str:
    """Get entity annotations for articles using PubTator3 (FREE).

    Returns all genes, diseases, chemicals, species, mutations, and cell lines
    mentioned in the articles. Useful for understanding what biomedical concepts
    are discussed in a paper.

    Args:
        pmids: List of PubMed IDs to annotate (e.g., ["32133824", "34170578"])
        full_text: Include full-text annotations if available (default: False)

    Returns:
        Annotated entities found in each article with their types and positions.
    """
    result = await export_publications(pmids, format="biocjson", full_text=full_text)

    if result.get("error"):
        return _json_out(result)

    # Format annotations in a readable way
    documents = result.get("documents", [])
    if not documents:
        return "No annotations found for the provided PMIDs."

    lines = ["## PubTator3 Entity Annotations\n"]

    for doc in documents:
        pmid = doc.get("id", "Unknown")
        lines.append(f"### PMID: {pmid}")

        passages = doc.get("passages", [])
        all_annotations = []
        for passage in passages:
            annotations = passage.get("annotations", [])
            all_annotations.extend(annotations)

        if not all_annotations:
            lines.append("No entities found.\n")
            continue

        # Group by entity type
        by_type: Dict[str, List[str]] = {}
        for ann in all_annotations:
            infons = ann.get("infons", {})
            entity_type = infons.get("type", "Unknown")
            text = ann.get("text", "")
            identifier = infons.get("identifier", "")

            key = f"{text} ({identifier})" if identifier else text
            by_type.setdefault(entity_type, []).append(key)

        for entity_type, entities in sorted(by_type.items()):
            unique_entities = list(dict.fromkeys(entities))[:10]  # Dedupe, limit
            lines.append(f"**{entity_type}:** {', '.join(unique_entities)}")

        lines.append("")

    return "\n".join(lines)


@mcp.tool(
    name="find_entity_id",
    annotations={
        "title": "Find Entity ID (PubTator3)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def find_entity_id_tool(
    query: str,
    concept: Optional[str] = None,
    limit: int = 5,
) -> str:
    """Find standardized entity IDs from free text using PubTator3 (FREE).

    Converts text like "metformin" to "@CHEMICAL_Metformin" which can then
    be used with find_related_entities to explore relationships.

    Args:
        query: Free text to look up (e.g., "metformin", "diabetes", "BRCA1")
        concept: Optional entity type filter - "gene", "disease", "chemical",
                 "species", or "mutation"
        limit: Maximum number of results to return (default: 5)

    Returns:
        Matching entity IDs that can be used for relationship queries.
    """
    result = await find_entity_id(query, concept, limit)

    if result.get("error"):
        return _json_out(result)

    results = result.get("results", [])
    if not results:
        return f"No entity IDs found for '{query}'."

    lines = [f"## Entity IDs for '{query}'\n"]
    lines.append("Use these IDs with `find_related_entities`:\n")

    for item in results:
        if isinstance(item, dict):
            entity_id = item.get("id", item.get("identifier", ""))
            name = item.get("name", item.get("text", ""))
            entity_type = item.get("type", item.get("category", ""))
            lines.append(f"- **{entity_id}** - {name} ({entity_type})")
        else:
            lines.append(f"- {item}")

    return "\n".join(lines)


@mcp.tool(
    name="find_related_entities",
    annotations={
        "title": "Find Related Entities (PubTator3)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def find_related_entities_tool(
    entity_id: str,
    relation_type: Optional[str] = None,
    target_type: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Find entities related to a given entity using PubTator3 (FREE).

    Discover relationships like: drugs that treat a disease, genes that
    interact with a protein, chemicals that cause side effects, etc.

    Args:
        entity_id: Entity ID from find_entity_id (must start with "@",
                   e.g., "@CHEMICAL_Metformin", "@DISEASE_Diabetes Mellitus")
        relation_type: Optional relation filter - "treat", "cause", "interact",
                      "associate", "prevent", "inhibit", "stimulate"
        target_type: Optional target entity type - "gene", "disease",
                     "chemical", "variant"
        limit: Maximum number of results (default: 10)

    Returns:
        Related entities and their relationships.
    """
    result = await find_related_entities(entity_id, relation_type, target_type, limit)

    if result.get("error"):
        return _json_out(result)

    relations = result.get("relations", [])
    if not relations:
        msg = f"No relationships found for '{entity_id}'"
        if relation_type:
            msg += f" with relation '{relation_type}'"
        return msg + "."

    lines = [f"## Relationships for {entity_id}\n"]

    if isinstance(relations, list):
        for rel in relations[:limit]:
            if isinstance(rel, dict):
                e2 = rel.get("e2", rel.get("entity2", ""))
                rel_type = rel.get("type", rel.get("relation", "related to"))
                score = rel.get("score", "")
                score_str = f" (score: {score:.2f})" if score else ""
                lines.append(f"- **{rel_type}** → {e2}{score_str}")
            else:
                lines.append(f"- {rel}")
    else:
        lines.append(_json_out(relations))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for Cloud Run."""
    return JSONResponse({
        "status": "healthy",
        "service": "pubmed_mcp",
        "bigquery_enabled": is_bigquery_available(),
    })


if __name__ == "__main__":
    print(f"Starting PubMed MCP Server on port {PORT}")
    print(f"BigQuery backend: {'enabled' if is_bigquery_available() else 'disabled'}")
    print(f"MCP endpoint: http://localhost:{PORT}/mcp")
    mcp.run(transport="streamable-http")
