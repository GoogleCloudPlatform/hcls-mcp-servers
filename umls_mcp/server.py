# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
umls_mcp – MCP server wrapping the UMLS REST API.

Provides cross-vocabulary mapping, concept lookup, relationship traversal,
and semantic type filtering across 100+ biomedical vocabularies.

Authentication: Users supply their own UMLS API key via one of:
  1. Query parameter on the MCP URL:  .../mcp?umls_key=KEY
  2. Environment variable: UMLS_API_KEY  (fallback for self-deployed instances)
"""

import os
import json
from urllib.parse import parse_qs, urlparse
from mcp.server.fastmcp import FastMCP

try:
    from fastmcp.server.dependencies import get_http_request
    HAS_HTTP_REQUEST = True
except ImportError:
    HAS_HTTP_REQUEST = False

import api_client

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "umls_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)

# ---------------------------------------------------------------------------
# API key extraction
# ---------------------------------------------------------------------------

_ENV_KEY = os.environ.get("UMLS_API_KEY", "")


def _get_api_key() -> str:
    """Extract UMLS API key from the HTTP request query string or env var.

    Priority: query param 'umls_key' > env var UMLS_API_KEY.
    """
    if HAS_HTTP_REQUEST:
        try:
            request = get_http_request()
            if request and request.url:
                url_str = str(request.url)
                parsed = urlparse(url_str)
                qs = parse_qs(parsed.query)
                key = qs.get("umls_key", [None])[0]
                if key:
                    return key
        except Exception:
            pass

    if _ENV_KEY:
        return _ENV_KEY

    return ""


def _require_key() -> str:
    """Get API key or raise a helpful error."""
    key = _get_api_key()
    if not key:
        raise ValueError(
            "UMLS API key required. Either append ?umls_key=YOUR_KEY to the MCP URL, "
            "or set the UMLS_API_KEY environment variable. "
            "Get a free key at https://uts.nlm.nih.gov/"
        )
    return key


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok", "server": "umls_mcp"})


# ---------------------------------------------------------------------------
# Tool 1: search_concepts
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_concepts(
    term: str,
    vocabularies: str = "",
    search_type: str = "words",
    page_size: int = 25,
    page_number: int = 1,
) -> str:
    """Search UMLS for concepts matching a free-text term.

    Args:
        term: Search term (e.g., 'diabetes mellitus', 'aspirin', 'chest pain').
        vocabularies: Comma-separated source abbreviations to restrict results
                      (e.g., 'SNOMEDCT_US,ICD10CM,MSH'). Empty = all vocabularies.
                      Common: SNOMEDCT_US, ICD10CM, ICD10PCS, LOINC, RXNORM, CPT, MSH, NDFRT.
        search_type: Search strategy. 'words' (default, any word match), 'exact' (exact string),
                     'normalizedString' (normalized matching), 'normalizedWords'.
        page_size: Results per page (max 200).
        page_number: Page number (starts at 1).

    Returns:
        List of matching concepts with CUI, name, source vocabulary, and semantic types.
    """
    key = _require_key()
    data = await api_client.search(
        key, term,
        sabs=vocabularies or None,
        search_type=search_type,
        page_size=page_size,
        page_number=page_number,
    )
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 2: get_concept
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_concept(cui: str) -> str:
    """Get full details for a UMLS concept by its CUI (Concept Unique Identifier).

    Args:
        cui: UMLS Concept Unique Identifier (e.g., 'C0011849' for diabetes mellitus).

    Returns:
        Concept name, semantic types, atom count, and metadata.
    """
    key = _require_key()
    data = await api_client.get_concept(key, cui)
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 3: get_definitions
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_definitions(cui: str) -> str:
    """Get all definitions of a concept from every vocabulary that defines it.

    Args:
        cui: UMLS CUI (e.g., 'C0011849'). Multiple vocabularies may provide
             different definitions of the same concept.

    Returns:
        List of definitions with their source vocabulary.
    """
    key = _require_key()
    data = await api_client.get_definitions(key, cui)
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 4: get_relations
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_relations(
    cui: str,
    page_size: int = 25,
    page_number: int = 1,
) -> str:
    """Get relationships of a concept to other UMLS concepts.

    Args:
        cui: UMLS CUI (e.g., 'C0011849').
        page_size: Results per page (max 200).
        page_number: Page number (starts at 1).

    Returns:
        Related concepts with relationship type (broader, narrower, related, etc.).
    """
    key = _require_key()
    data = await api_client.get_relations(key, cui, page_size=page_size, page_number=page_number)
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 5: get_atoms
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_atoms(
    cui: str,
    vocabularies: str = "",
    page_size: int = 25,
    page_number: int = 1,
) -> str:
    """Get all atoms (source terms) for a concept across vocabularies.

    An atom is an individual occurrence of a concept name in a specific source
    vocabulary. For example, the concept 'Diabetes Mellitus' (C0011849) has
    atoms in SNOMED CT, ICD-10, MeSH, etc., each with different names/codes.

    Args:
        cui: UMLS CUI (e.g., 'C0011849').
        vocabularies: Comma-separated source abbreviations to filter
                      (e.g., 'SNOMEDCT_US,ICD10CM'). Empty = all vocabularies.
        page_size: Results per page (max 200).
        page_number: Page number (starts at 1).

    Returns:
        List of atoms with source vocabulary, code, and term name.
    """
    key = _require_key()
    data = await api_client.get_atoms(
        key, cui,
        sabs=vocabularies or None,
        page_size=page_size,
        page_number=page_number,
    )
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 6: crosswalk
# ---------------------------------------------------------------------------

@mcp.tool()
async def crosswalk(
    source_vocabulary: str,
    source_code: str,
    target_vocabulary: str = "",
    page_size: int = 25,
    page_number: int = 1,
) -> str:
    """Map a code from one vocabulary to equivalent codes in other vocabularies.

    This is the primary cross-vocabulary mapping tool. For example, map a
    SNOMED CT code to ICD-10-CM, or an ICD-10 code to MeSH.

    Args:
        source_vocabulary: Source vocabulary abbreviation.
            Common values: SNOMEDCT_US, ICD10CM, ICD10PCS, LOINC, RXNORM, CPT, MSH,
            NDFRT, NCI, VANDF, HL7V3.0, HCPCS, GO, OMIM, HPO.
        source_code: Code in the source vocabulary (e.g., '44054006' for SNOMED diabetes,
                     'E11.65' for ICD-10 type 2 diabetes with hyperglycemia).
        target_vocabulary: Target vocabulary to map to (e.g., 'ICD10CM').
                           Empty = return mappings in all available vocabularies.
        page_size: Results per page (max 200).
        page_number: Page number (starts at 1).

    Returns:
        Equivalent codes in target vocabulary(ies) with names and relationship types.
    """
    key = _require_key()
    data = await api_client.crosswalk(
        key,
        source_vocabulary,
        source_code,
        target_source=target_vocabulary or None,
        page_size=page_size,
        page_number=page_number,
    )
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 7: get_hierarchy
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_hierarchy(
    source_vocabulary: str,
    source_code: str,
    direction: str = "children",
) -> str:
    """Navigate the hierarchy of a concept within a specific vocabulary.

    Retrieve parents, children, or ancestors (full path to root) for a code
    in its source vocabulary's hierarchy.

    Args:
        source_vocabulary: Vocabulary abbreviation (e.g., 'SNOMEDCT_US', 'ICD10CM', 'MSH').
        source_code: Code in that vocabulary (e.g., '73211009' for SNOMED diabetes).
        direction: 'children' (immediate children), 'parents' (immediate parents),
                   or 'ancestors' (full path to root).

    Returns:
        List of parent/child/ancestor concepts with codes and names.
    """
    key = _require_key()
    if direction == "parents":
        data = await api_client.get_source_parents(key, source_vocabulary, source_code)
    elif direction == "ancestors":
        data = await api_client.get_source_ancestors(key, source_vocabulary, source_code)
    else:
        data = await api_client.get_source_children(key, source_vocabulary, source_code)
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 8: resolve_source_code
# ---------------------------------------------------------------------------

@mcp.tool()
async def resolve_source_code(
    source_vocabulary: str,
    source_code: str,
) -> str:
    """Look up a source vocabulary code and get its UMLS concept info.

    Given a code from any vocabulary (ICD-10, SNOMED, LOINC, CPT, etc.),
    retrieve its full UMLS mapping including CUI, preferred name, semantic
    types, and all vocabulary memberships.

    Args:
        source_vocabulary: Vocabulary abbreviation.
            Common values: SNOMEDCT_US, ICD10CM, ICD10PCS, LOINC, RXNORM, CPT, MSH,
            HCPCS, NCI, VANDF, GO, OMIM, HPO.
        source_code: Code in that vocabulary (e.g., 'E11.65' for ICD-10-CM,
                     '44054006' for SNOMED CT, '2160-0' for LOINC creatinine).

    Returns:
        UMLS concept info: CUI, preferred name, semantic types, and relations.
    """
    key = _require_key()
    data = await api_client.get_source_concept(key, source_vocabulary, source_code)
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 9: get_semantic_types
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_semantic_types(tui: str = "") -> str:
    """List UMLS semantic types, or get details for a specific type.

    Semantic types categorize every UMLS concept into broad categories like
    'Disease or Syndrome' (T047), 'Pharmacologic Substance' (T121), etc.

    Args:
        tui: Specific TUI to look up (e.g., 'T047' for Disease or Syndrome).
             Empty = list all semantic types.

    Returns:
        Semantic type details (name, TUI, definition, relationships) or full list.
    """
    key = _require_key()
    if tui:
        data = await api_client.get_semantic_type(key, tui)
    else:
        data = await api_client.get_semantic_types_list(key)
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 10: compare_concepts
# ---------------------------------------------------------------------------

@mcp.tool()
async def compare_concepts(cui_1: str, cui_2: str) -> str:
    """Compare two UMLS concepts side by side.

    Retrieves both concepts and their relations, then shows shared semantic
    types, shared relations, and vocabulary overlap.

    Args:
        cui_1: First UMLS CUI (e.g., 'C0011849' for Diabetes Mellitus).
        cui_2: Second UMLS CUI (e.g., 'C0011860' for Diabetes Mellitus, Type 2).

    Returns:
        Side-by-side comparison: names, semantic types, shared relations,
        and vocabulary memberships for both concepts.
    """
    key = _require_key()

    import asyncio
    concept_1, concept_2, rels_1, rels_2, atoms_1, atoms_2 = await asyncio.gather(
        api_client.get_concept(key, cui_1),
        api_client.get_concept(key, cui_2),
        api_client.get_relations(key, cui_1, page_size=50),
        api_client.get_relations(key, cui_2, page_size=50),
        api_client.get_atoms(key, cui_1, page_size=50),
        api_client.get_atoms(key, cui_2, page_size=50),
    )

    # Extract semantic types from concept results
    def _sem_types(concept_data: dict) -> set:
        result = concept_data.get("result", {})
        return {st.get("name", "") for st in result.get("semanticTypes", [])}

    # Extract vocabulary abbreviations from atoms
    def _vocabs(atoms_data: dict) -> set:
        results = atoms_data.get("result", [])
        if isinstance(results, dict):
            results = results.get("results", results)
        if isinstance(results, list):
            return {a.get("rootSource", "") for a in results if isinstance(a, dict)}
        return set()

    # Extract related CUIs
    def _related_cuis(rels_data: dict) -> set:
        results = rels_data.get("result", [])
        if isinstance(results, dict):
            results = results.get("results", results)
        if isinstance(results, list):
            return {r.get("relatedIdName", "") for r in results if isinstance(r, dict)}
        return set()

    st1, st2 = _sem_types(concept_1), _sem_types(concept_2)
    v1, v2 = _vocabs(atoms_1), _vocabs(atoms_2)
    r1, r2 = _related_cuis(rels_1), _related_cuis(rels_2)

    comparison = {
        "concept_1": {
            "cui": cui_1,
            "details": concept_1.get("result", {}),
        },
        "concept_2": {
            "cui": cui_2,
            "details": concept_2.get("result", {}),
        },
        "shared_semantic_types": sorted(st1 & st2),
        "shared_vocabularies": sorted(v1 & v2),
        "shared_related_concepts": sorted(r1 & r2),
        "unique_to_concept_1": {
            "semantic_types": sorted(st1 - st2),
            "vocabularies": sorted(v1 - v2),
        },
        "unique_to_concept_2": {
            "semantic_types": sorted(st2 - st1),
            "vocabularies": sorted(v2 - v1),
        },
    }
    return json.dumps(comparison, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
