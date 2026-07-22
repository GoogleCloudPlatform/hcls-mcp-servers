# RxNorm & Drug Labels MCP Server

An [MCP](https://modelcontextprotocol.io) server that wraps four public NIH APIs — **RxNorm**, **RxClass**, **DailyMed v2**, and **MED-RT** — into a single tool-server for LLM agents.

No API keys required. Designed for stateless deployment on Google Cloud Run.

## Tools

| Tool | Source API | Description |
|------|-----------|-------------|
| `normalize_drug` | RxNorm | Resolve brand/generic drug name → RxCUI |
| `get_drug_info` | RxNorm | Ingredients, dosage forms, NDCs for an RxCUI |
| `check_interactions` | RxNorm Interaction | Drug-drug interactions (single or multi-drug) |
| `get_drug_class` | RxClass + MED-RT | Therapeutic class, MOA, pharmacokinetics |
| `get_drug_label` | DailyMed v2 | FDA-approved SPL label by RxCUI or setId |
| `search_drug_labels` | DailyMed v2 | Search labels by name, boxed warning, paginated |
| `get_indications` | MED-RT via RxClass | Disease indications and contraindications |

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
gcloud run deploy rxnorm-mcp \
  --source . \
  --port 8080 \
  --allow-unauthenticated
```

## Architecture

- **Transport**: Streamable HTTP (stateless, horizontally scalable)
- **Rate limiting**: Token-bucket (15 req/s RxNav, 10 req/s DailyMed)
- **Caching**: TTL-based (24h drug data, 7d terminology)
- **Retry**: Exponential backoff on 429/503 (max 3 attempts)
- **Health check**: `GET /health` returns `{"status": "ok"}`

## Project Structure

```
rxnorm_mcp/
├── server.py          # FastMCP server + 7 tool definitions
├── api_client.py      # Shared HTTP client, rate limiter, cache
├── models.py          # Pydantic v2 input models
├── requirements.txt
├── Dockerfile
└── .gitignore
```

## Part of Healthcare MCP Servers

This is the first server in a portfolio of 11 healthcare MCP servers wrapping public U.S. government APIs.

## License

Apache 2.0
