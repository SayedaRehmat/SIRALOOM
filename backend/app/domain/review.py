from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CriterionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern=r"^(ACCEPT|MODIFY|REJECT)$")
    strength: str | None = None
    reason: str = Field(min_length=1, max_length=5000)
    evidence_ids: list[str] = Field(default_factory=list)
    expected_version: int = Field(ge=0)


class ClassificationReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=5000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    analysis_id: str
    variant_id: str
    review_status: str
    classification: dict[str, Any] | None
    criteria: list[dict[str, Any]]
    history: list[dict[str, Any]]
    clinical_context: dict[str, Any] = Field(default_factory=dict)
    clinical_indication: Any | None = None
    phenotypes: list[dict[str, Any]] = Field(default_factory=list)
    variant_context: dict[str, Any] = Field(default_factory=dict)
    inheritance: dict[str, Any] = Field(default_factory=dict)
    pedigree: dict[str, Any] = Field(default_factory=dict)
    reportability: dict[str, Any] | None = None
    confirmation: dict[str, Any] = Field(default_factory=dict)
    follow_up: dict[str, Any] = Field(default_factory=dict)
    secondary_finding: dict[str, Any] = Field(default_factory=dict)
    evidence_count: int = 0
