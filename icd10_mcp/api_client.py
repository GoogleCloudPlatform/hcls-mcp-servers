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
ICD-10 Code Lookup Client

Provides functions for searching and looking up ICD-10-CM (diagnosis) and
ICD-10-PCS (procedure) codes using bundled CMS data files.

Data files are downloaded from CMS at Docker build time and loaded into
memory on server startup for fast lookups.
"""

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Data directory (set by Dockerfile or environment)
DATA_DIR = os.environ.get("ICD10_DATA_DIR", "/app/data")

# In-memory code databases
_cm_codes: Dict[str, "ICD10CMCode"] = {}
_pcs_codes: Dict[str, "ICD10PCSCode"] = {}
_cm_loaded = False
_pcs_loaded = False


@dataclass
class ICD10CMCode:
    """ICD-10-CM diagnosis code."""
    code: str
    short_desc: str
    long_desc: str
    billable: bool
    order: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "short_description": self.short_desc,
            "long_description": self.long_desc,
            "billable": self.billable,
        }


@dataclass
class ICD10PCSCode:
    """ICD-10-PCS procedure code."""
    code: str
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "description": self.description,
            # All PCS codes in the codes file are billable
            "billable": True,
        }


def format_api_error(error: Exception, context: str = "") -> Dict[str, Any]:
    """Format an API error for consistent error responses."""
    return {
        "error": True,
        "message": str(error),
        "context": context,
    }


def _load_cm_codes() -> None:
    """Load ICD-10-CM codes from the CMS order file."""
    global _cm_codes, _cm_loaded
    if _cm_loaded:
        return

    order_file = os.path.join(DATA_DIR, "icd10cm", "icd10cm_order_2026.txt")
    if not os.path.exists(order_file):
        print(f"Warning: ICD-10-CM file not found at {order_file}")
        _cm_loaded = True
        return

    with open(order_file, "r", encoding="utf-8") as f:
        for line in f:
            if len(line) < 15:
                continue
            try:
                # Fixed-width format:
                # Positions 1-5: order number
                # Positions 7-13: code (space-padded)
                # Position 14: billable flag (0/1)
                # Positions 15-74: short description
                # Positions 75+: long description
                order_num = int(line[0:5].strip())
                code = line[6:14].strip()
                billable = line[14] == "1"
                short_desc = line[16:77].strip()
                long_desc = line[77:].strip() if len(line) > 77 else short_desc

                _cm_codes[code.upper()] = ICD10CMCode(
                    code=code,
                    short_desc=short_desc,
                    long_desc=long_desc,
                    billable=billable,
                    order=order_num,
                )
            except (ValueError, IndexError):
                continue

    _cm_loaded = True
    print(f"Loaded {len(_cm_codes)} ICD-10-CM codes")


def _load_pcs_codes() -> None:
    """Load ICD-10-PCS codes from the CMS codes file."""
    global _pcs_codes, _pcs_loaded
    if _pcs_loaded:
        return

    codes_file = os.path.join(DATA_DIR, "icd10pcs", "icd10pcs_codes_2026.txt")
    if not os.path.exists(codes_file):
        print(f"Warning: ICD-10-PCS file not found at {codes_file}")
        _pcs_loaded = True
        return

    with open(codes_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if len(line) < 8:
                continue
            # Format: 7-character code + space + description
            code = line[0:7]
            description = line[8:].strip() if len(line) > 8 else ""

            _pcs_codes[code.upper()] = ICD10PCSCode(
                code=code,
                description=description,
            )

    _pcs_loaded = True
    print(f"Loaded {len(_pcs_codes)} ICD-10-PCS codes")


def ensure_loaded() -> None:
    """Ensure both code sets are loaded."""
    _load_cm_codes()
    _load_pcs_codes()


# ---------------------------------------------------------------------------
# ICD-10-CM Functions
# ---------------------------------------------------------------------------

def search_cm_codes(
    query: str,
    max_results: int = 20,
    billable_only: bool = False,
) -> Dict[str, Any]:
    """
    Search ICD-10-CM codes by keyword.

    Args:
        query: Search term (searches code and descriptions)
        max_results: Maximum results to return
        billable_only: If True, only return billable codes

    Returns:
        Dictionary with matching codes
    """
    ensure_loaded()
    query_upper = query.upper()
    query_words = query_upper.split()
    results = []

    for code, cm_code in _cm_codes.items():
        if billable_only and not cm_code.billable:
            continue

        # Check if query matches code or description
        searchable = f"{code} {cm_code.short_desc} {cm_code.long_desc}".upper()

        # All query words must match
        if all(word in searchable for word in query_words):
            # Score by how early the match appears
            score = 0
            if query_upper in code:
                score = 100  # Exact code match
            elif code.startswith(query_upper):
                score = 90
            elif query_upper in cm_code.short_desc.upper():
                score = 50
            else:
                score = 10

            results.append((score, cm_code))

    # Sort by score descending, then by code
    results.sort(key=lambda x: (-x[0], x[1].code))
    top_results = [r[1].to_dict() for r in results[:max_results]]

    return {
        "query": query,
        "total_results": len(results),
        "returned_results": len(top_results),
        "codes": top_results,
    }


def get_cm_code(code: str) -> Dict[str, Any]:
    """
    Get details for a specific ICD-10-CM code.

    Args:
        code: ICD-10-CM code (e.g., "E11.9")

    Returns:
        Code details or error
    """
    ensure_loaded()
    normalized = code.upper().replace(".", "")

    if normalized in _cm_codes:
        return {"code": _cm_codes[normalized].to_dict()}

    # Try with periods removed
    return {"error": True, "message": f"Code not found: {code}"}


def get_cm_hierarchy(code: str) -> Dict[str, Any]:
    """
    Get parent and child codes for an ICD-10-CM code.

    Args:
        code: ICD-10-CM code

    Returns:
        Dictionary with parent codes and child codes
    """
    ensure_loaded()
    normalized = code.upper().replace(".", "")

    if normalized not in _cm_codes:
        return {"error": True, "message": f"Code not found: {code}"}

    current = _cm_codes[normalized]

    # Find parent codes (shorter prefixes)
    parents = []
    for i in range(len(normalized) - 1, 2, -1):
        prefix = normalized[:i]
        if prefix in _cm_codes:
            parents.append(_cm_codes[prefix].to_dict())

    # Find child codes (longer codes that start with this one)
    children = []
    for c, cm_code in _cm_codes.items():
        if c.startswith(normalized) and c != normalized and len(c) == len(normalized) + 1:
            children.append(cm_code.to_dict())

    # Sort children by code
    children.sort(key=lambda x: x["code"])

    return {
        "code": current.to_dict(),
        "parents": parents,
        "children": children[:50],  # Limit children
    }


def validate_cm_code(code: str) -> Dict[str, Any]:
    """
    Validate an ICD-10-CM code.

    Args:
        code: ICD-10-CM code to validate

    Returns:
        Validation result with billable status and suggestions
    """
    ensure_loaded()
    normalized = code.upper().replace(".", "")

    if normalized not in _cm_codes:
        # Check if it's a partial match
        suggestions = []
        for c in _cm_codes:
            if c.startswith(normalized):
                suggestions.append(_cm_codes[c].to_dict())
                if len(suggestions) >= 5:
                    break

        return {
            "valid": False,
            "code": code,
            "message": "Code not found",
            "suggestions": suggestions,
        }

    cm_code = _cm_codes[normalized]

    # Check if more specific codes exist
    more_specific = []
    if not cm_code.billable:
        for c, child in _cm_codes.items():
            if c.startswith(normalized) and c != normalized and child.billable:
                more_specific.append(child.to_dict())
                if len(more_specific) >= 10:
                    break

    return {
        "valid": True,
        "code": cm_code.to_dict(),
        "billable": cm_code.billable,
        "message": "Valid and billable" if cm_code.billable else "Valid but not billable - use more specific code",
        "more_specific_codes": more_specific if not cm_code.billable else [],
    }


def get_related_cm_codes(code: str, max_results: int = 20) -> Dict[str, Any]:
    """
    Find codes related to a given ICD-10-CM code.

    Returns codes in the same category/subcategory.

    Args:
        code: ICD-10-CM code
        max_results: Maximum results to return

    Returns:
        Related codes in the same category
    """
    ensure_loaded()
    normalized = code.upper().replace(".", "")

    if normalized not in _cm_codes:
        return {"error": True, "message": f"Code not found: {code}"}

    current = _cm_codes[normalized]

    # Find the 3-character category
    category = normalized[:3]

    # Get all codes in the same category
    related = []
    for c, cm_code in _cm_codes.items():
        if c.startswith(category) and c != normalized:
            related.append(cm_code.to_dict())

    # Sort by code
    related.sort(key=lambda x: x["code"])

    return {
        "code": current.to_dict(),
        "category": category,
        "related_codes": related[:max_results],
        "total_in_category": len(related),
    }


def check_cm_specificity(code: str) -> Dict[str, Any]:
    """
    Check if a code needs more specificity.

    Args:
        code: ICD-10-CM code to check

    Returns:
        Specificity analysis with recommendations
    """
    ensure_loaded()
    normalized = code.upper().replace(".", "")

    if normalized not in _cm_codes:
        return {"error": True, "message": f"Code not found: {code}"}

    cm_code = _cm_codes[normalized]
    issues = []
    recommendations = []

    # Check if billable
    if not cm_code.billable:
        issues.append("Code is not billable - it is a category header")

        # Find billable children
        billable_children = []
        for c, child in _cm_codes.items():
            if c.startswith(normalized) and c != normalized and child.billable:
                billable_children.append(child.to_dict())

        if billable_children:
            recommendations.append({
                "issue": "Use a more specific code",
                "options": billable_children[:10],
            })

    # Check for "unspecified" in description
    if "unspecified" in cm_code.long_desc.lower():
        issues.append("Code indicates 'unspecified' - more specific code may exist")

        # Find sibling codes that are more specific
        prefix = normalized[:-1] if len(normalized) > 3 else normalized
        siblings = []
        for c, sibling in _cm_codes.items():
            if (c.startswith(prefix) and c != normalized and
                "unspecified" not in sibling.long_desc.lower() and
                sibling.billable):
                siblings.append(sibling.to_dict())

        if siblings:
            recommendations.append({
                "issue": "Consider more specific alternative",
                "options": siblings[:10],
            })

    return {
        "code": cm_code.to_dict(),
        "billable": cm_code.billable,
        "issues": issues,
        "recommendations": recommendations,
        "passes_specificity": len(issues) == 0,
    }


# ---------------------------------------------------------------------------
# ICD-10-PCS Functions
# ---------------------------------------------------------------------------

def search_pcs_codes(
    query: str,
    max_results: int = 20,
) -> Dict[str, Any]:
    """
    Search ICD-10-PCS procedure codes by keyword.

    Args:
        query: Search term
        max_results: Maximum results to return

    Returns:
        Dictionary with matching procedure codes
    """
    ensure_loaded()
    query_upper = query.upper()
    query_words = query_upper.split()
    results = []

    for code, pcs_code in _pcs_codes.items():
        searchable = f"{code} {pcs_code.description}".upper()

        if all(word in searchable for word in query_words):
            score = 100 if query_upper in code else 10
            results.append((score, pcs_code))

    results.sort(key=lambda x: (-x[0], x[1].code))
    top_results = [r[1].to_dict() for r in results[:max_results]]

    return {
        "query": query,
        "total_results": len(results),
        "returned_results": len(top_results),
        "codes": top_results,
    }


def get_pcs_code(code: str) -> Dict[str, Any]:
    """
    Get details for a specific ICD-10-PCS code.

    Args:
        code: 7-character ICD-10-PCS code

    Returns:
        Code details or error
    """
    ensure_loaded()
    normalized = code.upper()

    if normalized in _pcs_codes:
        pcs = _pcs_codes[normalized]
        result = pcs.to_dict()

        # Parse the 7 characters
        if len(normalized) == 7:
            result["structure"] = {
                "section": normalized[0],
                "body_system": normalized[1],
                "root_operation": normalized[2],
                "body_part": normalized[3],
                "approach": normalized[4],
                "device": normalized[5],
                "qualifier": normalized[6],
            }

        return {"code": result}

    return {"error": True, "message": f"Code not found: {code}"}


def build_pcs_code(
    section: Optional[str] = None,
    body_system: Optional[str] = None,
    root_operation: Optional[str] = None,
    body_part: Optional[str] = None,
    approach: Optional[str] = None,
    device: Optional[str] = None,
    qualifier: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a PCS code interactively by showing valid options for each position.

    Args:
        section: Position 1 - Section (0-9, B-H, X)
        body_system: Position 2 - Body System
        root_operation: Position 3 - Root Operation
        body_part: Position 4 - Body Part
        approach: Position 5 - Approach
        device: Position 6 - Device
        qualifier: Position 7 - Qualifier

    Returns:
        Valid options for the next position, or the final code if complete
    """
    ensure_loaded()

    # Build the partial code from provided values
    parts = [section, body_system, root_operation, body_part, approach, device, qualifier]
    partial = ""
    for p in parts:
        if p is None:
            break
        partial += p.upper()

    if len(partial) == 7:
        # Complete code - validate it
        if partial in _pcs_codes:
            return {
                "complete": True,
                "code": _pcs_codes[partial].to_dict(),
            }
        else:
            return {
                "complete": False,
                "error": f"Code {partial} is not a valid ICD-10-PCS code",
                "partial": partial,
            }

    # Find valid options for the next position
    next_position = len(partial)
    position_names = [
        "section", "body_system", "root_operation", "body_part",
        "approach", "device", "qualifier"
    ]

    valid_chars = set()
    matching_codes = []

    for code, pcs_code in _pcs_codes.items():
        if code.startswith(partial):
            if len(code) > next_position:
                valid_chars.add(code[next_position])
                if len(matching_codes) < 5:
                    matching_codes.append(pcs_code.to_dict())

    return {
        "complete": False,
        "partial_code": partial,
        "next_position": next_position + 1,
        "next_position_name": position_names[next_position],
        "valid_options": sorted(valid_chars),
        "example_codes": matching_codes,
    }


def get_code_counts() -> Dict[str, int]:
    """Get counts of loaded codes."""
    ensure_loaded()
    return {
        "icd10cm_codes": len(_cm_codes),
        "icd10pcs_codes": len(_pcs_codes),
    }
