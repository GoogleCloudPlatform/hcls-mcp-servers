# Google Cloud Healthcare MCP Servers

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

Open-source [Model Context Protocol (MCP)](https://modelcontextprotocol.io) servers that provide AI agents with structured access to public U.S. healthcare data from the [NIH](https://www.nih.gov/), [FDA](https://www.fda.gov/), [CMS](https://www.cms.gov/), and [NLM](https://www.nlm.nih.gov/). 

Deploy some or all of these 10 servers into your own Google Cloud project in minutes, then connect them to any MCP-compatible client (e.g., Gemini Enterprise, Antigravity Gemini CLI, Gemini Enterprise Agent Platform (GEAP, fomerly Vertex AI) , Claude Desktop). Each server runs as a stateless container on [Cloud Run](https://cloud.google.com/run) with built-in rate limiting, caching, and retry logic. 

Your data and the execution environment never leave your tenant.

---

## Table of Contents
- [Overview & Use Cases](#overview--use-cases)
- [Architecture](#architecture)
- [Servers Catalog](#servers-catalog)
- [Quick Start (Local)](#quick-start-local)
- [Cloud Run Deployment](#cloud-run-deployment)
  - [Prerequisites](#prerequisites)
  - [Setup](#first-time-setup)
- [Security & Authentication](#security--authentication)
- [Connecting Clients](#connecting-clients)
- [Testing](#testing)
- [Compliance & Support](#compliance--support)

---

## Overview & Use Cases

These MCP servers act as a bridge between powerful LLMs and authoritative healthcare data sources. By equipping your agents with these tools, you can automate complex biomedical and administrative workflows, such as:

*   **Pharmacovigilance:** Cross-reference FDA Adverse Event reports (FAERS) with active clinical trials and current drug labels (DailyMed).
*   **Provider Verification:** Verify NPI provider credentials against the NPPES registry and map them to CMS Medicare Coverage rules (NCDs/LCDs).
*   **Pricing Analysis:** Calculate generic vs. brand drug pricing trends using Medicaid National Average Drug Acquisition Cost (NADAC) data.
*   **Medical Coding:** Validate ICD-10-CM/PCS diagnoses and procedures for billing accuracy.
*   **Literature Review:** Synthesize biomedical literature from PubMed and translate complex medical concepts into patient-friendly materials via MedlinePlus.

---

## Architecture

The servers are designed to be deployed as a unified ecosystem on Google Cloud. They follow a stateless, serverless architecture pattern.

```text
    +-------------------+       +-----------------------+       +------------------------+
    |                   |       |     Google Cloud      |       |                        |
    |    MCP Client     |       |                       |       |   Authoritative APIs   |
    |                   |       |  +-----------------+  |       |                        |
    | +---------------+ |  HTTP |  | Cloud Load      |  |       |  +------------------+  |
    | | Gemini        | |<----->|  | Balancer & IAP  |  |       |  | NIH / NLM        |  |
    | | GEAP          | | (SSE) |  +--------+--------+  |       |  +------------------+  |
    | | Custom Agent  | |       |           |           |       |                        |
    | +---------------+ |       |           v           | HTTPS |  +------------------+  |
    |                   |       |  +-----------------+  |<----->|  | FDA openFDA      |  |
    +-------------------+       |  | Cloud Run       |  |       |  +------------------+  |
                                |  | (MCP Servers)   |  |       |                        |
                                |  |   + Rate Limit  |  |       |  +------------------+  |
                                |  |   + Caching     |  |       |  | CMS / Socrata    |  |
                                |  |   + Retry       |  |       |  +------------------+  |
                                |  +-----------------+  |       |                        |
                                |                       |       |                        |
                                +-----------------------+       +------------------------+
```

All Python servers follow the same internal pattern:
- **Transport**: Streamable HTTP (stateless) via `FastMCP` — horizontally scalable.
- **Rate limiting**: Per-API token bucket to stay within upstream government limits.
- **Caching**: TTL-based (15m for searches, 1–24h for static data, 7d for terminology).
- **Retry**: Exponential backoff on 429/503 HTTP errors (max 3 attempts).
- **Health check**: `GET /health` available on every server.
- **Response format**: All tools support both `markdown` (default) and `json` via the `response_format` parameter.

---

## Servers Catalog

| # | Server | Source APIs | Tools | Auth |
|---|--------|------------|-------|------|
| 1 | [rxnorm_mcp](./rxnorm_mcp/) | [RxNorm](https://rxnav.nlm.nih.gov/), [RxClass](https://rxnav.nlm.nih.gov/RxClassAPIs.html), [DailyMed](https://dailymed.nlm.nih.gov/dailymed/), [MED-RT](https://evs.nci.nih.gov/ftp1/MED-RT/) | 7 | None |
| 2 | [clinical_trials_mcp](./clinical_trials_mcp/) | [ClinicalTrials.gov v2](https://clinicaltrials.gov/data-api/about-api) | 10 | None |
| 3 | [pubmed_mcp](./pubmed_mcp/) | [E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/), [PMC](https://www.ncbi.nlm.nih.gov/pmc/), [PubTator3](https://www.ncbi.nlm.nih.gov/research/pubtator3/) | 12 | NCBI key (server-side) |
| 4 | [fda_safety_mcp](./fda_safety_mcp/) | [openFDA](https://open.fda.gov/) (FAERS, MAUDE, 510k) | 6 | FDA key (server-side) |
| 5 | [drug_data_mcp](./drug_data_mcp/) | [NADAC](https://data.medicaid.gov/dataset/dfa2ab14-06c2-457a-9e36-5cb6d80f8d93), Part D, SDUD, Drug Rebate (CMS) | 8 | None |
| 6 | [umls_mcp](./umls_mcp/) | [UMLS REST](https://documentation.uts.nlm.nih.gov/rest/home.html) (100+ vocabularies, crosswalks) | 10 | UMLS key (user-provided) |
| 7 | [icd10_mcp](./icd10_mcp/) | [ICD-10-CM/PCS](https://www.cms.gov/medicare/coding-billing/icd-10-codes) FY2026 (bundled) | 9 | None |
| 8 | [npi_mcp](./npi_mcp/) | [NPPES NPI Registry](https://npiregistry.cms.hhs.gov/) | 4 | None |
| 9 | [cms_coverage_mcp](./cms_coverage_mcp/) | [CMS Medicare Coverage Database](https://www.cms.gov/medicare-coverage-database) | 5 | None |
| 10 | [medlineplus_mcp](./medlineplus_mcp/) | [MedlinePlus](https://medlineplus.gov/) Connect + Web Service | 5 | None |

---

## Quick Start (Local)

**Prerequisites:** Python 3.10+

Each server can be run independently for local development or testing:

```bash
python3 -m venv .venv && source .venv/bin/activate
cd rxnorm_mcp
pip install -r requirements.txt
python server.py
```

The server starts on port 8080. 
- MCP Endpoint: `http://localhost:8080/mcp`
- Health Check: `http://localhost:8080/health`

> **Note on `icd10_mcp`:** This server downloads CMS code files at Docker build time. To run it locally, first download the data. See [icd10_mcp/README.md](./icd10_mcp/README.md) for instructions.

---

## Cloud Run Deployment

Pushing to the `main` branch automatically builds all server images and deploys them to Cloud Run via Cloud Build and Terraform.

### Prerequisites

- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated (`gcloud auth login`).
- A GitHub repository connected to Cloud Build ([instructions](https://console.cloud.google.com/cloud-build/repositories)).
- A Google Cloud Project with billing enabled.

### First-Time Setup

Run the setup script once to create all GCP infrastructure and the GitHub trigger:

```bash
cd deploy
chmod +x setup.sh
./setup.sh YOUR_PROJECT_ID YOUR_GITHUB_OWNER/REPO
```

This will:
1. Enable required GCP APIs (Cloud Run, Cloud Build, Artifact Registry, Storage).
2. Create an Artifact Registry Docker repo (`healthcare-mcp`).
3. Create a GCS bucket for Terraform state.
4. Grant Cloud Build the necessary IAM roles.
5. Create a Cloud Build trigger for pushes to `main`.
6. Run the initial build and deploy all servers.

### Continuous Deployment

After setup, simply push your code:

```bash
git add . && git commit -m "update configuration" && git push
```

Cloud Build triggers automatically. All servers will rebuild and redeploy. 
If you need to trigger a build manually without pushing, run `./deploy/redeploy.sh`.

### Adding a New Server or Modifying Defaults

To keep the base repository clean, use a custom `.tfvars` file to define new servers or override default settings (like `auth_mode`).

1. Build your server in a new directory (e.g., `my_custom_mcp/`).
2. Add a Docker build step and append the image to the push list in `deploy/cloudbuild.yaml`.
3. Create a custom variables file, e.g., `deploy/terraform/custom.tfvars` (add this to `.gitignore`):
   ```hcl
   servers = {
     "my-custom-mcp" = {
       image_name    = "my-custom-mcp"
       auth_mode     = "public" # or "iam"
       env_vars      = {}
       min_instances = 0
       max_instances = 1
       memory        = "512Mi"
       cpu           = "1"
     }
   }
   ```
4. Deploy using the `_TFVARS_FILE` parameter:
   ```bash
   gcloud builds submit --config=deploy/cloudbuild.yaml --substitutions=_TFVARS_FILE="deploy/terraform/custom.tfvars" .
   ```

### Teardown

To remove all deployed resources from your GCP project:

```bash
cd deploy
./teardown.sh YOUR_PROJECT_ID
```

*(This deletes all Cloud Run services, the Artifact Registry repo, Cloud Build trigger, service account, and Terraform state bucket. Requires confirmation before proceeding.)*

---

## Security & Authentication

The deploy pipeline supports two authentication modes, controlled **per-server** in your Terraform configuration:

| Mode | Protection Level | Best For |
|------|------------------|----------|
| `iam` (Default) | IAM-protected (`roles/run.invoker`) | Production, shared enterprise projects |
| `public` | Open to anyone with the URL | Demos, testing, isolated dev environments |

> **Note:** IAM authentication is strongly recommended for all production deployments. Public access should only be enabled after a thorough risk assessment confirms it is appropriate for the specific server and use case. While these servers query publicly available data sources, open endpoints can expose query patterns, enable abuse of upstream APIs, and create unintended data disclosure risks depending on the context in which they are deployed. Customers should follow [IAM best practices](https://cloud.google.com/iam/docs/using-iam-securely) to restrict access to authorized users and service accounts only.

### Concurrent Public & Private Deployments

You can deploy the same server in both Public and Private modes concurrently by defining two entries in a custom `servers` map (e.g., `deploy/terraform/dual.tfvars`) with distinct names:

```hcl
  "clinical-trials-public" = {
    image_name    = "clinical-trials-mcp"
    auth_mode     = "public"
  }
  "clinical-trials-private" = {
    image_name    = "clinical-trials-mcp"
    auth_mode     = "iam"
  }
```

Deploy using:
```bash
gcloud builds submit --config=deploy/cloudbuild.yaml --substitutions=_TFVARS_FILE="deploy/terraform/dual.tfvars" .
```

### Additional Security Features
- **IAP support**: Optional [Identity-Aware Proxy](https://cloud.google.com/iap) for context-aware access control (IAM mode only).
- **Secrets Management**: API keys (NCBI, UMLS, openFDA) can be stored in [Google Secret Manager](https://cloud.google.com/secret-manager) and injected as environment variables at runtime.
- **No Data Egress**: Servers call public government APIs and return results directly to your agent. No intermediary telemetry or logging services are used.
- **UMLS API Key Logging**: The `umls_mcp` server supports per-user UMLS API keys passed as a URL query parameter. Because these keys are tied to individual NLM accounts, they can appear in Cloud Run request logs. See [umls_mcp/README.md](./umls_mcp/README.md#configuring-cloud-logging-to-protect-api-keys) for instructions on configuring Cloud Logging exclusion filters to prevent this.

### Managing Cloud Run Logs

Cloud Run automatically logs all inbound HTTP requests, including the full request URL with any query parameters. Depending on how your agents or end-users invoke these servers, query parameters — such as search terms, medical codes, or provider identifiers — may appear in your Cloud Logging logs. If your deployment handles sensitive data, you should review and configure your logging accordingly.

**Disable request logging entirely** (if logs are not needed):
```bash
gcloud run services update SERVICE_NAME \
  --clear-custom-audiences \
  --no-traffic \
  --region=YOUR_REGION \
  --project=YOUR_PROJECT_ID
```
See [Cloud Run logging documentation](https://cloud.google.com/run/docs/logging) for full options.

**Exclude specific query parameters from logs** using a Cloud Logging exclusion filter on the `_Default` sink. For example, to exclude any request containing a `umls_key` parameter:
```bash
gcloud logging sinks update _Default \
  --add-exclusion='name=exclude-sensitive-params,filter=resource.type="cloud_run_revision" AND httpRequest.requestUrl=~"umls_key="' \
  --project=YOUR_PROJECT_ID
```
Adjust the filter to match any other parameters relevant to your deployment. See [umls_mcp/README.md](./umls_mcp/README.md#configuring-cloud-logging-to-protect-api-keys) for a detailed walkthrough including Console-based instructions.

**Set a shorter log retention period** to limit how long request logs are stored. The default `_Default` bucket retains logs for 30 days; this can be reduced via the [Log Router](https://console.cloud.google.com/logs/router) in the Google Cloud Console.

---

## Connecting Clients

### Public Mode (`auth_mode=public`)

All Cloud Run service URLs are directly accessible. Connect any MCP client to `https://SERVICE-URL/mcp`:
- **[Antigravity](https://developers.googleblog.com/build-with-google-antigravity-our-new-agentic-development-platform/)** — Add the service URL to your `mcp_config.json` ([Antigravity MCP docs](https://antigravity.google/docs/mcp)).
- **[Gemini Enterprise](https://cloud.google.com/products/gemini)** — Use the service URL as a custom MCP server.
- **[Gemini CLI](https://github.com/google-gemini/gemini-cli)** — `gemini mcp add rxnorm-mcp --url https://rxnorm-mcp-YOUR_HASH.run.app/mcp`
- **Any MCP client** — Connect directly over Streamable HTTP.

### IAM Mode (`auth_mode=iam`, Default)

Services require Cloud IAM authentication (`roles/run.invoker`). Connect directly to the Cloud Run service URLs. Append `/mcp` to the service URL.

- **[Gemini Enterprise](https://cloud.google.com/products/gemini) / [Antigravity](https://developers.googleblog.com/build-with-google-antigravity-our-new-agentic-development-platform/)** — Use the direct service URL if your client supports native OIDC auth scopes.
- **Local / CLI Clients** — For local development environments where native OIDC header injection is not yet supported, use the provided Python bridge scripts in the `scripts/` directory to wrap the connection as a standard `stdio` server while injecting your `gcloud` identity tokens.

```bash
# Example for Antigravity: Add to your mcp_config.json
"python3 scripts/antigravity_bridge.py https://SERVICE-URL/mcp"

# Example for Gemini CLI:
gemini mcp add rxnorm-mcp "python scripts/gemini_cli_bridge.py https://rxnorm-mcp-YOUR_HASH.run.app/mcp"
```

> [!NOTE]
> **Workaround Notice**: The Python bridge scripts (`antigravity_bridge.py` and `gemini_cli_bridge.py`) are temporary convenience wrappers that translate local `stdio` to remote `SSE` while injecting your `gcloud` identity tokens. These can be deprecated once native remote OIDC authentication is supported natively in the client platforms.

- **[GEAP](https://cloud.google.com/vertex-ai) / Other Google Auth clients** — Connect directly to the Cloud Run service URLs. Append `/mcp` to the service URL.

### Local Development

Run any server locally — no auth needed:

```bash
cd rxnorm_mcp && python server.py
# Connect your client to http://localhost:8080/mcp
```

*Note:* `umls_mcp` additionally requires a free UMLS API key provided via URL query parameter. See [umls_mcp/README.md](./umls_mcp/README.md) for details.

---

## Testing

Smoke tests verify health checks, MCP handshakes, and run one tool call per server.

```bash
pip install -r tests/requirements.txt

# Test locally (starts each server, runs checks, stops it)
pytest tests/smoke_test.py -v

# Test deployed Cloud Run services
pytest tests/smoke_test.py -v --cloud --project=YOUR_PROJECT_ID

# Include UMLS tests (requires free API key from https://uts.nlm.nih.gov/)
UMLS_API_KEY=your-key pytest tests/smoke_test.py -v
```

---

## Compliance & Support

**Disclaimer:** This is not an officially supported Google product. This repository is provided "as-is" as a set of developer examples. **There are no Service Level Agreements (SLAs) for response times or bug fixes.**

If you encounter issues, please open an issue on GitHub. Contributions are welcome; please see [`CONTRIBUTING.md`](./CONTRIBUTING.md) for guidelines.

These servers are deployed and operated within your own Google Cloud tenant. Ensuring compliance with your organization's policies and any applicable regulatory requirements is the responsibility of the deploying organization. Google Cloud's [shared responsibility model](https://cloud.google.com/architecture/framework/security/shared-responsibility-shared-fate) applies.

**Regarding PHI and HIPAA:** While these servers provide access to public healthcare data sources, the queries made through them may become sensitive depending on the context in which they are used. For example, querying drug interactions in the context of a specific patient's medications could constitute Protected Health Information (PHI) under HIPAA. Customers are solely responsible for ensuring their use of these tools complies with all applicable privacy regulations, including HIPAA, based on their specific use case and the nature of the data being processed by their agents or end-users. Google's [HIPAA Compliance on Google Cloud](https://cloud.google.com/security/compliance/hipaa) guide outlines the shared responsibility model and customer obligations for applications built on GCP. Customers should also review the [Google Cloud Privacy Notice](https://cloud.google.com/terms/cloud-privacy-notice) and the [Cloud Data Processing Addendum](https://cloud.google.com/terms/data-processing-addendum), which describe how Google processes data within GCP and outline customer responsibilities as a data controller.

## License

[Apache 2.0](./LICENSE)