# NPI Registry MCP Server

An [MCP](https://modelcontextprotocol.io) server that wraps the **CMS NPPES NPI Registry API** into a tool-server for LLM agents. Search for healthcare providers, look up provider details, and validate NPI numbers.

No API keys required. Designed for stateless deployment on Google Cloud Run.

## Tools

| Tool | Description |
|------|-------------|
| `npi_search` | Search providers by name, location, specialty, or organization. Supports wildcards and name aliases. |
| `npi_lookup` | Get full provider details by NPI number (addresses, taxonomies, identifiers). |
| `npi_validate` | Validate NPI format and Luhn check digit (local, no API call). |
| `search_organizations` | Search organizational providers (hospitals, clinics, pharmacies) by name, state, type. |

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

Example with curl:

```bash
# Health check
curl https://YOUR-URL/health

# MCP call (note the /mcp path and Accept header)
curl -X POST https://YOUR-URL/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

For MCP clients (Claude Desktop, etc.), use the full URL including `/mcp`.

## Deploy to Cloud Run

```bash
gcloud run deploy npi-mcp \
  --source . \
  --port 8080 \
  --allow-unauthenticated
```

## Architecture

- **Transport**: Streamable HTTP (stateless, horizontally scalable)
- **Rate limiting**: Token-bucket (10 req/s, conservative)
- **Caching**: TTL-based (1h lookups, 15m searches)
- **Retry**: Exponential backoff on 429/503 (max 3 attempts)
- **Health check**: `GET /health` returns `{"status": "ok"}`

## Project Structure

```
npi_mcp/
├── server.py          # FastMCP server + 4 tool definitions
├── api_client.py      # Shared HTTP client, rate limiter, cache, Luhn validator
├── requirements.txt
├── Dockerfile
└── README.md
```

## Part of Healthcare MCP Servers

This server is part of a portfolio of healthcare MCP servers wrapping public U.S. government APIs. See the [project README](../README.md) for the full list.

## License

Apache 2.0
