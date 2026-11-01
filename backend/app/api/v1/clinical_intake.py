from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth.authorization import CASE_WRITE_ROLES, require_case_permission, require_role
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.case_change import create_case_change_candidates
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    Case,
    ClinicalIntakeRevision,
    PedigreeMember,
    PhenotypeObservation,
    WorkflowStep,
)
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["clinical-intake"])


class AgeAtAssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0)
    unit: Literal["YEARS", "MONTHS", "WEEKS", "DAYS"]
    as_of_date: date | None = None

    @model_validator(mode="after")
    def finite_age(self):
        if not math.isfinite(self.value):
            raise ValueError("age_at_assessment.value must be finite")
        if self.as_of_date is None:
            raise ValueError("age_at_assessment requires the date on which the age was recorded")
        return self


class PriorTestingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_type: str = Field(min_length=1, max_length=200)
    test_type_system: str | None = Field(default=None, max_length=500)
    test_type_code: str | None = Field(default=None, max_length=200)
    test_type_display: str | None = Field(default=None, max_length=500)
    performed_at: date | None = None
    laboratory: str | None = Field(default=None, max_length=300)
    accession_reference: str | None = Field(default=None, max_length=300)
    result_status: Literal[
        "POSITIVE", "NEGATIVE", "INCONCLUSIVE", "PENDING", "NOT_AVAILABLE", "UNKNOWN"
    ] = "UNKNOWN"
    result_summary: str | None = Field(default=None, max_length=5000)
    source_reference: str | None = Field(default=None, max_length=1000)
    artifact_id: UUID | None = None

    @model_validator(mode="after")
    def normalize_prior_test(self):
        self.test_type = self.test_type.strip()
        for name in ("test_type_system", "test_type_code", "test_type_display", "laboratory", "accession_reference", "result_summary", "source_reference"):
            value = getattr(self, name)
            if isinstance(value, str):
                setattr(self, name, value.strip() or None)
        coded_values = (self.test_type_system, self.test_type_code, self.test_type_display)
        if any(coded_values) and not all(coded_values):
            raise ValueError("A coded prior test type requires system URI, code and display")
        if self.test_type_system and not self.test_type_system.startswith(("http://", "https://", "urn:")):
            raise ValueError("Prior-test coding system must be an absolute URI")
        if self.result_status in {"POSITIVE", "NEGATIVE", "INCONCLUSIVE"} and not (
            self.result_summary or self.source_reference or self.artifact_id
        ):
            raise ValueError("Prior-test result requires a result summary or traceable source/artifact reference")
        return self


class DifferentialDiagnosisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str = Field(min_length=3, max_length=500)
    code: str = Field(min_length=1, max_length=200)
    display: str = Field(min_length=1, max_length=1000)
    certainty: Literal["CONFIRMED", "SUSPECTED", "CONSIDERED", "RULED_OUT", "UNKNOWN"] = "CONSIDERED"
    clinical_status: Literal["ACTIVE", "RULED_OUT", "RESOLVED", "UNKNOWN"] = "ACTIVE"

    @model_validator(mode="after")
    def validate_coded_concept(self):
        self.system = self.system.strip()
        self.code = self.code.strip()
        self.display = self.display.strip()
        if not self.system.startswith(("http://", "https://", "urn:")):
            raise ValueError("Differential diagnosis coding system must be an absolute URI")
        if self.certainty == "RULED_OUT" and self.clinical_status != "RULED_OUT":
            raise ValueError("A RULED_OUT differential diagnosis must have clinical_status RULED_OUT")
        if self.clinical_status == "RULED_OUT" and self.certainty != "RULED_OUT":
            raise ValueError("A RULED_OUT clinical status must have certainty RULED_OUT")
        return self


class ClinicalIntakeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intake_status: Literal["DRAFT", "COMPLETE", "NOT_APPLICABLE"] = "DRAFT"
    referral_indication: str | None = Field(default=None, max_length=2000)
    referral_question: str | None = Field(default=None, max_length=5000)
    referral_date: date | None = None
    referring_clinician: str | None = Field(default=None, max_length=300)
    referring_organization: str | None = Field(default=None, max_length=300)
    clinical_service: str | None = Field(default=None, max_length=200)
    clinical_encounter_date: date | None = None
    clinical_summary: str | None = Field(default=None, max_length=15000)
    age_at_assessment: AgeAtAssessmentInput | None = None
    prior_testing: list[PriorTestingInput] = Field(default_factory=list, max_length=100)
    differential_diagnoses: list[DifferentialDiagnosisInput] = Field(default_factory=list, max_length=100)
    source_document_references: list[str] = Field(default_factory=list, max_length=100)
    phenotype_review_status: Literal["COMPLETE", "NOT_ASSESSED", "NOT_APPLICABLE", "PENDING"] = "PENDING"
    family_history_review_status: Literal["COMPLETE", "NOT_ASSESSED", "NOT_APPLICABLE", "PENDING"] = "PENDING"
    phenotype_review_note: str | None = Field(default=None, max_length=5000)
    family_history_review_note: str | None = Field(default=None, max_length=5000)
    completion_note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def validate_intake_attestation(self):
        for field_name in ("referral_indication", "referral_question", "referring_clinician",
                           "referring_organization", "clinical_service", "clinical_summary",
                           "phenotype_review_note", "family_history_review_note", "completion_note"):
            value = getattr(self, field_name)
            if isinstance(value, str):
                setattr(self, field_name, value.strip() or None)
        if self.intake_status == "COMPLETE":
            if not self.referral_indication or not self.referral_question:
                raise ValueError("A complete clinical intake requires referral indication and referral question")
            if self.phenotype_review_status == "PENDING" or self.family_history_review_status == "PENDING":
                raise ValueError("A complete clinical intake requires explicit phenotype and family-history review states")
        if self.phenotype_review_status in {"NOT_ASSESSED", "NOT_APPLICABLE"} and not self.phenotype_review_note:
            raise ValueError("Phenotype NOT_ASSESSED/NOT_APPLICABLE requires a clinical rationale")
        if self.family_history_review_status in {"NOT_ASSESSED", "NOT_APPLICABLE"} and not self.family_history_review_note:
            raise ValueError("Family-history NOT_ASSESSED/NOT_APPLICABLE requires a clinical rationale")
        if self.intake_status == "NOT_APPLICABLE" and not self.completion_note:
            raise ValueError("NOT_APPLICABLE clinical intake requires a documented reason")
        references = [item.strip() for item in self.source_document_references if item.strip()]
        if any(len(item) > 1000 for item in references):
            raise ValueError("Each source document reference must be at most 1000 characters")
        if len(references) != len(set(references)):
            raise ValueError("source_document_references must be unique")
        self.source_document_references = references
        diagnosis_keys = [
            (item.system.casefold(), item.code.casefold())
            for item in self.differential_diagnoses
        ]
        if len(diagnosis_keys) != len(set(diagnosis_keys)):
            raise ValueError("Differential diagnoses must not contain duplicate system/code pairs")
        encoded = json.dumps(self.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 128 * 1024:
            raise ValueError("Clinical intake revision exceeds the 128 KiB structured payload limit")
        return self


def _revision_context(body: ClinicalIntakeInput) -> dict[str, Any]:
    return body.model_dump(mode="json", exclude={
        "intake_status",
        "phenotype_review_status",
        "family_history_review_status",
        "phenotype_review_note",
        "family_history_review_note",
        "completion_note",
    })


def clinical_intake_fingerprint(body: ClinicalIntakeInput, recorded_by: UUID | None = None) -> str:
    material = {
        "recorded_by": str(recorded_by) if recorded_by is not None else None,
        "intake_status": body.intake_status,
        "phenotype_review_status": body.phenotype_review_status,
        "family_history_review_status": body.family_history_review_status,
        "phenotype_review_note": body.phenotype_review_note,
        "family_history_review_note": body.family_history_review_note,
        "completion_note": body.completion_note,
        "context": _revision_context(body),
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _revision_payload(row: ClinicalIntakeRevision) -> dict[str, Any]:
    return {
        "revision_id": str(row.id),
        "case_id": str(row.case_id),
        "version": row.version,
        "schema_version": row.schema_version,
        "revision_fingerprint": row.revision_fingerprint,
        "intake_status": row.intake_status,
        "phenotype_review_status": row.phenotype_review_status,
        "family_history_review_status": row.family_history_review_status,
        "context": row.context or {},
        "phenotype_review_note": row.phenotype_review_note,
        "family_history_review_note": row.family_history_review_note,
        "completion_note": row.completion_note,
        "recorded_by": str(row.recorded_by),
        "recorded_at": row.recorded_at.isoformat(),
    }


def _assert_case_inputs_mutable(db: Session, case: Case) -> None:
    active_analyses = db.scalars(
        select(Analysis).where(
            Analysis.case_id == case.id,
            Analysis.status.in_((
                "CREATED", "QUEUED", "PENDING", "RUNNING", "RETRYING",
                "REQUIRES_REVIEW", "BLOCKED", "RESOURCE_FAILURE", "CANCEL_REQUESTED",
            )),
        )
    ).all()
    for analysis in active_analyses:
        step = db.scalar(
            select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis.id,
                WorkflowStep.step_id == "build_evidence",
            )
        )
        if step is not None and (step.metadata_json or {}).get("clinical_input_snapshot") is not None:
            raise HTTPException(
                409,
                "Clinical context is frozen for an active analysis because its evidence-stage snapshot has already been persisted. Wait for a terminal state before recording a new revision.",
            )


def _validate_review_evidence(db: Session, case: Case, body: ClinicalIntakeInput) -> None:
    probands = db.scalars(
        select(PedigreeMember).where(
            PedigreeMember.case_id == case.id,
            PedigreeMember.is_proband.is_(True),
        )
    ).all()
    if len(probands) > 1:
        raise HTTPException(409, "The case pedigree has multiple probands; resolve pedigree integrity before attesting clinical intake")
    patient_conditions = [
        PhenotypeObservation.case_id == case.id,
        PhenotypeObservation.analysis_id.is_(None),
    ]
    if probands:
        patient_conditions.append(
            (PhenotypeObservation.subject_member_id.is_(None))
            | (PhenotypeObservation.subject_member_id == probands[0].id)
        )
    else:
        patient_conditions.append(PhenotypeObservation.subject_member_id.is_(None))
    patient_feature_count = db.scalar(
        select(func.count()).select_from(PhenotypeObservation).where(*patient_conditions)
    ) or 0
    if (
        body.intake_status == "COMPLETE"
        and body.phenotype_review_status == "COMPLETE"
        and patient_feature_count == 0
        and not body.phenotype_review_note
    ):
        raise HTTPException(
            422,
            "No proband phenotype observations are recorded. Document explicitly that no relevant findings were identified, or record the observed/absent findings before completing phenotype review.",
        )

    family_member_ids = select(PedigreeMember.id).where(
        PedigreeMember.case_id == case.id,
        PedigreeMember.is_proband.is_(False),
    )
    family_feature_count = db.scalar(
        select(func.count()).select_from(PhenotypeObservation).where(
            PhenotypeObservation.case_id == case.id,
            PhenotypeObservation.analysis_id.is_(None),
            PhenotypeObservation.subject_member_id.in_(family_member_ids),
        )
    ) or 0
    if (
        body.intake_status == "COMPLETE"
        and body.family_history_review_status == "COMPLETE"
        and family_feature_count == 0
        and not body.family_history_review_note
    ):
        raise HTTPException(
            422,
            "No family-member phenotype observations are recorded. Document the reviewed family-history conclusion before completing family-history review.",
        )


@router.get("/cases/{case_id}/clinical-intake")
def get_case_clinical_intake(
    case_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "read")
    revisions = db.scalars(
        select(ClinicalIntakeRevision)
        .where(ClinicalIntakeRevision.case_id == case.id)
        .order_by(ClinicalIntakeRevision.version.desc())
        .limit(100)
    ).all()
    return {
        "case_id": str(case.id),
        "latest": _revision_payload(revisions[0]) if revisions else None,
        "revision_count": len(revisions),
        "revisions": [_revision_payload(row) for row in revisions],
        "legacy_clinical_context": case.clinical_context or {},
    }


@router.post("/cases/{case_id}/clinical-intake/revisions", status_code=201)
def create_case_clinical_intake_revision(
    case_id: UUID,
    body: ClinicalIntakeInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = db.get(Case, case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)

    fingerprint = clinical_intake_fingerprint(body, principal.user_id)
    existing = db.scalar(
        select(ClinicalIntakeRevision).where(
            ClinicalIntakeRevision.case_id == case.id,
            ClinicalIntakeRevision.revision_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return _revision_payload(existing)

    _assert_case_inputs_mutable(db, case)
    _validate_review_evidence(db, case, body)
    for test in body.prior_testing:
        if test.artifact_id is not None:
            artifact = db.get(Artifact, test.artifact_id)
            if artifact is None or artifact.case_id != case.id:
                raise HTTPException(400, "Prior-testing artifact must belong to this case")

    current_version = db.scalar(
        select(func.max(ClinicalIntakeRevision.version)).where(
            ClinicalIntakeRevision.case_id == case.id
        )
    ) or 0
    version = int(current_version) + 1
    context = _revision_context(body)
    row = ClinicalIntakeRevision(
        id=uuid4(),
        case_id=case.id,
        version=version,
        schema_version=1,
        revision_fingerprint=fingerprint,
        intake_status=body.intake_status,
        phenotype_review_status=body.phenotype_review_status,
        family_history_review_status=body.family_history_review_status,
        context=context,
        phenotype_review_note=body.phenotype_review_note,
        family_history_review_note=body.family_history_review_note,
        completion_note=body.completion_note,
        recorded_by=principal.user_id,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(ClinicalIntakeRevision).where(
                ClinicalIntakeRevision.case_id == case.id,
                ClinicalIntakeRevision.revision_fingerprint == fingerprint,
            )
        )
        if existing is not None:
            return _revision_payload(existing)
        raise

    case_context = dict(case.clinical_context or {})
    case_context["clinical_intake"] = context
    case_context["clinical_intake_revision"] = {
        "revision_id": str(row.id),
        "version": version,
        "intake_status": body.intake_status,
    }
    case_context["indication"] = body.referral_indication
    case.clinical_context = case_context

    AuditService(db).record(
        event_type="CLINICAL_INTAKE_REVISION_CREATED",
        case_id=case.id,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="CLINICAL_INTAKE_REVISION",
        subject_id=str(row.id),
        operation="CREATE",
        after_state={
            "revision_id": str(row.id),
            "version": version,
            "intake_status": body.intake_status,
            "phenotype_review_status": body.phenotype_review_status,
            "family_history_review_status": body.family_history_review_status,
            "revision_fingerprint": fingerprint,
        },
    )
    create_case_change_candidates(
        db,
        case=case,
        trigger_type="CLINICAL_CONTEXT_UPDATE",
        reason=f"Clinical intake revision {version} was recorded; completed analyses may require reanalysis.",
        metadata={
            "clinical_intake_revision_id": str(row.id),
            "clinical_intake_revision_version": version,
            "intake_status": body.intake_status,
            "revision_fingerprint": fingerprint,
        },
    )
    db.commit()
    return _revision_payload(row)
