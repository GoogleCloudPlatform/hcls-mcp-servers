# fda_safety_mcp

MCP server wrapping the openFDA API for LLM agents to search drug and device safety data.

## Data Sources

| Dataset | openFDA Endpoint | Description |
|---------|------------------|-------------|
| FAERS | `/drug/event` | Drug adverse event reports |
| MAUDE | `/device/event` | Device adverse event reports |
| Drug Enforcement | `/drug/enforcement` | Drug recalls and enforcement actions |
| Device Enforcement | `/device/enforcement` | Device recalls and enforcement actions |
| 510(k) | `/device/510k` | Premarket notifications |
| Device Classification | `/device/classification` | FDA device classifications |

No authentication required. Optional `OPENFDA_API_KEY` env var for higher rate limits (240/min vs 40/min).

## Tools (6)

| # | Tool | Description |
|---|------|-------------|
| 1 | `search_adverse_events` | Query FAERS for drug adverse event reports |
| 2 | `search_device_events` | Query MAUDE for device adverse event reports |
| 3 | `search_drug_recalls` | Drug enforcement/recall actions |
| 4 | `search_device_recalls` | Device enforcement/recall actions |
| 5 | `get_510k` | 510(k) premarket notification lookup |
| 6 | `get_device_classification` | FDA device classification by product code |

## Quick Start

```bash
pip install -r requirements.txt
python server.py
```

The server starts on port 8080 (override with `PORT` env var). MCP endpoint is at `/mcp`.

## Deploy to Cloud Run

```bash
gcloud run deploy fda-safety-mcp --source . --port 8080 --allow-unauthenticated
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | No | Server port (default: 8080) |
| `OPENFDA_API_KEY` | No | openFDA API key for higher rate limits |

## Important Note

openFDA data is for research use. It should not be used to generate public safety alerts or track recall lifecycles in production. FAERS reports indicate temporal association, not causation.

## Architecture
