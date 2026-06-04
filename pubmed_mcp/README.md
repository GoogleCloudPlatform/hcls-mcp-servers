# pubmed_mcp

MCP server for searching PubMed/PMC scientific literature and annotating biomedical entities.

## Data Sources

| Source | API | Cost | Description |
|--------|-----|------|-------------|
| **PubMed** | [E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/) | FREE | 36M+ citations, abstracts, metadata |
| **PMC** | [BigQuery Public Dataset](https://console.cloud.google.com/marketplace/product/nih-nlm-ncbi/pmc-open-access) | ~$0.003-$0.69/query | 5M+ full-text open access articles |
| **PubTator3** | [REST API](https://www.ncbi.nlm.nih.gov/research/pubtator3/api) | FREE | AI-powered entity annotations (genes, diseases, chemicals) |

E-utilities and PubTator3 tools are always available. BigQuery tools only appear if `GOOGLE_CLOUD_PROJECT` is set.

### Resources

- **E-utilities Documentation:** https://www.ncbi.nlm.nih.gov/books/NBK25500/
- **PubMed Search Syntax:** https://pubmed.ncbi.nlm.nih.gov/help/
- **MeSH Browser:** https://meshb.nlm.nih.gov/search
- **PMC Open Access BigQuery:** https://console.cloud.google.com/marketplace/product/nih-nlm-ncbi/pmc-open-access
- **PubTator3 Documentation:** https://www.ncbi.nlm.nih.gov/research/pubtator3/tutorial

## Tools (14)

### Search Tools - E-utilities (FREE)

| # | Tool | Description |
|---|------|-------------|
| 1 | `search_pubmed` | Search PubMed using standard query syntax |
| 2 | `search_by_author` | Find articles by author name |
| 3 | `get_article` | Get article details by PMID |
| 4 | `get_articles_batch` | Get multiple articles by PMIDs |
| 5 | `advanced_search` | Search with date ranges, publication types, MeSH terms, journals |
| 6 | `get_related_articles` | Find similar articles using NCBI's similarity algorithm |
| 7 | `get_citing_articles` | Find articles that cite a given PMID |
| 8 | `get_article_links` | Get links to PMC, gene, protein, and other databases |

### Search Tools - BigQuery (PAID, optional)

| # | Tool | Cost | Description |
|---|------|------|-------------|
| 9 | `search_pubmed_semantic` | ~$0.08 | Semantic vector search using embeddings |
| 10 | `search_fulltext` | ~$0.62 | Search within article full text |
| 11 | `search_author_pmc` | ~$0.003 | Author search on PMC |

### Annotation Tools - PubTator3 (FREE)

| # | Tool | Description |
|---|------|-------------|
| 12 | `annotate_articles` | Get entity annotations for PMIDs (genes, diseases, chemicals, etc.) |
| 13 | `find_entity_id` | Convert free text to standardized entity ID (e.g., "metformin" → "@CHEMICAL_Metformin") |
| 14 | `find_related_entities` | Find relationships between entities (drugs that treat diseases, gene interactions, etc.) |

## Quick Start

```bash
cd pubmed_mcp
pip install -r requirements.txt
python server.py
```

Server starts on port 8080. MCP endpoint at `http://localhost:8080/mcp`.

### Enable BigQuery (optional)

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
python server.py
```

### Higher E-utilities rate limit (optional)

Get a free API key from [NCBI](https://www.ncbi.nlm.nih.gov/account/):

```bash
export PUBMED_API_KEY=your-api-key
python server.py
```

## Example Queries

### E-utilities - Basic Search

```
# Keyword search
search_pubmed("diabetes AND GLP-1 agonists")

# Title search
search_pubmed("CRISPR[Title] AND gene editing")

# Author search
search_by_author("Hassabis Demis")

# Get specific article
get_article("12345678")
```

### E-utilities - Advanced Search

```
# Search with date range and publication type
advanced_search(
    query="cancer immunotherapy",
    date_from="2022",
    date_to="2024",
    publication_types=["systematic review", "meta-analysis"]
)

# Search specific journal with MeSH terms
advanced_search(
    mesh_terms=["Diabetes Mellitus, Type 2", "Metformin"],
    journal="Nature Medicine"
)

# Title-only search with filters
advanced_search(
    query="CRISPR",
    title_only=True,
    publication_types=["review"]
)
```

### E-utilities - Citation Analysis

```
# Find similar articles (literature discovery)
get_related_articles("28375731")

# Find who cites a paper (forward citation tracking)
get_citing_articles("28375731")

# Get links to genes, proteins, full text
get_article_links("28375731", target_db="gene")
```

### BigQuery (Semantic)

```
# Complex conceptual query
search_pubmed_semantic("machine learning approaches for predicting adverse drug reactions in elderly patients")

# Full-text search for specific methods
search_fulltext("Western blot AND immunoprecipitation")
```

### PubTator3 (Entity Annotation)

```
# Get all entities mentioned in an article
annotate_articles(["32133824"])

# Find entity ID for a drug
find_entity_id("metformin", concept="chemical")
# Returns: @CHEMICAL_Metformin

# Find what diseases metformin treats
find_related_entities("@CHEMICAL_Metformin", relation_type="treat")

# Find genes associated with a disease
find_related_entities("@DISEASE_Diabetes Mellitus", target_type="gene")
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | No | Server port (default: 8080) |
| `GOOGLE_CLOUD_PROJECT` | No | GCP project for BigQuery tools |
| `PUBMED_API_KEY` | No | NCBI API key for higher rate limits |

## Rate Limits

| API | Rate Limit |
|-----|------------|
| E-utilities (no key) | 3 requests/second |
| E-utilities (with key) | 10 requests/second |
| PubTator3 | 3 requests/second |
| BigQuery | No limit (pay per query) |

## Architecture
