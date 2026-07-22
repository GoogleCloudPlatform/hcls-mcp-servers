# MedlinePlus MCP Server

An [MCP](https://modelcontextprotocol.io) server that wraps two NLM services — **MedlinePlus Connect** and **MedlinePlus Web Service** — into a single tool-server for LLM agents. Look up patient-friendly health information by medical code or search health topics by keyword.

No API keys required. Designed for stateless deployment on Google Cloud Run.

## Tools

| Tool | Source API | Description |
|------|-----------|-------------|
| `search_health_topics` | Web Service | Search health topics by keyword (e.g., "diabetes", "asthma") |
| `get_health_info_by_code` | Connect | Look up health info by ICD-10, SNOMED, RxNorm, NDC, LOINC, or CPT code |
| `get_drug_information` | Connect | Get consumer drug info by RxCUI or NDC code |
| `get_lab_test_information` | Connect | Get patient-friendly lab test info by LOINC code |
| `get_procedure_information` | Connect | Get patient-friendly procedure info by CPT or SNOMED code |

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
gcloud run deploy medlineplus-mcp \
  --source . \
  --port 8080 \
  --allow-unauthenticated
```

## Architecture

- **Transport**: Streamable HTTP (stateless, horizontally scalable)
- **Rate limiting**: Separate token buckets (1.5 req/s Connect, 1.4 req/s Web Service)
- **Caching**: TTL-based (24h — content updates daily Tue-Sat)
- **Retry**: Exponential backoff on 429/503 (max 3 attempts)
- **Health check**: `GET /health` returns `{"status": "ok"}`

## Supported Code Systems

| Shorthand | Code System | Example |
|-----------|-------------|---------|
| `icd10` | ICD-10-CM | E11.65 |
| `snomed` | SNOMED CT | 44054006 |
| `rxnorm` | RxNorm (RxCUI) | 161354 |
| `ndc` | National Drug Code | 0069-1540-66 |
| `loinc` | LOINC | 2339-0 |
| `cpt` | CPT | 43239 |

## Project Structure

```
medlineplus_mcp/
├── server.py          # FastMCP server + 5 tool definitions
├── api_client.py      # Dual HTTP client (Connect + Web Service), XML parser
├── requirements.txt
├── Dockerfile
└── README.md
```

## Part of Healthcare MCP Servers

This server is part of a portfolio of healthcare MCP servers wrapping public U.S. government APIs. See the [project README](../README.md) for the full list.

## License

Apache 2.0
