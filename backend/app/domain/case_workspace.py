from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["en", "ar", "bilingual"] | None = None
    clinical_context: dict[str, Any] | None = None


class SpecimenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specimen_identifier: str = Field(min_length=1, max_length=200)
    specimen_type: str | None = Field(default=None, max_length=120)
    collection_datetime: datetime | None = None
    received_datetime: datetime | None = None
    vcf_sample_name: str | None = Field(default=None, min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
