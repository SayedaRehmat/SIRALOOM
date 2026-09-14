from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

class CanonicalVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    genome_build: str
    chromosome: str
    position: int = Field(gt=0)
    reference: str
    alternate: str
    normalization_status: Literal["UNNORMALIZED", "NORMALIZED"] = "UNNORMALIZED"
    original_chromosome: str | None = None
    original_position: int | None = None
    original_reference: str | None = None
    original_alternate: str | None = None
    variant_key: str | None = None

class CaseCreate(BaseModel):
    case_identifier: str = Field(min_length=1, max_length=200)
    language: Literal["en", "ar", "bilingual"] = "en"
    clinical_context: dict[str, Any] = Field(default_factory=dict)

class ArtifactResponse(BaseModel):
    artifact_id: UUID
    artifact_type: str
    sha256: str
    size_bytes: int
    validation_status: str

class AnalysisCreate(BaseModel):
    analysis_type: str = "VARIANT_INTERPRETATION"
    input_artifact_id: UUID
    assay_id: UUID | None = None
    workflow_id: str = "variant-v1"
    workflow_version: str = "1.0"
    reference_build: str = "GRCh38"
    configuration: dict[str, Any] = Field(default_factory=dict)

class AnalysisResponse(BaseModel):
    analysis_id: UUID
    case_id: UUID
    status: str
    workflow_id: str
    workflow_version: str
    reference_build: str
    created_at: datetime

class PopulationQueryRequest(BaseModel):
    analysis_id: UUID
    variant_ids: list[UUID]
    requested_populations: list[str] = Field(default_factory=lambda: ["GLOBAL", "MID"])

class ACMGReviewRequest(BaseModel):
    decision: Literal["ACCEPT", "MODIFY", "REJECT"]
    strength: str | None = None
    reason: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(default_factory=list)

class ReportCreate(BaseModel):
    report_type: str = "CLINICAL_INTERPRETATION"
    language: Literal["en", "ar", "bilingual"] = "en"
    include_full_evidence: bool = False

class ReportabilityDecisionRequest(BaseModel):
    disposition: Literal["REPORT", "DO_NOT_REPORT", "REVIEW"]
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=5000)

class ExportCreate(BaseModel):
    include_artifacts: bool = True
    include_reports: bool = True
    include_evidence: bool = True
    include_audit: bool = True
    include_provenance: bool = True
