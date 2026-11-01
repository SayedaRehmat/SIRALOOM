"""Strict API contract for versioned caller/assay ploidy policies."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class CallerPloidyPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    caller_id: str = Field(min_length=1, max_length=200)
    caller_version: str = Field(min_length=1, max_length=120)
    policy_version: str = Field(min_length=1, max_length=120)
    reference_build: str = Field(min_length=1, max_length=40)
    status: Literal["DRAFT", "QUALIFIED", "RETIRED"]
    validation_evidence_reference: str | None = Field(default=None, min_length=1, max_length=500)
    region_copy_number_to_gt_ploidy: dict[str, dict[str, StrictInt | Literal["NOT_CALLABLE"]]] = Field(default_factory=dict)
