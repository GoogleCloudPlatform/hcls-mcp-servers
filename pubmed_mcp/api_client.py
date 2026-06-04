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
PubMed API Client

Provides two backends for searching PubMed:
1. E-utilities (NCBI) - FREE, rate-limited
2. BigQuery - Paid, semantic vector search

E-utilities is always available. BigQuery requires GOOGLE_CLOUD_PROJECT env var.
"""

import os
import re
import asyncio
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import httpx

# E-utilities configuration
EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY")

# BigQuery configuration (optional)
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
PUBMED_TABLE = "bigquery-public-data.pmc_open_access_commercial.articles"

# Lazy-load BigQuery client only if needed
_bq_client = None


def _get_bq_client():
    """Lazy-load BigQuery client."""
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        _bq_client = bigquery.Client(project=GOOGLE_CLOUD_PROJECT)
    return _bq_client


def format_api_error(error: Exception, context: str = "") -> Dict[str, Any]:
    """Format an API error for consistent error responses."""
    return {
        "error": True,
        "message": str(error),
        "context": context,
    }


# ---------------------------------------------------------------------------
# E-utilities Backend (FREE)
# ---------------------------------------------------------------------------

async def search_eutils(
    query: str,
    max_results: int = 10,
    sort: str = "relevance",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search PubMed using NCBI E-utilities API (FREE).

    Args:
        query: PubMed search query using standard syntax
               Examples: "diabetes AND treatment", "CRISPR[Title]", "Smith J[Author]"
        max_results: Maximum results to return (max 100)
        sort: Sort order - "relevance" or "date"
        api_key: Optional NCBI API key

    Returns:
        Dictionary with articles list and metadata
    """
    effective_api_key = api_key or DEFAULT_PUBMED_API_KEY
    sleep_time = 0.5 if effective_api_key else 1.0
    await asyncio.sleep(sleep_time)
    
    max_results = min(max_results, 100)

    try:
        # Step 1: Search for PMIDs
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": str(max_results),
            "sort": sort,
        }
        if effective_api_key:
            search_params["api_key"] = effective_api_key

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{EUTILS_BASE_URL}/esearch.fcgi",
                params=search_params,
                timeout=30.0,
            )
            resp.raise_for_status()
            search_data = resp.json()

        pmid_list = search_data.get("esearchresult", {}).get("idlist", [])
        total_count = int(search_data.get("esearchresult", {}).get("count", 0))

        if not pmid_list:
            return {
                "query": query,
                "total_results": total_count,
                "returned_results": 0,
                "articles": [],
            }

        # Step 2: Fetch article details
        await asyncio.sleep(sleep_time)
        articles = await fetch_articles_by_pmid(pmid_list, api_key=effective_api_key)

        return {
            "query": query,
            "total_results": total_count,
            "returned_results": len(articles),
            "articles": articles,
        }

    except httpx.HTTPError as e:
        return format_api_error(e, f"E-utilities search for: {query}")
    except Exception as e:
        return format_api_error(e, f"Unexpected error searching: {query}")


async def fetch_articles_by_pmid(pmids: List[str], api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch article details for a list of PMIDs.

    Args:
        pmids: List of PubMed IDs
        api_key: Optional NCBI API key

    Returns:
        List of article dictionaries
    """
    if not pmids:
        return []

    effective_api_key = api_key or DEFAULT_PUBMED_API_KEY
    fetch_params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    }
    if effective_api_key:
        fetch_params["api_key"] = effective_api_key

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{EUTILS_BASE_URL}/efetch.fcgi",
            params=fetch_params,
            timeout=30.0,
        )
        resp.raise_for_status()

    return _parse_pubmed_xml(resp.text)


async def get_article_by_pmid(pmid: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Get a single article by PMID.

    Args:
        pmid: PubMed ID
        api_key: Optional NCBI API key

    Returns:
        Article dictionary or error
    """
    effective_api_key = api_key or DEFAULT_PUBMED_API_KEY
    sleep_time = 0.5 if effective_api_key else 1.0
    await asyncio.sleep(sleep_time)
    
    try:
        articles = await fetch_articles_by_pmid([pmid], api_key=effective_api_key)
        if articles:
            return {"article": articles[0]}
        return {"error": True, "message": f"Article not found: {pmid}"}
    except Exception as e:
        return format_api_error(e, f"Fetching PMID: {pmid}")


async def search_by_author_eutils(
    author_name: str,
    max_results: int = 10,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search PubMed by author name using E-utilities.

    Args:
        author_name: Author name (e.g., "Smith J", "Doe Jane")
        max_results: Maximum results to return
        api_key: Optional NCBI API key

    Returns:
        Dictionary with articles by this author
    """
    # Format for PubMed author search
    query = f"{author_name}[Author]"
    return await search_eutils(query, max_results, sort="date", api_key=api_key)


async def search_advanced(
    query: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    publication_types: Optional[List[str]] = None,
    mesh_terms: Optional[List[str]] = None,
    journal: Optional[str] = None,
    title_only: bool = False,
    max_results: int = 10,
    sort: str = "relevance",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Advanced PubMed search with filters for dates, publication types, MeSH, etc.

    Args:
        query: Base search query (optional if using other filters)
        date_from: Start date (YYYY/MM/DD or YYYY)
        date_to: End date (YYYY/MM/DD or YYYY)
        publication_types: Filter by publication type(s).
            Options: "review", "clinical trial", "meta-analysis", "randomized controlled trial",
            "systematic review", "case reports", "editorial", "letter"
        mesh_terms: List of MeSH terms to search
        journal: Journal name or abbreviation
        title_only: If True, search only in title (not abstract)
        max_results: Maximum results to return
        sort: Sort order - "relevance" or "date"
        api_key: Optional NCBI API key

    Returns:
        Dictionary with articles matching all criteria
    """
    query_parts = []

    if query:
        if title_only:
            query_parts.append(f"({query}[Title])")
        else:
            query_parts.append(f"({query})")

    if date_from and date_to:
        query_parts.append(f"({date_from}:{date_to}[PDAT])")
    elif date_from:
        query_parts.append(f"({date_from}:3000[PDAT])")
    elif date_to:
        query_parts.append(f"(1800:{date_to}[PDAT])")

    if publication_types:
        pt_map = {
            "review": "Review[PT]",
            "clinical trial": "Clinical Trial[PT]",
            "meta-analysis": "Meta-Analysis[PT]",
            "randomized controlled trial": "Randomized Controlled Trial[PT]",
            "systematic review": "Systematic Review[PT]",
            "case reports": "Case Reports[PT]",
            "editorial": "Editorial[PT]",
            "letter": "Letter[PT]",
        }
        pt_terms = []
        for pt in publication_types:
            pt_lower = pt.lower()
            if pt_lower in pt_map:
                pt_terms.append(pt_map[pt_lower])
        if pt_terms:
            query_parts.append(f"({' OR '.join(pt_terms)})")

    if mesh_terms:
        mesh_query = " AND ".join([f'"{term}"[MeSH]' for term in mesh_terms])
        query_parts.append(f"({mesh_query})")

    if journal:
        query_parts.append(f'("{journal}"[Journal])')

    if not query_parts:
        return {"error": True, "message": "At least one search parameter required"}

    full_query = " AND ".join(query_parts)
    return await search_eutils(full_query, max_results, sort, api_key=api_key)


async def get_related_articles(
    pmid: str,
    max_results: int = 10,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Find articles similar to a given PMID using NCBI ELink.

    Uses PubMed's "Similar Articles" algorithm which considers word-weighted
    title/abstract, MeSH terms, and citation relationships.

    Args:
        pmid: PubMed ID to find similar articles for
        max_results: Maximum related articles to return
        api_key: Optional NCBI API key

    Returns:
        Dictionary with related articles
    """
    effective_api_key = api_key or DEFAULT_PUBMED_API_KEY
    sleep_time = 0.5 if effective_api_key else 1.0
    await asyncio.sleep(sleep_time)

    try:
        link_params = {
            "dbfrom": "pubmed",
            "db": "pubmed",
            "id": pmid,
            "cmd": "neighbor_score",
            "retmode": "json",
        }
        if effective_api_key:
            link_params["api_key"] = effective_api_key

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{EUTILS_BASE_URL}/elink.fcgi",
                params=link_params,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract linked PMIDs with scores
        linksets = data.get("linksets", [])
        if not linksets:
            return {"pmid": pmid, "related_articles": [], "total_results": 0}

        linksetdbs = linksets[0].get("linksetdbs", [])
        related_pmids = []
        for linksetdb in linksetdbs:
            if linksetdb.get("linkname") == "pubmed_pubmed":
                links = linksetdb.get("links", [])
                for link in links[:max_results]:
                    if isinstance(link, dict):
                        related_pmids.append(str(link.get("id", "")))
                    else:
                        related_pmids.append(str(link))

        if not related_pmids:
            return {"pmid": pmid, "related_articles": [], "total_results": 0}

        # Fetch article details
        await asyncio.sleep(sleep_time)
        articles = await fetch_articles_by_pmid(related_pmids[:max_results], api_key=effective_api_key)

        return {
            "pmid": pmid,
            "total_results": len(articles),
            "related_articles": articles,
        }

    except httpx.HTTPError as e:
        return format_api_error(e, f"ELink related articles for PMID: {pmid}")
    except Exception as e:
        return format_api_error(e, f"Unexpected error finding related articles: {pmid}")


async def get_citing_articles(
    pmid: str,
    max_results: int = 20,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Find articles that cite a given PMID using NCBI ELink.

    Args:
        pmid: PubMed ID to find citing articles for
        max_results: Maximum citing articles to return
        api_key: Optional NCBI API key

    Returns:
        Dictionary with citing articles
    """
    effective_api_key = api_key or DEFAULT_PUBMED_API_KEY
    sleep_time = 0.5 if effective_api_key else 1.0
    await asyncio.sleep(sleep_time)

    try:
        link_params = {
            "dbfrom": "pubmed",
            "db": "pubmed",
            "id": pmid,
            "linkname": "pubmed_pubmed_citedin",
            "retmode": "json",
        }
        if effective_api_key:
            link_params["api_key"] = effective_api_key

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{EUTILS_BASE_URL}/elink.fcgi",
                params=link_params,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract citing PMIDs
        linksets = data.get("linksets", [])
        if not linksets:
            return {"pmid": pmid, "citing_articles": [], "total_results": 0}

        linksetdbs = linksets[0].get("linksetdbs", [])
        citing_pmids = []
        for linksetdb in linksetdbs:
            if linksetdb.get("linkname") == "pubmed_pubmed_citedin":
                links = linksetdb.get("links", [])
                citing_pmids = [str(link) for link in links[:max_results]]

        if not citing_pmids:
            return {"pmid": pmid, "citing_articles": [], "total_results": 0}

        # Fetch article details
        await asyncio.sleep(sleep_time)
        articles = await fetch_articles_by_pmid(citing_pmids, api_key=effective_api_key)

        return {
            "pmid": pmid,
            "total_results": len(articles),
            "citing_articles": articles,
        }

    except httpx.HTTPError as e:
        return format_api_error(e, f"ELink citing articles for PMID: {pmid}")
    except Exception as e:
        return format_api_error(e, f"Unexpected error finding citing articles: {pmid}")


async def get_article_links(
    pmid: str,
    target_db: str = "all",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get links from a PubMed article to other NCBI databases.

    Args:
        pmid: PubMed ID
        target_db: Target database - "all", "pmc", "gene", "protein",
                   "nucleotide", "structure", "taxonomy"
        api_key: Optional NCBI API key

    Returns:
        Dictionary with links to other databases
    """
    effective_api_key = api_key or DEFAULT_PUBMED_API_KEY
    sleep_time = 0.5 if effective_api_key else 1.0
    await asyncio.sleep(sleep_time)

    try:
        link_params = {
            "dbfrom": "pubmed",
            "id": pmid,
            "cmd": "llinks",
            "retmode": "json",
        }
        if target_db != "all":
            link_params["db"] = target_db
        if effective_api_key:
            link_params["api_key"] = effective_api_key

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{EUTILS_BASE_URL}/elink.fcgi",
                params=link_params,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        # Parse link results
        linksets = data.get("linksets", [])
        if not linksets:
            return {"pmid": pmid, "links": {}}

        links_by_db: Dict[str, List[Dict[str, Any]]] = {}
        for linkset in linksets:
            # Handle idurllist format (external links)
            idurllist = linkset.get("idurllist", [])
            for idurl in idurllist:
                objurls = idurl.get("objurls", [])
                for objurl in objurls:
                    provider = objurl.get("provider", {}).get("nameabbr", "Other")
                    url = objurl.get("url", "")
                    category = objurl.get("category", "Unknown")
                    if provider not in links_by_db:
                        links_by_db[provider] = []
                    links_by_db[provider].append({"url": url, "category": category})

            # Handle linksetdbs format (internal NCBI links)
            linksetdbs = linkset.get("linksetdbs", [])
            for linksetdb in linksetdbs:
                db = linksetdb.get("dbto", "unknown")
                links = linksetdb.get("links", [])
                if db not in links_by_db:
                    links_by_db[db] = []
                links_by_db[db].extend([{"id": str(link)} for link in links[:20]])

        return {
            "pmid": pmid,
            "links": links_by_db,
        }

    except httpx.HTTPError as e:
        return format_api_error(e, f"ELink get links for PMID: {pmid}")
    except Exception as e:
        return format_api_error(e, f"Unexpected error getting links: {pmid}")


def _parse_pubmed_xml(xml_text: str) -> List[Dict[str, Any]]:
    """Parse PubMed XML response and extract article information using ElementTree."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    articles = []
    for pubmed_article in root.findall(".//PubmedArticle"):
        article_data = _parse_single_article(pubmed_article)
        if article_data:
            articles.append(article_data)
    
    return articles


def _parse_single_article(article_node: ET.Element) -> Optional[Dict[str, Any]]:
    """Parse a single article from XML element."""
    article = {}

    # PMID
    pmid_node = article_node.find(".//PMID")
    if pmid_node is not None:
        article["pmid"] = pmid_node.text.strip() if pmid_node.text else ""

    # Title
    title_node = article_node.find(".//ArticleTitle")
    if title_node is not None:
        article["title"] = _clean_xml_node_text(title_node)

    # Abstract
    abstract_nodes = article_node.findall(".//AbstractText")
    if abstract_nodes:
        abstract_parts = []
        for node in abstract_nodes:
            text = _clean_xml_node_text(node)
            if text:
                label = node.get("Label")
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
        article["abstract"] = " ".join(abstract_parts)

    # Authors
    authors = []
    author_list = article_node.find(".//AuthorList")
    if author_list is not None:
        for author in author_list.findall("Author"):
            last_name = author.find("LastName")
            initials = author.find("Initials")
            
            ln_text = last_name.text.strip() if last_name is not None and last_name.text else ""
            init_text = initials.text.strip() if initials is not None and initials.text else ""
            
            if ln_text:
                authors.append(f"{ln_text} {init_text}".strip())

    article["authors"] = authors[:10]

    # Journal
    journal_title = article_node.find(".//Journal/Title")
    if journal_title is not None:
        article["journal"] = journal_title.text.strip() if journal_title.text else ""

    # Year
    pub_date = article_node.find(".//Journal/JournalIssue/PubDate")
    if pub_date is not None:
        year_node = pub_date.find("Year")
        if year_node is not None:
            article["year"] = year_node.text.strip() if year_node.text else ""
        else:
            # Sometimes it's in MedlineDate
            medline_date = pub_date.find("MedlineDate")
            if medline_date is not None and medline_date.text:
                # Extract first 4 digits
                match = re.search(r'\d{4}', medline_date.text)
                if match:
                    article["year"] = match.group()

    # PubMed URL
    if "pmid" in article:
        article["pubmed_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{article['pmid']}/"

    return article if article.get("pmid") else None


def _clean_xml_node_text(node: ET.Element) -> str:
    """Extract and clean text from an XML element, including nested tags."""
    text = "".join(node.itertext())
    return text.strip()


# ---------------------------------------------------------------------------
# BigQuery Backend (PAID - requires GOOGLE_CLOUD_PROJECT)
# ---------------------------------------------------------------------------

def is_bigquery_available() -> bool:
    """Check if BigQuery backend is available."""
    return GOOGLE_CLOUD_PROJECT is not None


async def search_semantic(
    query: str,
    max_results: int = 10,
    include_full_text: bool = False,
) -> Dict[str, Any]:
    """
    Search PubMed using semantic vector search via BigQuery.

    COST WARNING: ~$0.08 per query, ~$0.69 if include_full_text=True

    Args:
        query: Natural language search query
        max_results: Maximum results to return
        include_full_text: Include article full text (increases cost 9x)

    Returns:
        Dictionary with semantically relevant articles
    """
    if not is_bigquery_available():
        return {
            "error": True,
            "message": "BigQuery not configured. Set GOOGLE_CLOUD_PROJECT env var.",
        }

    # BigQuery library is synchronous, we run it in a thread to avoid blocking
    return await asyncio.to_thread(_search_semantic_sync, query, max_results, include_full_text)


def _search_semantic_sync(query: str, max_results: int, include_full_text: bool) -> Dict[str, Any]:
    bq_client = _get_bq_client()
    safe_query = query.replace("'", "''")

    if include_full_text:
        select_columns = "base.pmc_id, base.pmid, base.title, base.author, base.article_text, base.pmc_link, distance"
    else:
        select_columns = "base.pmc_id, base.pmid, base.title, base.author, base.pmc_link, distance"

    sql = f"""
    CREATE SCHEMA IF NOT EXISTS models
    OPTIONS(location="US");

    CREATE MODEL IF NOT EXISTS models.textembed
    REMOTE WITH CONNECTION DEFAULT
    OPTIONS(endpoint="text-embedding-005");

    WITH query_embedding AS (
      SELECT ml_generate_embedding_result AS embedding_col
      FROM ML.GENERATE_EMBEDDING(
        MODEL models.textembed,
        (SELECT '{safe_query}' AS content),
        STRUCT(TRUE AS flatten_json_output)
      )
    )
    SELECT
      {select_columns}
    FROM VECTOR_SEARCH(
      TABLE `{PUBMED_TABLE}`,
      'ml_generate_embedding_result',
      (SELECT embedding_col FROM query_embedding),
      top_k => {max_results}
    )
    ORDER BY distance ASC;
    """

    try:
        query_job = bq_client.query(sql)
        results = query_job.result()

        articles = []
        for row in results:
            article = {
                "pmc_id": str(row.pmc_id) if row.pmc_id else None,
                "pmid": str(row.pmid) if row.pmid else None,
                "title": row.title,
                "authors": row.author,
                "pmc_link": row.pmc_link if hasattr(row, 'pmc_link') else None,
                "relevance_score": 1 - float(row.distance) if hasattr(row, 'distance') else None,
            }
            if include_full_text and hasattr(row, 'article_text'):
                article["full_text"] = row.article_text[:2000] if row.article_text else None
            articles.append(article)

        return {
            "query": query,
            "backend": "bigquery_semantic",
            "returned_results": len(articles),
            "articles": articles,
        }

    except Exception as e:
        return format_api_error(e, f"BigQuery semantic search for: {query}")


async def search_by_author_bq(
    author_name: str,
    max_results: int = 10,
) -> Dict[str, Any]:
    """
    Search PubMed by author name using BigQuery SEARCH function.

    Args:
        author_name: Author name to search for
        max_results: Maximum results to return

    Returns:
        Dictionary with articles by this author
    """
    if not is_bigquery_available():
        return {
            "error": True,
            "message": "BigQuery not configured. Set GOOGLE_CLOUD_PROJECT env var.",
        }

    return await asyncio.to_thread(_search_by_author_bq_sync, author_name, max_results)


def _search_by_author_bq_sync(author_name: str, max_results: int) -> Dict[str, Any]:
    bq_client = _get_bq_client()
    safe_author = author_name.replace("'", "''")

    sql = f"""
    SELECT pmc_id, pmid, title, author, pmc_link
    FROM `{PUBMED_TABLE}`
    WHERE SEARCH(author, '{safe_author}')
    LIMIT {max_results}
    """

    try:
        query_job = bq_client.query(sql)
        results = query_job.result()

        articles = []
        for row in results:
            articles.append({
                "pmc_id": str(row.pmc_id) if row.pmc_id else None,
                "pmid": str(row.pmid) if row.pmid else None,
                "title": row.title,
                "authors": row.author,
                "pmc_link": row.pmc_link if hasattr(row, 'pmc_link') else None,
            })

        return {
            "query": author_name,
            "backend": "bigquery",
            "returned_results": len(articles),
            "articles": articles,
        }

    except Exception as e:
        return format_api_error(e, f"BigQuery author search for: {author_name}")


async def search_fulltext(
    query: str,
    max_results: int = 10,
) -> Dict[str, Any]:
    """
    Search within full text of PMC articles using BigQuery.

    COST WARNING: ~$0.62 per query (searches ~100GB of text)

    Args:
        query: Keywords to search for in article full text
        max_results: Maximum results to return

    Returns:
        Dictionary with articles containing the search terms
    """
    if not is_bigquery_available():
        return {
            "error": True,
            "message": "BigQuery not configured. Set GOOGLE_CLOUD_PROJECT env var.",
        }

    return await asyncio.to_thread(_search_fulltext_sync, query, max_results)


def _search_fulltext_sync(query: str, max_results: int) -> Dict[str, Any]:
    bq_client = _get_bq_client()
    safe_query = query.replace("'", "''")

    sql = f"""
    SELECT pmc_id, pmid, title, author, article_text, pmc_link
    FROM `{PUBMED_TABLE}`
    WHERE SEARCH(article_text, '{safe_query}')
    LIMIT {max_results}
    """

    try:
        query_job = bq_client.query(sql)
        results = query_job.result()

        articles = []
        for row in results:
            articles.append({
                "pmc_id": str(row.pmc_id) if row.pmc_id else None,
                "pmid": str(row.pmid) if row.pmid else None,
                "title": row.title,
                "authors": row.author,
                "full_text_snippet": row.article_text[:1000] if row.article_text else None,
                "pmc_link": row.pmc_link if hasattr(row, 'pmc_link') else None,
            })

        return {
            "query": query,
            "backend": "bigquery_fulltext",
            "returned_results": len(articles),
            "articles": articles,
        }

    except Exception as e:
        return format_api_error(e, f"BigQuery fulltext search for: {query}")


# ---------------------------------------------------------------------------
# PubTator3 Backend (FREE - Entity Annotation)
# ---------------------------------------------------------------------------

PUBTATOR3_BASE_URL = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
PUBTATOR3_RATE_LIMIT = 0.34  # 3 requests/second max

_pubtator_last_request = 0


async def _pubtator_rate_limit():
    """Enforce PubTator3 rate limit."""
    global _pubtator_last_request
    elapsed = asyncio.get_event_loop().time() - _pubtator_last_request
    if elapsed < PUBTATOR3_RATE_LIMIT:
        await asyncio.sleep(PUBTATOR3_RATE_LIMIT - elapsed)
    _pubtator_last_request = asyncio.get_event_loop().time()


async def export_publications(
    pmids: List[str],
    format: str = "biocjson",
    full_text: bool = False,
) -> Dict[str, Any]:
    """
    Export PubTator3 entity annotations for a list of PMIDs.

    Returns genes, diseases, chemicals, species, mutations, and cell lines
    found in the articles.

    Args:
        pmids: List of PubMed IDs (e.g., ["32133824", "34170578"])
        format: Output format - "biocjson", "biocxml", or "pubtator"
        full_text: Include full text annotations (only for biocjson/biocxml)

    Returns:
        Dictionary with annotated documents
    """
    if not pmids:
        return {"error": True, "message": "PMIDs list cannot be empty"}

    if format not in ["pubtator", "biocxml", "biocjson"]:
        return {"error": True, "message": "format must be: pubtator, biocxml, or biocjson"}

    await _pubtator_rate_limit()

    try:
        url = f"{PUBTATOR3_BASE_URL}/publications/export/{format}"
        params = {"pmids": ",".join(pmids)}
        if full_text and format != "pubtator":
            params["full"] = "true"

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=30.0)
            resp.raise_for_status()

            if format == "biocjson":
                result = resp.json()
                # Normalize response structure - PubTator3 wraps in "PubTator3" key
                if isinstance(result, dict) and "PubTator3" in result:
                    docs = result["PubTator3"]
                    return {"documents": docs, "count": len(docs)}
                elif isinstance(result, list):
                    return {"documents": result, "count": len(result)}
                return result
            else:
                return {"content": resp.text, "format": format}

    except httpx.HTTPError as e:
        return format_api_error(e, f"PubTator3 export for PMIDs: {pmids[:3]}...")
    except Exception as e:
        return format_api_error(e, "PubTator3 export")


async def find_entity_id(
    query: str,
    concept: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Find standardized entity IDs from free text using PubTator3.

    Converts text like "metformin" to "@CHEMICAL_Metformin" which can be
    used with find_related_entities.

    Args:
        query: Free text to look up (e.g., "metformin", "diabetes", "BRCA1")
        concept: Optional entity type filter - "gene", "disease", "chemical",
                 "species", or "mutation"
        limit: Maximum number of results to return

    Returns:
        Dictionary with matching entity IDs and metadata
    """
    await _pubtator_rate_limit()

    try:
        url = f"{PUBTATOR3_BASE_URL}/entity/autocomplete/"
        params = {"query": query, "limit": limit}

        if concept:
            valid_concepts = ["gene", "disease", "chemical", "species", "mutation"]
            if concept.lower() not in valid_concepts:
                return {
                    "error": True,
                    "message": f"concept must be one of: {valid_concepts}",
                }
            params["concept"] = concept.lower()

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=30.0)
            resp.raise_for_status()
            results = resp.json()

        return {
            "query": query,
            "concept": concept,
            "results": results,
            "count": len(results) if isinstance(results, list) else 1,
        }

    except httpx.HTTPError as e:
        return format_api_error(e, f"PubTator3 entity lookup for: {query}")
    except Exception as e:
        return format_api_error(e, "PubTator3 entity lookup")


async def find_related_entities(
    entity_id: str,
    relation_type: Optional[str] = None,
    target_type: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Find entities related to a given entity using PubTator3.

    For example: find drugs that treat a disease, genes that interact, etc.

    Args:
        entity_id: Entity ID from find_entity_id (must start with "@",
                   e.g., "@CHEMICAL_Metformin", "@DISEASE_Diabetes Mellitus")
        relation_type: Optional relation filter - "treat", "cause", "interact",
                      "associate", "positive_correlate", "negative_correlate",
                      "prevent", "inhibit", "stimulate", "drug_interact"
        target_type: Optional target entity type - "gene", "disease",
                     "chemical", "variant"
        limit: Maximum number of results

    Returns:
        Dictionary with related entities and their relationships
    """
    if not entity_id.startswith("@"):
        return {
            "error": True,
            "message": "entity_id must start with '@' (e.g., '@CHEMICAL_Metformin'). "
                       "Use find_entity_id to get valid IDs.",
        }

    await _pubtator_rate_limit()

    try:
        url = f"{PUBTATOR3_BASE_URL}/relations"
        params = {"e1": entity_id, "limit": limit}

        valid_relations = [
            "treat", "cause", "cotreat", "convert", "compare",
            "interact", "associate", "positive_correlate",
            "negative_correlate", "prevent", "inhibit",
            "stimulate", "drug_interact"
        ]

        if relation_type:
            if relation_type.lower() not in valid_relations:
                return {
                    "error": True,
                    "message": f"relation_type must be one of: {valid_relations}",
                }
            params["type"] = relation_type.lower()

        if target_type:
            valid_targets = ["gene", "disease", "chemical", "variant"]
            if target_type.lower() not in valid_targets:
                return {
                    "error": True,
                    "message": f"target_type must be one of: {valid_targets}",
                }
            params["e2"] = target_type.lower()

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=30.0)
            resp.raise_for_status()
            results = resp.json()

        return {
            "entity_id": entity_id,
            "relation_type": relation_type,
            "target_type": target_type,
            "relations": results,
            "count": len(results) if isinstance(results, list) else 1,
        }

    except httpx.HTTPError as e:
        return format_api_error(e, f"PubTator3 relations for: {entity_id}")
    except Exception as e:
        return format_api_error(e, "PubTator3 relations")
