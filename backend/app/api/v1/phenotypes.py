from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    get_accessible_analysis,
    require_case_permission,
    require_role,
)
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.case_change import create_case_change_candidates
from backend.app.domain.provider_registry import ProviderRegistryError, register_builtin_providers
from backend.app.domain.resource_capabilities import CapabilityRequirement, ResourceCapability
from backend.app.domain.resource_execution import ResourceExecutionError, resolve_resource_execution
from backend.app.domain.resource_execution_plan import build_resource_execution_plan
from backend.app.adapters.phenotype.hpo_obo import HPOOntologyError
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    Analysis, Case, PedigreeMember, PhenotypeObservation, ResourceExecutionRecord,
)
from backend.app.infrastructure.db.session import get_db
from backend.app.phenotype import normalize_hpo_id

router = APIRouter(tags=["phenotypes"])

_ALLOWED_ATTRIBUTE_KEYS = {
    "onset_age", "clinical_course_hpo_id", "modifier_hpo_ids", "laterality",
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
            if lower is None or upper is None or float(lower) < 0 or float(upper) < float(lower):
                raise ValueError("RANGE onset_age requires non-negative ordered lower_value and upper_value")
        else:
            age = onset_age.get("value")
            if age is None or float(age) < 0:
                raise ValueError("onset_age requires a non-negative value")
        normalized["onset_age"] = {**onset_age, "unit": unit, "comparator": comparator}
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
        if int(frequency.get("count", 0)) < 1 or float(frequency.get("period_value", 0)) <= 0:
            raise ValueError("episode_frequency requires positive count and period_value")
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


def _payload(row):
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
    return {"case_id": str(case_id), "count": len(rows), "phenotypes": [_payload(r) for r in rows]}


@router.post("/cases/{case_id}/phenotypes", status_code=201)
def add_case_phenotype(
    case_id: UUID,
    body: PhenotypeInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    # Serialize phenotype changes against report sign-out and snapshot capture.
    case = db.get(Case, case_id, with_for_update=True)
    if not case:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    if body.subject_member_id is not None:
        member = db.get(PedigreeMember, body.subject_member_id)
        if member is None or member.case_id != case.id:
            raise HTTPException(400, "Phenotype subject must be a pedigree member in this case")
    canonical_hpo_id, ontology_resolution = _resolution_bundle(db, case, body)
    row = db.scalar(
        select(PhenotypeObservation).where(
            PhenotypeObservation.case_id == case_id,
            PhenotypeObservation.analysis_id.is_(None),
            PhenotypeObservation.subject_member_id == body.subject_member_id,
            PhenotypeObservation.hpo_id == body.hpo_id,
            PhenotypeObservation.phenotype_status == body.phenotype_status,
        )
    )
    if row:
        return _payload(row)
    present = body.phenotype_status == "PRESENT"
    row = PhenotypeObservation(
        id=uuid4(),
        case_id=case_id,
        analysis_id=None,
        subject_member_id=body.subject_member_id,
        hpo_id=body.hpo_id,
        canonical_hpo_id=canonical_hpo_id,
        label=body.label,
        present=present,
        phenotype_status=body.phenotype_status,
        onset=body.onset,
        severity=body.severity,
        observed_at=body.observed_at,
        clinical_attributes=body.clinical_attributes,
        ontology_resolution=ontology_resolution,
        source=body.source,
        evidence=body.evidence,
    )
    db.add(row)
    AuditService(db).record(
        event_type="PHENOTYPE_ADDED",
        case_id=case_id,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="PHENOTYPE",
        subject_id=str(row.id),
        operation="CREATE",
        after_state={
            "hpo_id": body.hpo_id,
            "canonical_hpo_id": canonical_hpo_id,
            "phenotype_status": body.phenotype_status,
            "subject_member_id": str(body.subject_member_id) if body.subject_member_id else None,
            "ontology_resolution": ontology_resolution,
        },
    )
    create_case_change_candidates(
        db,
        case=case,
        trigger_type="PHENOTYPE_UPDATE",
        reason=f"Phenotype {body.hpo_id} was added to case {case.case_identifier}; completed analyses may require reanalysis.",
        metadata={
            "hpo_id": body.hpo_id,
            "canonical_hpo_id": canonical_hpo_id,
            "phenotype_status": body.phenotype_status,
            "phenotype_id": str(row.id),
            "subject_member_id": str(body.subject_member_id) if body.subject_member_id else None,
        },
    )
    db.commit()
    return _payload(row)


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
    return {
        "analysis_id": str(analysis_id),
        "count": len(rows),
        "phenotypes": [_payload(r) for r in rows],
    }
