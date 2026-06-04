# drug_data_mcp

MCP server wrapping CMS drug pricing and utilization datasets for LLM agents.

## Data Sources

| Dataset | Source | Update Frequency |
|---------|--------|-----------------|
| NADAC (National Average Drug Acquisition Cost) | Data.Medicaid.gov | Weekly |
| Medicare Part D Spending by Drug | data.cms.gov | Quarterly |
| Medicare Part D Prescriber Data | data.cms.gov | Annually |
| State Drug Utilization Data (Medicaid) | Data.Medicaid.gov | Quarterly |
| Medicaid Drug Rebate Program | Data.Medicaid.gov | Quarterly |

All datasets are accessed via the Socrata SODA API. No authentication required (optional `SOCRATA_APP_TOKEN` env var for higher rate limits).

## Tools (8)

| # | Tool | Description |
|---|------|-------------|
| 1 | `get_nadac_price` | Current NADAC price by drug name or NDC |
| 2 | `search_nadac` | Advanced NADAC search with filters (classification, OTC, date/price range) |
| 3 | `get_price_history` | NADAC price trends over time (queries 2024 + 2025 data) |
| 4 | `compare_drug_prices` | Side-by-side NADAC comparison for 2-10 drugs |
| 5 | `get_part_d_spending` | Medicare Part D spending, claims, and beneficiary data |
| 6 | `get_prescriber_data` | Part D prescriber-level data by NPI, drug, state, or specialty |
| 7 | `get_state_utilization` | Medicaid state-level drug utilization (Rx counts, reimbursement) |
| 8 | `search_rebate_drugs` | Medicaid Drug Rebate Program product lookup |

## Quick Start

```bash
pip install -r requirements.txt
python server.py
```

The server starts on port 8080 (override with `PORT` env var). MCP endpoint is at `/mcp`.

## Deploy to Cloud Run

```bash
gcloud run deploy drug-data-mcp --source . --port 8080 --allow-unauthenticated
```

## Connecting to the Server

Add a custom MCP connector with the URL:

```
https://<your-cloud-run-url>/mcp
```

Set the `Accept` header to `application/json`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | No | Server port (default: 8080) |
| `SOCRATA_APP_TOKEN` | No | Socrata app token for higher rate limits |

## Architecture
