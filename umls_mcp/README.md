# umls_mcp

MCP server wrapping the UMLS REST API for cross-vocabulary mapping, concept lookup, and relationship traversal across 100+ biomedical terminologies.

## Prerequisites: Get a UMLS API Key (Free)

Unlike the other servers in this portfolio, `umls_mcp` requires each user to have their own UMLS API key. The key is free and takes about 2 minutes to set up.

**Step 1:** Go to [https://uts.nlm.nih.gov/uts/signup-login](https://uts.nlm.nih.gov/uts/signup-login) and create a free account (or sign in with an existing NIH Login).

**Step 2:** Once logged in, go to [My Profile](https://uts.nlm.nih.gov/uts/profile) and copy your **API Key** (a UUID like `20db4a09-955f-435c-8587-6b0215eeeebb`).

**Step 3:** Keep this key — you'll need it when connecting to the server.

## How Authentication Works

The server supports two ways to provide your UMLS API key:

### Option A: Environment variable (recommended)

If you deploy your own instance, set the key as an environment variable. The key never appears in request URLs or logs.

```bash
UMLS_API_KEY=your-key-here
```

### Option B: Query parameter on the MCP URL

Append `?umls_key=YOUR_KEY` to the server URL when adding the connector. Use this for shared deployments where one server serves many users and each user provides their own key.

```
https://your-cloud-run-url/mcp?umls_key=YOUR_KEY
```

**Note:** When using this option, the UMLS API key appears in Cloud Run request logs. Because the key is tied to an individual NLM user account, this links queries to a specific person. See [Configuring Cloud Logging to Protect API Keys](#configuring-cloud-logging-to-protect-api-keys) below.

If both are provided, the query parameter takes priority.

## Connecting to the Server from MCP clients

**Note:** Your API key is sent as a URL query parameter to the Cloud Run server. The server forwards it to the UMLS API and does not store it. Cloud Run request logs may contain the URL — if you control the deployment, you can disable request logging.


The same URL pattern works with any MCP client that supports Streamable HTTP:

```
https://<your-cloud-run-url>/mcp?umls_key=YOUR_UMLS_API_KEY
```

## Vocabularies

UMLS integrates 100+ source vocabularies. Common abbreviations used with this server:

| Abbreviation | Vocabulary |
|-------------|-----------|
| SNOMEDCT_US | SNOMED CT (US Edition) |
| ICD10CM | ICD-10-CM (Diagnoses) |
| ICD10PCS | ICD-10-PCS (Procedures) |
| LOINC | Logical Observation Identifiers |
| RXNORM | RxNorm (Drugs) |
| CPT | Current Procedural Terminology |
| MSH | MeSH (Medical Subject Headings) |
| HCPCS | HCPCS (CMS procedure codes) |
| NCI | NCI Thesaurus |
| HPO | Human Phenotype Ontology |

## Tools (10)

| # | Tool | Description |
|---|------|-------------|
| 1 | `search_concepts` | Free-text search for UMLS concepts with vocabulary and search type filters |
| 2 | `get_concept` | Full concept details by CUI (name, semantic types, atom count) |
| 3 | `get_definitions` | All definitions of a concept from every vocabulary that defines it |
| 4 | `get_relations` | Relationships to other concepts (broader, narrower, related, etc.) |
| 5 | `get_atoms` | All source terms (atoms) for a concept, filterable by vocabulary |
| 6 | `crosswalk` | Map a code from one vocabulary to equivalent codes in others (e.g., SNOMED → ICD-10) |
| 7 | `get_hierarchy` | Navigate parents, children, or ancestors within a vocabulary's hierarchy |
| 8 | `resolve_source_code` | Given a source code (e.g., ICD-10 E11.65), get its UMLS concept info |
| 9 | `get_semantic_types` | List or look up semantic types (Disease, Drug, Procedure, etc.) |
| 10 | `compare_concepts` | Side-by-side comparison of two CUIs (shared types, vocabularies, relations) |

## Deploy to Cloud Run

```bash
cd umls_mcp
gcloud run deploy umls-mcp --source . --port 8080 --allow-unauthenticated
```

For shared deployments, do **not** set `UMLS_API_KEY` as an env var — each user passes their own key via the URL. For personal use, you can optionally set it:

```bash
gcloud run deploy umls-mcp --source . --port 8080 --allow-unauthenticated \
  --set-env-vars UMLS_API_KEY=your-key-here
```

## Run Locally

```bash
export UMLS_API_KEY=your-key-here
pip install -r requirements.txt
python server.py
```

The server starts on port 8080 (override with `PORT` env var). MCP endpoint at `/mcp`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | No | Server port (default: 8080) |
| `UMLS_API_KEY` | No | Fallback API key if not provided via URL query parameter |

## Security Notes

- Each user's API key is passed as a URL query parameter (`?umls_key=...`). This is less secure than OAuth but is the only option given that Claude's connector UI does not support custom headers and UMLS does not offer an OAuth authorization server.
- The server does not store or log API keys. However, Cloud Run infrastructure logs may capture request URLs. Use the environment variable option where possible, or follow the [Cloud Logging exclusion instructions](#configuring-cloud-logging-to-protect-api-keys) below to prevent keys from being stored in logs.
- UMLS API keys are free and non-financial. If a key is compromised, the user can regenerate a new one from their UMLS profile.
- For production deployments serving many users, consider placing the server behind an API gateway with OAuth support as a future enhancement.

## Configuring Cloud Logging to Protect API Keys

If you are using Option B (query parameter), the `umls_key` value will appear in Cloud Run request URLs and will be captured in Cloud Logging by default. Because UMLS API keys are tied to individual NLM user accounts, their presence in logs links specific queries to a specific person. Configure a Cloud Logging exclusion filter to prevent these log entries from being stored.

**Recommended:** Use Option A (environment variable) if you control the deployment — this avoids the issue entirely.

**If you must use the query parameter**, configure the following exclusion filter on your project's `_Default` log sink:

**Via Google Cloud Console:**
1. Go to **Logging → Log Router** in the Google Cloud Console
2. Find the `_Default` sink and click **Edit**
3. Scroll to **"Choose logs to filter out of sink"** and click **Add exclusion**
4. Set the name to `exclude-umls-key` and paste the following filter:
   ```
   resource.type="cloud_run_revision" AND httpRequest.requestUrl=~"umls_key="
   ```
5. Click **Update sink**

**Via gcloud CLI:**
```bash
gcloud logging sinks update _Default \
  --add-exclusion='name=exclude-umls-key,filter=resource.type="cloud_run_revision" AND httpRequest.requestUrl=~"umls_key="' \
  --project=YOUR_PROJECT_ID
```

**Verify the filter is working:** In Logs Explorer, run the query `httpRequest.requestUrl=~"umls_key="` before and after applying the exclusion. After applying, no results should appear for new requests.

## Architecture
