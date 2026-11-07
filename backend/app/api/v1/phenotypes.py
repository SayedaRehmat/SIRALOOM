import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    get_accessible_analysis,
    require_case_permission,
    require_role,
)
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.case_change import create_case_change_candidates
from backend.app.domain.clinical_input_snapshot import validate_case_clinical_input_snapshot
from backend.app.domain.provider_registry import ProviderRegistryError, register_builtin_providers
from backend.app.domain.resource_capabilities import CapabilityRequirement, ResourceCapability
from backend.app.domain.resource_execution import ResourceExecutionError, resolve_resource_execution
from backend.app.domain.resource_execution_plan import build_resource_execution_plan
from backend.app.adapters.phenotype.hpo_obo import HPOOntologyError
from backend.app.adapters.phenotype.phenopackets_v2 import PhenopacketExportError, build_phenopackets_v2
from backend.app.adapters.phenotype.fhir_r5 import FHIRExportError, build_fhir_r5_bundle
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    Analysis, Case, ClinicalIntakeRevision, PedigreeMember, PedigreeRelationship,
    PhenotypeObservation, PhenotypeObservationAmendment, WorkflowStep,
)
from backend.app.infrastructure.db.session import get_db
from backend.app.phenotype import normalize_hpo_id

router = APIRouter(tags=["phenotypes"])

_ALLOWED_ATTRIBUTE_KEYS = {
    "onset_age", "onset_age_iso8601", "resolution_age_iso8601",
    "severity_hpo_id", "clinical_course_hpo_id", "modifier_hpo_ids", "laterality",
    "anatomical_site", "temporal_pattern", "episode_frequency",
}
_AGE_UNITS = {"YEARS", "MONTHS", "WEEKS", "DAYS"}
_AGE_COMPARATORS = {"EXACT", "LESS_THAN", "GREATER_THAN", "RANGE"}
_LATERALITY = {"LEFT", "RIGHT", "BILATERAL", "UNILATERAL", "MIDLINE", "NOT_APPLICABLE", "UNKNOWN"}
_TEMPORAL_PATTERNS = {"CONTINUOUS", "EPISODIC", "RECURRENT", "PROGRESSIVE", "REGRESSIVE", "STATIC", "UNKNOWN"}


def _validate_clinical_attributes(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("clinical_attributes must be an object")
    unknown = sorted(set(value) - _ALLOWED_ATTRIBUTE_KEYS)
    if unknown:
        raise ValueError("Unsupported clinical phenotype attributes: " + ", ".join(unknown))
    normalized = dict(value)
    onset_age = normalized.get("onset_age")
    if onset_age is not None:
        if not isinstance(onset_age, dict):
            raise ValueError("onset_age must be an object")
        if set(onset_age) - {"value", "unit", "comparator", "lower_value", "upper_value"}:
            raise ValueError("onset_age contains unsupported fields")
        unit = str(onset_age.get("unit") or "").upper()
        comparator = str(onset_age.get("comparator") or "EXACT").upper()
        if unit not in _AGE_UNITS or comparator not in _AGE_COMPARATORS:
            raise ValueError("onset_age requires a supported unit and comparator")
        if comparator == "RANGE":
            lower, upper = onset_age.get("lower_value"), onset_age.get("upper_value")
            if (
                lower is None or upper is None
                or not math.isfinite(float(lower)) or not math.isfinite(float(upper))
                or float(lower) < 0 or float(upper) < float(lower)
            ):
                raise ValueError("RANGE onset_age requires finite, non-negative ordered lower_value and upper_value")
        else:
            age = onset_age.get("value")
            if age is None or not math.isfinite(float(age)) or float(age) < 0:
                raise ValueError("onset_age requires a finite, non-negative value")
        normalized["onset_age"] = {**onset_age, "unit": unit, "comparator": comparator}
    for time_key in ("onset_age_iso8601", "resolution_age_iso8601"):
        duration = normalized.get(time_key)
        if duration is not None:
            duration = str(duration).strip().upper()
            if not re.fullmatch(
                r"P(?=\d|T\d)(?:\d+(?:\.\d+)?Y)?(?:\d+(?:\.\d+)?M)?(?:\d+(?:\.\d+)?W)?(?:\d+(?:\.\d+)?D)?(?:T(?:\d+(?:\.\d+)?H)?(?:\d+(?:\.\d+)?M)?(?:\d+(?:\.\d+)?S)?)?",
                duration,
            ):
                raise ValueError(f"{time_key} must be an ISO 8601 duration")
            normalized[time_key] = duration
    severity_hpo_id = normalized.get("severity_hpo_id")
    if severity_hpo_id is not None:
        normalized["severity_hpo_id"] = normalize_hpo_id(severity_hpo_id)
    course = normalized.get("clinical_course_hpo_id")
    if course is not None:
        normalized["clinical_course_hpo_id"] = normalize_hpo_id(course)
    modifiers = normalized.get("modifier_hpo_ids", [])
    if not isinstance(modifiers, list) or len(modifiers) > 50:
        raise ValueError("modifier_hpo_ids must be a list containing at most 50 HPO identifiers")
    normalized["modifier_hpo_ids"] = sorted({normalize_hpo_id(item) for item in modifiers})
    if "laterality" in normalized:
        normalized["laterality"] = str(normalized["laterality"]).upper()
        if normalized["laterality"] not in _LATERALITY:
            raise ValueError("Unsupported laterality")
    if "temporal_pattern" in normalized:
        normalized["temporal_pattern"] = str(normalized["temporal_pattern"]).upper()
        if normalized["temporal_pattern"] not in _TEMPORAL_PATTERNS:
            raise ValueError("Unsupported temporal_pattern")
    site = normalized.get("anatomical_site")
    if site is not None:
        if not isinstance(site, dict) or set(site) - {"system", "code", "display"}:
            raise ValueError("anatomical_site must contain only system, code and display")
        if not str(site.get("system") or "").strip() or not str(site.get("code") or "").strip():
            raise ValueError("anatomical_site requires a coding system and code")
    frequency = normalized.get("episode_frequency")
    if frequency is not None:
        if not isinstance(frequency, dict) or set(frequency) - {"count", "period_value", "period_unit"}:
            raise ValueError("episode_frequency must contain count, period_value and period_unit")
        count = frequency.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("episode_frequency count must be a positive integer")
        period_value = float(frequency.get("period_value", 0))
        if not math.isfinite(period_value) or period_value <= 0:
            raise ValueError("episode_frequency requires a finite, positive period_value")
        if str(frequency.get("period_unit") or "").upper() not in {"HOURS", "DAYS", "WEEKS", "MONTHS", "YEARS"}:
            raise ValueError("episode_frequency requires a supported period_unit")
        frequency["period_unit"] = str(frequency["period_unit"]).upper()
    return normalized


class PhenotypeInput(BaseModel):
    hpo_id: str
    label: str | None = Field(default=None, max_length=500)
    phenotype_status: str = "PRESENT"
    present: bool | None = None
    onset: str | None = Field(default=None, max_length=200)
    severity: str | None = Field(default=None, max_length=100)
    subject_member_id: UUID | None = None
    observed_at: datetime | None = None
    clinical_attributes: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="CLINICAL_INPUT", min_length=1, max_length=100)
    evidence: dict = Field(default_factory=dict)
    supersedes_observation_id: UUID | None = None
    amendment_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_presence(cls, values):
        if not isinstance(values, dict):
            return values
        values = dict(values)
        status = values.get("phenotype_status")
        legacy_present = values.get("present")
        if status is None:
            values["phenotype_status"] = "PRESENT" if legacy_present is not False else "ABSENT"
        return values

    @model_validator(mode="after")
    def validate_clinical_record(self):
        from backend.app.phenotype import PHENOTYPE_STATUSES
        self.hpo_id = normalize_hpo_id(self.hpo_id)
        self.phenotype_status = self.phenotype_status.strip().upper()
        if self.phenotype_status not in PHENOTYPE_STATUSES:
            raise ValueError("Unsupported phenotype_status")
        if self.present is not None and self.present != (self.phenotype_status == "PRESENT"):
            raise ValueError("phenotype_status conflicts with legacy present flag")
        self.clinical_attributes = _validate_clinical_attributes(self.clinical_attributes)
        if self.amendment_reason is not None:
            self.amendment_reason = self.amendment_reason.strip() or None
        if self.supersedes_observation_id is not None and not self.amendment_reason:
            raise ValueError("Superseding a phenotype observation requires a documented correction reason")
        if self.supersedes_observation_id is None and self.amendment_reason:
            raise ValueError("amendment_reason is valid only when supersedes_observation_id is supplied")
        return self


class PhenotypeRetractionInput(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def normalize_reason(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("A clinical retraction reason is required")
        return self


def _hpo_runtime(db: Session, case: Case):
    """Resolve only an organization-approved, technically qualified HPO resource."""
    plan = build_resource_execution_plan(
        db,
        organization_id=case.organization_id,
        requirements=(CapabilityRequirement(ResourceCapability.PHENOTYPE),),
    )
    candidates = [
        item for item in plan.for_capability(ResourceCapability.PHENOTYPE)
        if item.resource.provider == "HPO"
    ]
    if len(candidates) != 1:
        return None, None, None
    item = candidates[0]
    execution = resolve_resource_execution(db, resource=item.resource)
    implementation = register_builtin_providers().require(
        provider_id="HPO",
        provider_version=execution.contract.provider_version,
    )
    ontology = implementation.factory(execution.contract)
    if item.resource.version != ontology.release:
        raise HPOOntologyError("HPO resource version does not match the release declared by its OBO artifact")
    checksum = str(item.resource.checksum or "").lower().removeprefix("sha256:")
    contract_checksum = str(
        (execution.contract.toolchain or {}).get("sha256")
        or (execution.contract.toolchain or {}).get("checksum")
        or ""
    ).lower().removeprefix("sha256:")
    if not checksum or checksum != contract_checksum or checksum != ontology.sha256:
        raise HPOOntologyError("HPO resource checksum does not match its qualified execution contract")
    return item.resource, execution, ontology


def _phenotype_record_fingerprint(body: PhenotypeInput) -> str:
    """Stable idempotency key for one clinical observation, not for a term/status pair."""
    identity = {
        "hpo_id": body.hpo_id,
        "phenotype_status": body.phenotype_status,
        "subject_member_id": str(body.subject_member_id) if body.subject_member_id else None,
        "observed_at": body.observed_at.isoformat() if body.observed_at else None,
        "label": body.label,
        "onset": body.onset,
        "severity": body.severity,
        "clinical_attributes": body.clinical_attributes,
        "source": body.source,
        "evidence": body.evidence,
        "supersedes_observation_id": str(body.supersedes_observation_id) if body.supersedes_observation_id else None,
        "amendment_reason": body.amendment_reason,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_term(ontology, term_id: str) -> dict[str, Any]:
    if ontology is None:
        return {"input_id": term_id, "status": "ONTOLOGY_UNAVAILABLE"}
    result = ontology.resolve(term_id)
    return {
        "input_id": term_id,
        "status": result.status,
        "canonical_id": result.canonical_id,
        "label": result.label,
        "replacement_candidates": list(result.replacement_candidates),
        "consider": list(result.consider),
        "ambiguous_candidates": list(result.ambiguous_candidates),
    }


def _resolution_bundle(db: Session, case: Case, body: PhenotypeInput):
    try:
        resource, execution, ontology = _hpo_runtime(db, case)
    except (ResourceExecutionError, ProviderRegistryError, HPOOntologyError, ValueError):
        resource = execution = ontology = None
    terms = [body.hpo_id]
    terms.extend(body.clinical_attributes.get("modifier_hpo_ids", []))
    severity = body.clinical_attributes.get("severity_hpo_id")
    if severity:
        terms.append(severity)
    course = body.clinical_attributes.get("clinical_course_hpo_id")
    if course:
        terms.append(course)
    resolved = {term: _resolve_term(ontology, term) for term in sorted(set(terms))}
    primary = resolved[body.hpo_id]
    canonical = (
        primary.get("canonical_id")
        if primary.get("status") in {"CURRENT", "ALTERNATE_ID"}
        else None
    )
    return canonical, {
        "schema_version": 1,
        "primary_term": primary,
        "related_terms": [resolved[term] for term in sorted(set(terms)) if term != body.hpo_id],
        "resource": ({
            "resource_id": str(resource.id),
            "resource_name": resource.name,
            "resource_version": resource.version,
            "resource_checksum": resource.checksum,
            "qualification_id": str(execution.qualification_id),
            "qualification_version": execution.qualification_version,
            "contract_hash": execution.contract_hash,
            "ontology_release": ontology.release,
            "ontology_sha256": ontology.sha256,
        } if resource is not None and execution is not None and ontology is not None else None),
    }




def _amendment_fingerprint(
    case_id: UUID, observation_id: UUID, replacement_observation_id: UUID | None,
    amendment_type: str, reason: str, recorded_by: UUID,
) -> str:
    material = {
        "case_id": str(case_id),
        "observation_id": str(observation_id),
        "replacement_observation_id": str(replacement_observation_id) if replacement_observation_id else None,
        "amendment_type": amendment_type,
        "reason": reason,
        "recorded_by": str(recorded_by),
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _amendment_payload(row: PhenotypeObservationAmendment) -> dict[str, Any]:
    return {
        "amendment_id": str(row.id),
        "case_id": str(row.case_id),
        "observation_id": str(row.observation_id),
        "replacement_observation_id": str(row.replacement_observation_id) if row.replacement_observation_id else None,
        "amendment_type": row.amendment_type,
        "reason": row.reason,
        "recorded_by": str(row.recorded_by),
        "recorded_at": row.recorded_at.isoformat(),
    }


def _payload(row, amendment: PhenotypeObservationAmendment | None = None):
    legacy_present = (
        True if row.phenotype_status == "PRESENT"
        else False if row.phenotype_status in {"ABSENT", "EXCLUDED"}
        else None
    )
    return {
        "phenotype_id": str(row.id),
        "case_id": str(row.case_id),
        "analysis_id": str(row.analysis_id) if row.analysis_id else None,
        "subject_member_id": str(row.subject_member_id) if row.subject_member_id else None,
        "hpo_id": row.hpo_id,
        "canonical_hpo_id": row.canonical_hpo_id,
        "label": row.label,
        "present": legacy_present,
        "phenotype_status": row.phenotype_status,
        "onset": row.onset,
        "severity": row.severity,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "clinical_attributes": row.clinical_attributes or {},
        "ontology_resolution": row.ontology_resolution or {},
        "source": row.source,
        "evidence": row.evidence or {},
        "created_at": row.created_at.isoformat(),
        "record_lifecycle_status": amendment.amendment_type if amendment else "ACTIVE",
        "amendment_id": str(amendment.id) if amendment else None,
        "amendment_reason": amendment.reason if amendment else None,
        "replacement_observation_id": str(amendment.replacement_observation_id) if amendment and amendment.replacement_observation_id else None,
        "amendment_recorded_by": str(amendment.recorded_by) if amendment else None,
        "amendment_recorded_at": amendment.recorded_at.isoformat() if amendment else None,
    }


@router.get("/cases/{case_id}/phenotype-terms")
def search_case_phenotype_terms(
    case_id: UUID,
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "read")
    try:
        resource, execution, ontology = _hpo_runtime(db, case)
    except (ResourceExecutionError, ProviderRegistryError, HPOOntologyError, ValueError):
        resource = execution = ontology = None
    if ontology is None:
        return {
            "availability": "UNAVAILABLE",
            "reason": "NO_SINGLE_APPROVED_AND_QUALIFIED_HPO_RESOURCE",
            "terms": [],
        }
    return {
        "availability": "AVAILABLE",
        "resource": {
            "resource_id": str(resource.id),
            "resource_version": resource.version,
            "ontology_release": ontology.release,
            "ontology_sha256": ontology.sha256,
            "qualification_id": str(execution.qualification_id),
            "contract_hash": execution.contract_hash,
        },
        "terms": ontology.search_terms(q, limit=limit),
    }


@router.get("/cases/{case_id}/phenotypes")
def list_case_phenotypes(
    case_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "read")
    rows = db.scalars(
        select(PhenotypeObservation)
        .where(PhenotypeObservation.case_id == case_id)
        .order_by(PhenotypeObservation.created_at, PhenotypeObservation.id)
    ).all()
    for row in rows:
        if row.analysis_id is not None:
            analysis = db.get(Analysis, row.analysis_id)
            if analysis is None or analysis.case_id != case.id:
                raise HTTPException(409, "Phenotype analysis does not match its case")
        if row.subject_member_id is not None:
            member = db.get(PedigreeMember, row.subject_member_id)
            if member is None or member.case_id != case.id:
                raise HTTPException(409, "Phenotype subject does not match its case")
    amendments = db.scalars(
        select(PhenotypeObservationAmendment).where(
            PhenotypeObservationAmendment.observation_id.in_([row.id for row in rows])
        )
    ).all() if rows else []
    amendment_by_observation = {item.observation_id: item for item in amendments}
    return {
        "case_id": str(case_id),
        "count": len(rows),
        "phenotypes": [_payload(row, amendment_by_observation.get(row.id)) for row in rows],
    }


@router.post("/cases/{case_id}/phenotypes", status_code=201)
def add_case_phenotype(
    case_id: UUID,
    body: PhenotypeInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = db.get(Case, case_id, with_for_update=True)
    if not case:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    active_analyses = db.scalars(
        select(Analysis).where(
            Analysis.case_id == case_id,
            Analysis.status.in_((
                "CREATED", "QUEUED", "PENDING", "RUNNING", "RETRYING",
                "REQUIRES_REVIEW", "BLOCKED", "RESOURCE_FAILURE", "CANCEL_REQUESTED",
            )),
        )
    ).all()
    for active_analysis in active_analyses:
        evidence_step = db.scalar(
            select(WorkflowStep).where(
                WorkflowStep.analysis_id == active_analysis.id,
                WorkflowStep.step_id == "build_evidence",
            )
        )
        if evidence_step is not None and (evidence_step.metadata_json or {}).get("clinical_input_snapshot") is not None:
            raise HTTPException(409, "Clinical phenotype input is frozen for an active analysis snapshot")
    if body.subject_member_id is not None:
        member = db.get(PedigreeMember, body.subject_member_id)
        if member is None or member.case_id != case.id:
            raise HTTPException(400, "Phenotype subject must be a pedigree member in this case")

    record_fingerprint = _phenotype_record_fingerprint(body)
    existing_record = db.scalar(
        select(PhenotypeObservation).where(
            PhenotypeObservation.case_id == case_id,
            PhenotypeObservation.analysis_id.is_(None),
            PhenotypeObservation.record_fingerprint == record_fingerprint,
        )
    )
    if existing_record is not None:
        return _payload(existing_record)

    superseded_row = None
    if body.supersedes_observation_id is not None:
        superseded_row = db.get(
            PhenotypeObservation, body.supersedes_observation_id, with_for_update=True
        )
        if superseded_row is None or superseded_row.case_id != case.id:
            raise HTTPException(404, "Phenotype observation to supersede was not found in this case")
        if superseded_row.analysis_id is not None:
            raise HTTPException(409, "Analysis-scoped phenotype observations are immutable")
        if superseded_row.subject_member_id != body.subject_member_id:
            raise HTTPException(409, "A phenotype correction must retain the original observation subject")
        existing_amendment = db.scalar(
            select(PhenotypeObservationAmendment).where(
                PhenotypeObservationAmendment.observation_id == superseded_row.id
            )
        )
        if existing_amendment is not None:
            raise HTTPException(409, "This phenotype observation has already been superseded or retracted")

    canonical_hpo_id, ontology_resolution = _resolution_bundle(db, case, body)
    row = PhenotypeObservation(
        id=uuid4(), case_id=case_id, analysis_id=None,
        subject_member_id=body.subject_member_id, hpo_id=body.hpo_id,
        canonical_hpo_id=canonical_hpo_id, record_fingerprint=record_fingerprint,
        label=body.label, present=body.phenotype_status == "PRESENT",
        phenotype_status=body.phenotype_status, onset=body.onset, severity=body.severity,
        observed_at=body.observed_at, clinical_attributes=body.clinical_attributes,
        ontology_resolution=ontology_resolution, source=body.source, evidence=body.evidence,
    )
    amendment = None
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
            if superseded_row is not None:
                amendment = PhenotypeObservationAmendment(
                    id=uuid4(), case_id=case.id, observation_id=superseded_row.id,
                    replacement_observation_id=row.id, amendment_type="SUPERSEDED",
                    reason=body.amendment_reason,
                    amendment_fingerprint=_amendment_fingerprint(
                        case.id, superseded_row.id, row.id, "SUPERSEDED",
                        body.amendment_reason, principal.user_id,
                    ),
                    recorded_by=principal.user_id,
                )
                db.add(amendment)
                db.flush()
    except IntegrityError:
        existing_record = db.scalar(
            select(PhenotypeObservation).where(
                PhenotypeObservation.case_id == case_id,
                PhenotypeObservation.analysis_id.is_(None),
                PhenotypeObservation.record_fingerprint == record_fingerprint,
            )
        )
        if existing_record is not None:
            return _payload(existing_record)
        raise HTTPException(409, "Phenotype observation was concurrently amended; refresh the case and retry")

    AuditService(db).record(
        event_type="PHENOTYPE_SUPERSEDED" if superseded_row is not None else "PHENOTYPE_ADDED",
        case_id=case_id, analysis_id=None, actor_type="HUMAN",
        actor_id=str(principal.user_id), subject_type="PHENOTYPE",
        subject_id=str(superseded_row.id if superseded_row is not None else row.id),
        operation="SUPERSEDE" if superseded_row is not None else "CREATE",
        after_state={
            "hpo_id": body.hpo_id, "canonical_hpo_id": canonical_hpo_id,
            "phenotype_status": body.phenotype_status,
            "subject_member_id": str(body.subject_member_id) if body.subject_member_id else None,
            "replacement_observation_id": str(row.id) if superseded_row is not None else None,
            "amendment_fingerprint": amendment.amendment_fingerprint if amendment is not None else None,
            "ontology_resolution": ontology_resolution,
        },
    )
    create_case_change_candidates(
        db, case=case, trigger_type="PHENOTYPE_UPDATE",
        reason=(
            f"Phenotype observation {superseded_row.id} was superseded by {row.id}; completed analyses may require reanalysis."
            if superseded_row is not None
            else f"Phenotype {body.hpo_id} was added to case {case.case_identifier}; completed analyses may require reanalysis."
        ),
        metadata={
            "hpo_id": body.hpo_id, "canonical_hpo_id": canonical_hpo_id,
            "phenotype_status": body.phenotype_status, "phenotype_id": str(row.id),
            "supersedes_observation_id": str(superseded_row.id) if superseded_row is not None else None,
            "amendment_id": str(amendment.id) if amendment is not None else None,
            "subject_member_id": str(body.subject_member_id) if body.subject_member_id else None,
        },
    )
    db.commit()
    return _payload(row)


@router.post("/cases/{case_id}/phenotypes/{phenotype_id}/retractions", status_code=201)
def retract_case_phenotype(
    case_id: UUID, phenotype_id: UUID, body: PhenotypeRetractionInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = db.get(Case, case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    active_analyses = db.scalars(
        select(Analysis).where(
            Analysis.case_id == case_id,
            Analysis.status.in_((
                "CREATED", "QUEUED", "PENDING", "RUNNING", "RETRYING",
                "REQUIRES_REVIEW", "BLOCKED", "RESOURCE_FAILURE", "CANCEL_REQUESTED",
            )),
        )
    ).all()
    for active_analysis in active_analyses:
        evidence_step = db.scalar(
            select(WorkflowStep).where(
                WorkflowStep.analysis_id == active_analysis.id,
                WorkflowStep.step_id == "build_evidence",
            )
        )
        if evidence_step is not None and (evidence_step.metadata_json or {}).get("clinical_input_snapshot") is not None:
            raise HTTPException(409, "Clinical phenotype input is frozen for an active analysis snapshot")
    observation = db.get(PhenotypeObservation, phenotype_id, with_for_update=True)
    if observation is None or observation.case_id != case.id:
        raise HTTPException(404, "Phenotype observation not found in this case")
    if observation.analysis_id is not None:
        raise HTTPException(409, "Analysis-scoped phenotype observations are immutable")
    fingerprint = _amendment_fingerprint(
        case.id, observation.id, None, "RETRACTED", body.reason, principal.user_id
    )
    existing = db.scalar(
        select(PhenotypeObservationAmendment).where(
            PhenotypeObservationAmendment.observation_id == observation.id
        )
    )
    if existing is not None:
        if existing.amendment_fingerprint == fingerprint:
            return _amendment_payload(existing)
        raise HTTPException(409, "This phenotype observation has already been superseded or retracted")
    amendment = PhenotypeObservationAmendment(
        id=uuid4(), case_id=case.id, observation_id=observation.id,
        replacement_observation_id=None, amendment_type="RETRACTED",
        reason=body.reason, amendment_fingerprint=fingerprint,
        recorded_by=principal.user_id,
    )
    try:
        with db.begin_nested():
            db.add(amendment)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(PhenotypeObservationAmendment).where(
                PhenotypeObservationAmendment.observation_id == observation.id
            )
        )
        if existing is not None and existing.amendment_fingerprint == fingerprint:
            return _amendment_payload(existing)
        raise HTTPException(409, "Phenotype observation was concurrently amended; refresh the case and retry")
    AuditService(db).record(
        event_type="PHENOTYPE_RETRACTED", case_id=case.id, analysis_id=None,
        actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="PHENOTYPE", subject_id=str(observation.id), operation="RETRACT",
        after_state={"phenotype_id": str(observation.id), "hpo_id": observation.hpo_id,
                     "amendment_id": str(amendment.id), "amendment_fingerprint": fingerprint},
    )
    create_case_change_candidates(
        db, case=case, trigger_type="PHENOTYPE_UPDATE",
        reason=f"Phenotype observation {observation.id} was retracted; completed analyses may require reanalysis.",
        metadata={"phenotype_id": str(observation.id), "amendment_id": str(amendment.id),
                  "amendment_type": "RETRACTED"},
    )
    db.commit()
    return _amendment_payload(amendment)


@router.get("/analyses/{analysis_id}/phenotypes")
def list_analysis_phenotypes(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    rows = db.scalars(
        select(PhenotypeObservation).where(
            PhenotypeObservation.case_id == analysis.case_id,
            (PhenotypeObservation.analysis_id == analysis_id)
            | (PhenotypeObservation.analysis_id.is_(None)),
        ).order_by(PhenotypeObservation.created_at, PhenotypeObservation.id)
    ).all()
    evidence_step = db.scalar(
        select(WorkflowStep).where(
            WorkflowStep.analysis_id == analysis.id,
            WorkflowStep.step_id == "build_evidence",
        )
    )
    snapshot = (evidence_step.metadata_json or {}).get("clinical_input_snapshot") if evidence_step else None
    if snapshot is not None:
        validated = validate_case_clinical_input_snapshot(snapshot)
        snapshot_rows = validated["phenotype_observations"]
        return {
            "analysis_id": str(analysis_id),
            "count": len(snapshot_rows),
            "phenotypes": snapshot_rows,
            "snapshot_sha256": (evidence_step.metadata_json or {}).get("clinical_input_snapshot_sha256"),
        }
    amendments = db.scalars(
        select(PhenotypeObservationAmendment).where(
            PhenotypeObservationAmendment.observation_id.in_([row.id for row in rows])
        )
    ).all() if rows else []
    amendment_by_observation = {item.observation_id: item for item in amendments}
    return {
        "analysis_id": str(analysis_id),
        "count": len(rows),
        "phenotypes": [_payload(row, amendment_by_observation.get(row.id)) for row in rows],
    }



_INTERNAL_EXPORT_KEYS = {
    "case_id", "analysis_id", "member_id", "parent_member_id", "child_member_id",
    "specimen_id", "artifact_id", "user_id", "recorded_by", "created_by",
    "revision_id", "resource_id", "qualification_id", "execution_id", "provider_id",
}


def _sanitize_export_sidecar(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_export_sidecar(item)
            for key, item in value.items()
            if key not in _INTERNAL_EXPORT_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_export_sidecar(item) for item in value]
    return value


def _server_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _clinical_intake_export_payload(row: ClinicalIntakeRevision | None) -> dict[str, Any] | None:
    if row is None:
        return None
    context = dict(row.context or {})
    prior_testing = []
    for item in context.get("prior_testing", []) or []:
        if not isinstance(item, dict):
            continue
        exported = _sanitize_export_sidecar(item)
        if item.get("artifact_id"):
            exported["artifact_reference_present"] = True
        prior_testing.append(exported)
    if "prior_testing" in context:
        context["prior_testing"] = prior_testing
    return {
        "version": row.version,
        "schema_version": row.schema_version,
        "revision_fingerprint": row.revision_fingerprint,
        "intake_status": row.intake_status,
        "phenotype_review_status": row.phenotype_review_status,
        "family_history_review_status": row.family_history_review_status,
        "context": context,
        "phenotype_review_note": row.phenotype_review_note,
        "family_history_review_note": row.family_history_review_note,
        "completion_note": row.completion_note,
        "recorded_at": _server_utc_iso(row.recorded_at),
    }





def _active_export_observations(
    observations: list[PhenotypeObservation],
    amendments_by_observation: dict[UUID, PhenotypeObservationAmendment],
) -> list[PhenotypeObservation]:
    """Only current, non-amended clinical assertions enter standards documents."""
    return [row for row in observations if row.id not in amendments_by_observation]


def _phenotype_export_sidecar(
    observations: list[PhenotypeObservation],
    members: list[PedigreeMember],
    amendments_by_observation: dict[UUID, PhenotypeObservationAmendment] | None = None,
) -> list[dict[str, Any]]:
    member_identifiers = {str(member.id): member.member_identifier for member in members}
    amendments = amendments_by_observation or {}
    observation_by_id = {row.id: row for row in observations}
    exported = []
    for row in observations:
        subject_member_id = (
            member_identifiers.get(str(row.subject_member_id))
            if row.subject_member_id is not None else None
        )
        if row.subject_member_id is not None and subject_member_id is None:
            raise HTTPException(409, "Phenotype observation references a family member outside this case")
        amendment = amendments.get(row.id)
        replacement = (
            observation_by_id.get(amendment.replacement_observation_id)
            if amendment is not None and amendment.replacement_observation_id is not None
            else None
        )
        exported.append({
            "record_fingerprint": row.record_fingerprint,
            "subject_member_identifier": subject_member_id,
            "hpo_id": row.hpo_id,
            "canonical_hpo_id": row.canonical_hpo_id,
            "label": row.label,
            "phenotype_status": row.phenotype_status,
            "present": row.present,
            "onset": row.onset,
            "severity": row.severity,
            "observed_at": row.observed_at.isoformat() if row.observed_at else None,
            "created_at": _server_utc_iso(row.created_at),
            "clinical_attributes": _sanitize_export_sidecar(row.clinical_attributes or {}),
            "ontology_resolution": _sanitize_export_sidecar(row.ontology_resolution or {}),
            "source": row.source,
            "evidence": _sanitize_export_sidecar(row.evidence or {}),
            "record_lifecycle_status": amendment.amendment_type if amendment else "ACTIVE",
            "amendment_reason": amendment.reason if amendment else None,
            "amendment_recorded_at": _server_utc_iso(amendment.recorded_at) if amendment else None,
            "replacement_record_fingerprint": replacement.record_fingerprint if replacement else None,
        })
    return exported

def _pedigree_export_sidecar(
    case: Case,
    members: list[PedigreeMember],
    relationships: list[PedigreeRelationship],
    clinical_intake_revision: ClinicalIntakeRevision | None,
) -> dict[str, Any]:
    identifiers = {str(member.id): member.member_identifier for member in members}
    consanguinity_values = []
    sources = [getattr(case, "clinical_context", None) or {}]
    sources.extend(member.metadata_json or {} for member in members)
    sources.extend(relationship.metadata_json or {} for relationship in relationships)
    if clinical_intake_revision is not None:
        sources.append(clinical_intake_revision.context or {})
    for source in sources:
        if isinstance(source, dict) and "consanguinous_parents" in source:
            consanguinity_values.append(source["consanguinous_parents"])
    consanguinous_parents = consanguinity_values[0] if consanguinity_values else None
    return {
        "consanguinous_parents": (
            consanguinous_parents if consanguinous_parents is not None else "NOT_RECORDED"
        ),
        "members": [
            {
                "member_identifier": member.member_identifier,
                "phenopacket_subject_id": (
                    f"SIRALOOM:{uuid5(NAMESPACE_URL, f'siraloom:pedigree-member:{member.id}')}"
                ),
                "relationship_to_proband": member.relationship_to_proband,
                "sex": member.sex,
                "affected_status": member.affected_status,
                "is_proband": member.is_proband,
                "sampled": member.sampled,
                "specimen_reference_present": member.specimen_id is not None,
                "metadata": _sanitize_export_sidecar(member.metadata_json or {}),
            }
            for member in members
        ],
        "relationships": [
            {
                "parent_member_identifier": identifiers.get(str(row.parent_member_id)),
                "child_member_identifier": identifiers.get(str(row.child_member_id)),
                "relationship_type": row.relationship_type,
                "metadata": _sanitize_export_sidecar(row.metadata_json or {}),
            }
            for row in relationships
        ],
    } if members else {"members": [], "relationships": []}

@router.get("/cases/{case_id}/phenopackets-v2")
def export_case_phenopackets_v2(
    case_id: UUID,
    allow_lossy: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Export the case as a GA4GH Phenopacket v2 or Family document.

    The response envelope carries the schema-validated GA4GH document and
    explicit loss warnings. Strict export is the default.
    """
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_permission(case, principal, db, "read")

    observations = list(db.scalars(
        select(PhenotypeObservation)
        .where(
            PhenotypeObservation.case_id == case_id,
            PhenotypeObservation.analysis_id.is_(None),
        )
        .order_by(PhenotypeObservation.created_at, PhenotypeObservation.id)
    ))
    amendments = db.scalars(
        select(PhenotypeObservationAmendment).where(
            PhenotypeObservationAmendment.observation_id.in_([row.id for row in observations])
        )
    ).all() if observations else []
    amendments_by_observation = {row.observation_id: row for row in amendments}
    active_observations = _active_export_observations(observations, amendments_by_observation)
    members = list(db.scalars(
        select(PedigreeMember)
        .where(PedigreeMember.case_id == case_id)
        .order_by(PedigreeMember.created_at, PedigreeMember.member_identifier)
    ))
    relationships = list(db.scalars(
        select(PedigreeRelationship)
        .where(PedigreeRelationship.case_id == case_id)
        .order_by(PedigreeRelationship.created_at, PedigreeRelationship.id)
    ))
    clinical_intake_revision = db.scalar(
        select(ClinicalIntakeRevision)
        .where(ClinicalIntakeRevision.case_id == case_id)
        .order_by(ClinicalIntakeRevision.version.desc())
        .limit(1)
    )

    try:
        document, warnings = build_phenopackets_v2(
            case=case,
            phenotype_observations=active_observations,
            pedigree_members=members,
            pedigree_relationships=relationships,
            clinical_intake_revision=clinical_intake_revision,
            allow_lossy=allow_lossy,
        )
    except PhenopacketExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    AuditService(db).record(
        event_type="CLINICAL_INTEROPERABILITY_EXPORT",
        case_id=case_id,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="CASE",
        subject_id=str(case_id),
        operation="EXPORT",
        after_state={
            "format": "GA4GH_PHENOPACKETS",
            "schema_version": "2.0",
            "lossy": bool(warnings),
            "warning_count": len(warnings),
            "clinical_intake_revision_id": (
                str(clinical_intake_revision.id) if clinical_intake_revision is not None else None
            ),
            "clinical_intake_revision_version": (
                clinical_intake_revision.version if clinical_intake_revision is not None else None
            ),
        },
        payload={
            "allow_lossy": allow_lossy,
            "warning_fields": sorted({item["field"] for item in warnings}),
            "clinical_intake_revision_id": (
                str(clinical_intake_revision.id) if clinical_intake_revision is not None else None
            ),
        },
    )
    db.commit()
    return {
        "format": "GA4GH_PHENOPACKETS",
        "schema_version": "2.0",
        "lossy": bool(warnings),
        "warnings": warnings,
        "clinical_intake_revision": _clinical_intake_export_payload(clinical_intake_revision),
        "phenotype_observation_sidecar": _phenotype_export_sidecar(observations, members, amendments_by_observation),
        "pedigree_sidecar": _pedigree_export_sidecar(
            case, members, relationships, clinical_intake_revision
        ),
        "document": document,
    }


@router.get("/cases/{case_id}/fhir-r5/phenotypes")
def export_case_phenotypes_fhir_r5(
    case_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Export phenotype and family context as a validated HL7 FHIR R5 Bundle."""
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_permission(case, principal, db, "read")

    observations = list(db.scalars(
        select(PhenotypeObservation)
        .where(
            PhenotypeObservation.case_id == case_id,
            PhenotypeObservation.analysis_id.is_(None),
        )
        .order_by(PhenotypeObservation.created_at, PhenotypeObservation.id)
    ))
    amendments = db.scalars(
        select(PhenotypeObservationAmendment).where(
            PhenotypeObservationAmendment.observation_id.in_([row.id for row in observations])
        )
    ).all() if observations else []
    amendments_by_observation = {row.observation_id: row for row in amendments}
    active_observations = _active_export_observations(observations, amendments_by_observation)
    members = list(db.scalars(
        select(PedigreeMember)
        .where(PedigreeMember.case_id == case_id)
        .order_by(PedigreeMember.created_at, PedigreeMember.member_identifier)
    ))
    relationships = list(db.scalars(
        select(PedigreeRelationship)
        .where(PedigreeRelationship.case_id == case_id)
        .order_by(PedigreeRelationship.created_at, PedigreeRelationship.id)
    ))
    clinical_intake_revision = db.scalar(
        select(ClinicalIntakeRevision)
        .where(ClinicalIntakeRevision.case_id == case_id)
        .order_by(ClinicalIntakeRevision.version.desc())
        .limit(1)
    )

    try:
        bundle = build_fhir_r5_bundle(
            case=case,
            phenotype_observations=active_observations,
            pedigree_members=members,
            pedigree_relationships=relationships,
            clinical_intake_revision=clinical_intake_revision,
        )
    except FHIRExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    AuditService(db).record(
        event_type="CLINICAL_INTEROPERABILITY_EXPORT",
        case_id=case_id,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="CASE",
        subject_id=str(case_id),
        operation="EXPORT",
        after_state={
            "format": "HL7_FHIR_R5",
            "fhir_version": "5.0.0",
            "resource_count": len(bundle.get("entry", [])),
            "clinical_intake_revision_id": (
                str(clinical_intake_revision.id) if clinical_intake_revision is not None else None
            ),
            "clinical_intake_revision_version": (
                clinical_intake_revision.version if clinical_intake_revision is not None else None
            ),
        },
        payload={
            "format": "HL7_FHIR_R5",
            "resource_count": len(bundle.get("entry", [])),
            "clinical_intake_revision_id": (
                str(clinical_intake_revision.id) if clinical_intake_revision is not None else None
            ),
        },
    )
    db.commit()
    return JSONResponse(content=bundle, media_type="application/fhir+json")
