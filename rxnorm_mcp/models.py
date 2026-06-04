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
Pydantic v2 input models for all RxNorm & Drug Labels MCP tools.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"


# --- Tool input models ---

class NormalizeDrugInput(BaseModel):
    """Resolve a brand or generic drug name to its RxNorm Concept ID (RxCUI)."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(
        ...,
        description="Drug name to normalize (brand or generic, e.g. 'Lipitor', 'atorvastatin', 'metformin 500mg')",
        min_length=2,
        max_length=200,
    )
    search_type: int = Field(
        default=2,
        description="Search precision: 0=Exact, 1=Normalized, 2=Approximate (default). Approximate is best for user-supplied names.",
        ge=0,
        le=2,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' (human-readable) or 'json' (structured)",
    )



class GetDrugInfoInput(BaseModel):
    """Get ingredients, dosage forms, and NDCs for a drug by RxCUI."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    rxcui: str = Field(
        ...,
        description="RxNorm Concept Unique Identifier (e.g. '161354' for atorvastatin calcium). Use normalize_drug first if you only have a name.",
        min_length=1,
        max_length=20,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("rxcui")
    @classmethod
    def rxcui_must_be_numeric(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("RxCUI must be a numeric string (e.g. '161354')")
        return v



class CheckInteractionsInput(BaseModel):
    """Check known drug-drug interactions for one or more RxCUIs."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    rxcuis: List[str] = Field(
        ...,
        description="One or more RxCUIs to check for interactions (e.g. ['207106', '152923']). Provide ≥2 to check a specific pair, or 1 to see all known interactions for that drug.",
        min_length=1,
        max_length=20,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("rxcuis")
    @classmethod
    def rxcuis_must_be_numeric(cls, v: List[str]) -> List[str]:
        for item in v:
            if not item.strip().isdigit():
                raise ValueError(f"Each RxCUI must be numeric. Got: '{item}'")
        return [item.strip() for item in v]



class DrugClassType(str, Enum):
    """Drug classification category."""
    ALL = "all"
    THERAPEUTIC = "therapeutic"
    MOA = "moa"
    PHARMACOKINETICS = "pk"
    PHYSIOLOGIC_EFFECT = "pe"
    CHEMICAL = "chem"


class GetDrugClassInput(BaseModel):
    """Get therapeutic class, mechanism of action, or pharmacokinetics for a drug."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    rxcui: str = Field(
        ...,
        description="RxCUI of the drug (e.g. '161354'). Use normalize_drug first if you only have a name.",
        min_length=1,
        max_length=20,
    )
    class_type: DrugClassType = Field(
        default=DrugClassType.ALL,
        description="Which classification to return: 'all', 'therapeutic', 'moa', 'pk', 'pe', or 'chem'.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("rxcui")
    @classmethod
    def rxcui_must_be_numeric(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("RxCUI must be a numeric string")
        return v



class GetDrugLabelInput(BaseModel):
    """Get an FDA-approved drug label (SPL) from DailyMed."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    rxcui: Optional[str] = Field(
        default=None,
        description="RxCUI to look up the label for. Provide either rxcui or set_id.",
        max_length=20,
    )
    set_id: Optional[str] = Field(
        default=None,
        description="DailyMed SPL setId (UUID). Provide either rxcui or set_id.",
        max_length=50,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("rxcui")
    @classmethod
    def rxcui_numeric_if_given(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.isdigit():
            raise ValueError("RxCUI must be a numeric string")
        return v



class SearchDrugLabelsInput(BaseModel):
    """Search DailyMed drug labels by name, indication, or boxed warning."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    drug_name: Optional[str] = Field(
        default=None,
        description="Drug name to search (e.g. 'metformin'). At least one search parameter is required.",
        max_length=200,
    )
    boxed_warning: Optional[bool] = Field(
        default=None,
        description="If True, filter to drugs with a boxed (black box) warning.",
    )
    page: int = Field(
        default=1,
        description="Page number for pagination (starts at 1).",
        ge=1,
    )
    page_size: int = Field(
        default=10,
        description="Results per page (max 100).",
        ge=1,
        le=100,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)



class GetIndicationsInput(BaseModel):
    """Get disease-drug indication relationships from MED-RT."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    rxcui: str = Field(
        ...,
        description="RxCUI of the drug (e.g. '161354'). Use normalize_drug first if you only have a name.",
        min_length=1,
        max_length=20,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("rxcui")
    @classmethod
    def rxcui_must_be_numeric(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("RxCUI must be a numeric string")
        return v
