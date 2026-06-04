# icd10_mcp

MCP server for looking up ICD-10-CM diagnosis codes and ICD-10-PCS procedure codes.

## Data Sources

| Source | Description | Update Frequency |
|--------|-------------|------------------|
| [ICD-10-CM](https://www.cms.gov/medicare/coding-billing/icd-10-codes) | ~98,000 diagnosis codes | Annual (October 1) |
| [ICD-10-PCS](https://www.cms.gov/medicare/coding-billing/icd-10-codes) | ~79,000 procedure codes | Annual (October 1) |

**Important:** This server bundles the **FY2026** code sets directly into the Docker image at build time. The data is downloaded from CMS during `docker build` and loaded into memory at runtime. There are no external API calls - all lookups are local.

To update to a new fiscal year, modify the URLs in the `Dockerfile` and rebuild.

### Resources

- **ICD-10-CM Official Guidelines:** https://www.cms.gov/medicare/coding-billing/icd-10-codes
- **ICD-10-CM Browser:** https://www.cdc.gov/nchs/icd/icd-10-cm.htm
- **ICD-10-PCS Reference Manual:** https://www.cms.gov/medicare/coding-billing/icd-10-codes

## Tools (9)

### ICD-10-CM - Diagnosis Codes (7 tools)

| # | Tool | Description |
|---|------|-------------|
| 1 | `search_codes` | Search diagnosis codes by keyword/description |
| 2 | `get_code` | Get full details for a specific code |
| 3 | `get_hierarchy` | Get parent/child codes in the code tree |
| 4 | `validate_code` | Check if a code is valid and billable |
| 5 | `get_related_codes` | Find related codes in the same category |
| 6 | `check_specificity` | Flag codes needing more specificity |

### ICD-10-PCS - Procedure Codes (3 tools)

| # | Tool | Description |
|---|------|-------------|
| 7 | `search_procedures` | Search procedure codes by keyword |
| 8 | `get_procedure` | Get procedure details with code breakdown |
| 9 | `build_pcs_code` | Interactive 7-character code builder |

## Data Version

**Current version: FY2026** (October 1, 2025 - September 30, 2026)

The Dockerfile downloads these files from CMS at build time:
- `https://www.cms.gov/files/zip/2026-code-descriptions-tabular-order.zip` (ICD-10-CM)
- `https://www.cms.gov/files/zip/2026-icd-10-pcs-codes-file.zip` (ICD-10-PCS)

To update to a new year, change the year in the Dockerfile URLs and rebuild the image.

## Quick Start

```bash
cd icd10_mcp
pip install -r requirements.txt

# For local testing, download FY2026 data first:
mkdir -p data/icd10cm data/icd10pcs
curl -Lo data/icd10cm.zip "https://www.cms.gov/files/zip/2026-code-descriptions-tabular-order.zip"
curl -Lo data/icd10pcs.zip "https://www.cms.gov/files/zip/2026-icd-10-pcs-codes-file.zip"
unzip data/icd10cm.zip -d data/icd10cm
unzip data/icd10pcs.zip -d data/icd10pcs

export ICD10_DATA_DIR=./data
python server.py
```

Server starts on port 8080. MCP endpoint at `http://localhost:8080/mcp`.

## Example Queries

### Diagnosis Code Lookup

```python
# Search for diabetes codes
search_codes("type 2 diabetes")

# Get details for a specific code
get_code("E11.9")

# Validate a code for billing
validate_code("E11")
# Returns: "Valid but not billable - use more specific code"

# Check code hierarchy
get_hierarchy("E11")
# Returns parent categories and child codes

# Check specificity requirements
check_specificity("E11.9")
```

### Procedure Code Lookup

```python
# Search for appendectomy procedures
search_procedures("appendectomy")

# Get procedure details with code breakdown
get_procedure("0DTJ4ZZ")

# Build a PCS code step by step
build_pcs_code(section="0")
# Returns valid options for body_system

build_pcs_code(section="0", body_system="D", root_operation="T")
# Returns valid options for body_part
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | No | Server port (default: 8080) |
| `ICD10_DATA_DIR` | No | Path to data files (default: /app/data) |

## Code Structure

### ICD-10-CM Codes
- 3-7 characters (e.g., E11, E11.9, E11.65)
- Category codes (3 chars) are not billable
- Codes with more digits are more specific
- Some codes require 7th character for episode of care

### ICD-10-PCS Codes
- Always exactly 7 characters
- Each position has specific meaning:
  1. Section (Medical/Surgical, Imaging, etc.)
  2. Body System
  3. Root Operation (Excision, Replacement, etc.)
  4. Body Part
  5. Approach (Open, Percutaneous, etc.)
  6. Device
  7. Qualifier

## Architecture
