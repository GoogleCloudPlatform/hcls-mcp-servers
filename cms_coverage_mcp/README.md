# CMS Coverage MCP Server

An [MCP](https://modelcontextprotocol.io) server that wraps the **CMS Medicare Coverage Database API** into a tool-server for LLM agents. Search National Coverage Determinations (NCDs), Local Coverage Determinations (LCDs), and coverage articles.

No API keys required. Designed for stateless deployment on Google Cloud Run.

## Tools

| Tool | Description |
|------|-------------|
| `search_ncd` | Search National Coverage Determinations by keyword |
| `get_ncd` | Get full NCD document details (coverage criteria, indications, limitations) |
| `search_lcd` | Search Local Coverage Determinations by keyword or contractor |
| `search_coverage_articles` | Search local coverage articles (billing/coding guidance) |
| `list_coverage_updates` | List recently updated coverage documents across all types |

## Quick Start

```bash
pip install -r requirements.txt
python server.py
```

The server starts on `http://localhost:8080/mcp` using Streamable HTTP transport.

## Connecting to the Server

**MCP endpoint**: `/mcp` — this is FastMCP's default Streamable HTTP path. Append `/mcp` to your base URL when configuring clients.

**Required header**: Requests must include `Accept: application/json`, or the server returns `406 Not Acceptable`.

**Health check**: `GET /health` — returns `{"status": "ok"}`.

## Deploy to Cloud Run

```bash
gcloud run deploy cms-coverage-mcp \
  --source . \
  --port 8080 \
  --allow-unauthenticated
```

## Architecture

- **Transport**: Streamable HTTP (stateless, horizontally scalable)
- **Rate limiting**: Token-bucket (20 req/s, conservative)
- **Caching**: TTL-based (24h for document lists and details)
- **Retry**: Exponential backoff on 429/503 (max 3 attempts)
- **Client-side filtering**: CMS report endpoints return all documents; keyword and contractor filtering is performed locally with cached data
- **Health check**: `GET /health` returns `{"status": "ok"}`

## Coverage Document Types

| Type | Description |
|------|-------------|
| **NCD** | National Coverage Determinations — nationwide Medicare coverage policies |
| **LCD** | Local Coverage Determinations — regional policies by MAC contractor |
| **Article** | Coverage Articles — billing and coding guidance for LCDs |

## Project Structure

```
cms_coverage_mcp/
├── server.py          # FastMCP server + 5 tool definitions
├── api_client.py      # HTTP client, rate limiter, cache, document filtering
├── requirements.txt
├── Dockerfile
└── README.md
```

## Part of Healthcare MCP Servers

This server is part of a portfolio of healthcare MCP servers wrapping public U.S. government APIs. See the [project README](../README.md) for the full list.

## License

Apache 2.0
