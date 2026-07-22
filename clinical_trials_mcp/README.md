# Clinical Trials MCP Server

An [MCP](https://modelcontextprotocol.io) server that wraps the **ClinicalTrials.gov v2 API** into a comprehensive tool-server for LLM agents — with full access to study results data that other MCP servers don't expose.

No API keys required. Designed for stateless deployment on Google Cloud Run.

## Tools

| Tool | Description |
|------|-------------|
| `search_trials` | Search by condition, intervention, sponsor, phase, status, location |
| `get_trial` | Full study record by NCT ID (protocol, eligibility, design, locations) |
| `get_study_results` | Outcome measures with p-values, CIs, effect sizes, participant flow |
| `get_adverse_events` | Serious and other AEs by organ system with frequency counts per arm |
| `get_study_arms` | Arm descriptions, intervention details, dosing, randomization |
| `compare_trials` | Side-by-side comparison of 2-5 trials (design, endpoints, enrollment) |
| `match_patient` | Find recruiting trials matching patient demographics and criteria |
| `summarize_endpoints` | Aggregate endpoint patterns across trials for a condition |
| `search_investigators` | Find PIs and research sites by condition, name, institution, location |
| `search_by_sponsor` | Company pipeline analysis with phase grouping |

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
gcloud run deploy clinical-trials-mcp \
  --source . \
  --port 8080 \
  --allow-unauthenticated
```

## Key Differentiators

Most clinical trials MCP servers only expose protocol data (search + get trial). This server goes further:

- **Results data** — outcome measures with statistical analyses, p-values, confidence intervals
- **Adverse events** — serious and other AEs by organ system, grouped by study arm
- **Study arms** — detailed intervention descriptions, dosing, randomization design
- **Trial comparison** — side-by-side analysis of multiple trials in one call

## Architecture

- **Transport**: Streamable HTTP (stateless, horizontally scalable)
- **Rate limiting**: Token-bucket (5 req/s, matching ClinicalTrials.gov limits)
- **Caching**: TTL-based (15m search, 1h records, 24h results)
- **Retry**: Exponential backoff on 429/503 (max 3 attempts)
- **Health check**: `GET /health` returns `{"status": "ok"}`

## Project Structure

```
clinical_trials_mcp/
├── server.py          # FastMCP server + 10 tool definitions
├── api_client.py      # Shared HTTP client, rate limiter, cache
├── requirements.txt
├── Dockerfile
└── .gitignore
```

## Part of Healthcare MCP Servers

This is the second server in a portfolio of 11 healthcare MCP servers wrapping public U.S. government APIs.

## License

Apache 2.0
