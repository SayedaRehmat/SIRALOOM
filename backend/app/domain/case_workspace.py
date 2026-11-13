from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["en", "ar", "bilingual"] | None = None
    clinical_context: dict[str, Any] | None = None
    execution_environment_registration_id: UUID | None = None


class SpecimenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specimen_identifier: str = Field(min_length=1, max_length=200)
    specimen_type: str | None = Field(default=None, max_length=120)
    collection_datetime: datetime | None = None
    received_datetime: datetime | None = None
    vcf_sample_name: str | None = Field(default=None, min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)



class SpecimenPloidyEvidenceCreate(BaseModel):
    """New immutable specimen copy-number evidence revision."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    reference_build: str = Field(min_length=1, max_length=40)
    status: Literal["VERIFIED", "UNVERIFIED", "CONFLICTED", "MOSAIC_OR_COMPLEX"]
    region_copy_number: dict[str, StrictInt] = Field(default_factory=dict)
    source_type: str | None = Field(default=None, min_length=1, max_length=120)
    evidence_reference: str | None = Field(default=None, min_length=1, max_length=500)
