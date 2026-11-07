from datetime import UTC, datetime
import hashlib
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    READ_ROLES,
    REVIEW_ROLES,
    get_accessible_analysis,
    get_analysis_variant,
    require_case_permission,
    require_role,
)
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.case_change import create_case_change_candidates
from backend.app.domain.family_genotype_matrix import build_family_genotype_matrix
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisPartition,
    Artifact,
    Case,
    Evidence,
    FamilyGenotypeMatrixSnapshot,
    InheritanceAssessment,
    PedigreeMember,
    PedigreeRelationship,
    PedigreeSampleBinding,
    PedigreeSampleIdentityEvidence,
    SegregationObservation,
    SegregationObservationRevision,
    Specimen,
    SpecimenPloidyEvidenceRevision,
    Variant,
    WorkflowStep,
)
from backend.app.infrastructure.db.session import get_db
from backend.app.domain.sample_call import get_analysis_sample_calls
from backend.app.inheritance import FamilyObservation, assess_model, fingerprint, normalize_model

router = APIRouter(tags=["pedigree-inheritance"])


def _lock_analysis_for_pedigree(db: Session, analysis_id: UUID, principal: Principal, permission: str):
    """Serialize report-contributing pedigree decisions with sign-out."""
    analysis = db.scalar(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    case = db.get(Case, analysis.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    require_case_permission(case, principal, db, permission)
    return analysis

class MemberInput(BaseModel):
    member_identifier: str = Field(min_length=1, max_length=100)
    relationship_to_proband: str | None = Field(default=None, max_length=100)
    sex: str | None = Field(default=None, max_length=30)
    affected_status: str = Field(default="UNKNOWN", pattern=r"^(AFFECTED|UNAFFECTED|UNKNOWN)$")
    is_proband: bool = False
    sampled: bool = False
    specimen_id: UUID | None = None
    metadata: dict = Field(default_factory=dict)

class GenotypeMatrixInput(BaseModel):
    binding_ids: list[UUID] = Field(min_length=1, max_length=50)
    variant_ids: list[UUID] = Field(min_length=1, max_length=500)


class SampleBindingInput(BaseModel):
    member_id: UUID
    specimen_id: UUID
    analysis_id: UUID
    artifact_id: UUID
    sample_name: str = Field(min_length=1, max_length=200)
    binding_method: str = Field(min_length=1, max_length=100)
    evidence_reference: str | None = Field(default=None, max_length=1000)


class SampleIdentityEvidenceInput(BaseModel):
    evidence_type: str = Field(pattern=r"^(CHAIN_OF_CUSTODY|SAMPLE_IDENTITY_QC)$")
    result: str = Field(pattern=r"^(PASS|FAIL|INDETERMINATE)$")
    method: str = Field(min_length=1, max_length=200)
    method_version: str = Field(min_length=1, max_length=100)
    evidence_reference: str = Field(min_length=1, max_length=1000)
    source_artifact_id: UUID | None = None
    metrics: dict = Field(default_factory=dict)


class SampleIdentityEvidenceReviewInput(BaseModel):
    decision: str = Field(pattern=r"^(ACCEPTED|REJECTED)$")
    reason: str = Field(min_length=1, max_length=5000)


class SampleBindingReviewInput(BaseModel):
    decision: str = Field(pattern=r"^(VERIFIED|REJECTED)$")
    reason: str = Field(min_length=1, max_length=5000)


class RelationshipInput(BaseModel):
    parent_member_id: UUID
    child_member_id: UUID
    relationship_type: str = Field(default="PARENT_CHILD", max_length=50)
    metadata: dict = Field(default_factory=dict)

class SegregationInput(BaseModel):
    pedigree_member_id: UUID
    genotype: str | None = Field(default=None, max_length=50)
    zygosity: str | None = Field(default=None, max_length=50)
    phase: str | None = Field(default=None, max_length=50)
    allele_observed: str | None = Field(default=None, max_length=50)
    phenotype_status: str | None = Field(default=None, max_length=30)
    source: str = Field(default="HUMAN_REVIEW", max_length=50)
    notes: str | None = Field(default=None, max_length=5000)
    revision_reason: str | None = Field(default=None, max_length=5000)
    metadata: dict = Field(default_factory=dict)

class AssessmentInput(BaseModel):
    models: list[str] = Field(
        default_factory=lambda: ["AD", "AR", "X_LINKED", "DE_NOVO"],
        min_length=1,
        max_length=6,
    )
    # Explicitly selected, reviewed family bindings. Empty preserves the legacy
    # review-only path; it never promotes manually entered genotypes to evidence.
    binding_ids: list[UUID] = Field(default_factory=list, max_length=50)
    reviewer_note: str | None = Field(default=None, max_length=5000)


def _member(m):
    return {"id":str(m.id),"member_identifier":m.member_identifier,"relationship_to_proband":m.relationship_to_proband,"sex":m.sex,"affected_status":m.affected_status,"is_proband":m.is_proband,"sampled":m.sampled,"specimen_id":str(m.specimen_id) if m.specimen_id else None,"metadata":m.metadata_json or {}}

def _relationship(r):
    return {"id":str(r.id),"parent_member_id":str(r.parent_member_id),"child_member_id":str(r.child_member_id),"relationship_type":r.relationship_type,"metadata":r.metadata_json or {}}

def _seg(o, member=None):
    return {"id":str(o.id),"pedigree_member_id":str(o.pedigree_member_id),"member_identifier":member.member_identifier if member else None,"genotype":o.genotype,"zygosity":o.zygosity,"phase":o.phase,"allele_observed":o.allele_observed,"phenotype_status":o.phenotype_status,"source":o.source,"notes":o.notes,"metadata":o.metadata_json or {}}

def _validate_observation_members(rows, members):
    if any(row.pedigree_member_id not in members for row in rows):
        raise HTTPException(
            status_code=409,
            detail="Segregation observation member does not belong to the analysis case",
        )

def _validate_pedigree_lineage(members, relationships, case_id, db):
    member_ids = {member.id for member in members}
    if any(
        relationship.parent_member_id not in member_ids
        or relationship.child_member_id not in member_ids
        for relationship in relationships
    ):
        raise HTTPException(
            status_code=409,
            detail="Pedigree relationship members do not belong to this case",
        )

    specimen_ids = {member.specimen_id for member in members if member.specimen_id}
    if not specimen_ids:
        return
    specimens = {
        specimen.id: specimen
        for specimen in db.scalars(
            select(Specimen).where(Specimen.id.in_(specimen_ids))
        )
    }
    if any(
        specimen_id not in specimens or specimens[specimen_id].case_id != case_id
        for specimen_id in specimen_ids
    ):
        raise HTTPException(
            status_code=409,
            detail="Pedigree member specimen does not belong to this case",
        )


def _would_create_pedigree_cycle(relationships, parent_member_id, child_member_id) -> bool:
    """Check whether adding parent -> child would create an ancestry cycle."""
    children_by_parent = {}
    for relationship in relationships:
        children_by_parent.setdefault(relationship.parent_member_id, set()).add(
            relationship.child_member_id
        )

    pending = [child_member_id]
    visited = set()
    while pending:
        member_id = pending.pop()
        if member_id == parent_member_id:
            return True
        if member_id in visited:
            continue
        visited.add(member_id)
        pending.extend(children_by_parent.get(member_id, ()))
    return False


def _pedigree_context_snapshot(db: Session, case_id: UUID) -> dict:
    """Capture the case pedigree used to contextualize a segregation observation."""
    members = list(db.scalars(
        select(PedigreeMember).where(PedigreeMember.case_id == case_id)
    ))
    relationships = list(db.scalars(
        select(PedigreeRelationship).where(PedigreeRelationship.case_id == case_id)
    ))
    _validate_pedigree_lineage(members, relationships, case_id, db)
    member_by_id = {member.id: member for member in members}
    specimen_ids = {member.specimen_id for member in members if member.specimen_id}
    specimens = {
        specimen.id: specimen
        for specimen in db.scalars(select(Specimen).where(Specimen.id.in_(specimen_ids)))
    } if specimen_ids else {}
    return {
        "schema_version": 1,
        "members": sorted(
            [
                {
                    "member_identifier": member.member_identifier,
                    "relationship_to_proband": member.relationship_to_proband,
                    "sex": member.sex,
                    "affected_status": member.affected_status,
                    "is_proband": member.is_proband,
                    "sampled": member.sampled,
                    "specimen_identifier": (
                        specimens[member.specimen_id].specimen_identifier
                        if member.specimen_id in specimens else None
                    ),
                    "specimen_type": (
                        specimens[member.specimen_id].specimen_type
                        if member.specimen_id in specimens else None
                    ),
                    "metadata": member.metadata_json or {},
                }
                for member in members
            ],
            key=lambda item: item["member_identifier"],
        ),
        "relationships": sorted(
            [
                {
                    "parent_member_identifier": member_by_id[relationship.parent_member_id].member_identifier,
                    "child_member_identifier": member_by_id[relationship.child_member_id].member_identifier,
                    "relationship_type": relationship.relationship_type,
                    "metadata": relationship.metadata_json or {},
                }
                for relationship in relationships
            ],
            key=lambda item: (
                item["parent_member_identifier"],
                item["child_member_identifier"],
                item["relationship_type"],
            ),
        ),
    }

def _sample_binding_payload(row):
    return {
        "binding_id": str(row.id), "case_id": str(row.case_id),
        "member_id": str(row.pedigree_member_id), "specimen_id": str(row.specimen_id),
        "analysis_id": str(row.analysis_id), "artifact_id": str(row.artifact_id),
        "source_artifact_sha256": row.source_artifact_sha256,
        "sample_name": row.sample_name, "binding_status": row.binding_status,
        "binding_method": row.binding_method, "evidence_reference": row.evidence_reference,
        "review_reason": row.review_reason, "version": row.version,
        "supersedes_binding_id": str(row.supersedes_binding_id) if row.supersedes_binding_id else None,
        "recorded_by": str(row.recorded_by),
        "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }


def _sample_binding_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@router.get("/cases/{case_id}/pedigree/sample-bindings")
def list_sample_bindings(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "read")
    rows = db.scalars(
        select(PedigreeSampleBinding)
        .where(PedigreeSampleBinding.case_id == case_id)
        .order_by(PedigreeSampleBinding.pedigree_member_id, PedigreeSampleBinding.version)
    ).all()
    return {"case_id": str(case_id), "bindings": [_sample_binding_payload(row) for row in rows]}


@router.get("/cases/{case_id}/pedigree/sample-binding-context")
def get_sample_binding_context(
    case_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """List case analyses with their exact configured source VCF and selected sample."""
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "read")
    analyses = db.scalars(
        select(Analysis).where(Analysis.case_id == case_id).order_by(Analysis.created_at.desc())
    ).all()
    rows = []
    for analysis in analyses:
        configuration = analysis.configuration or {}
        raw_artifact_id = configuration.get("input_artifact_id")
        sample_name = configuration.get("vcf_sample_name")
        artifact = None
        if raw_artifact_id:
            try:
                artifact = db.get(Artifact, UUID(str(raw_artifact_id)))
            except (TypeError, ValueError):
                artifact = None
        valid_artifact = bool(
            artifact is not None
            and artifact.case_id == case_id
            and artifact.artifact_type in {"VCF", "SOURCE_VCF"}
            and artifact.validation_status in {"VALID", "VALIDATED"}
            and isinstance(artifact.sha256, str)
            and len(artifact.sha256) == 64
            and all(character in "0123456789abcdefABCDEF" for character in artifact.sha256)
        )
        rows.append({
            "analysis_id": str(analysis.id),
            "analysis_status": analysis.status,
            "reference_build": analysis.reference_build,
            "assay_id": str(analysis.assay_id) if analysis.assay_id else None,
            "selected_sample_name": sample_name if isinstance(sample_name, str) and sample_name.strip() else None,
            "source_vcf": ({
                "artifact_id": str(artifact.id),
                "filename": artifact.filename,
                "sha256": artifact.sha256,
                "specimen_id": str(artifact.specimen_id) if artifact.specimen_id else None,
                "validation_status": artifact.validation_status,
                "genome_build": artifact.genome_build,
            } if valid_artifact else None),
            "binding_candidate_status": (
                "READY" if valid_artifact and isinstance(sample_name, str) and sample_name.strip()
                else "MISSING_SOURCE_VCF_OR_SAMPLE_SELECTION"
            ),
        })
    return {"case_id": str(case_id), "analyses": rows}


@router.post("/cases/{case_id}/pedigree/sample-bindings", status_code=201)
def create_sample_binding(case_id: UUID, body: SampleBindingInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """Record an unverified family-member/specimen/VCF-sample identity claim."""
    case = db.get(Case, case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    member = db.get(PedigreeMember, body.member_id)
    specimen = db.get(Specimen, body.specimen_id)
    analysis = db.get(Analysis, body.analysis_id)
    artifact = db.get(Artifact, body.artifact_id)
    if member is None or member.case_id != case_id:
        raise HTTPException(404, "Pedigree member not found in this case")
    if specimen is None or specimen.case_id != case_id:
        raise HTTPException(404, "Specimen not found in this case")
    if analysis is None or analysis.case_id != case_id:
        raise HTTPException(404, "Analysis not found in this case")
    if artifact is None or artifact.case_id != case_id or artifact.artifact_type not in {"VCF", "SOURCE_VCF"}:
        raise HTTPException(404, "Source VCF artifact not found in this case")
    if artifact.specimen_id is not None and artifact.specimen_id != specimen.id:
        raise HTTPException(409, "Source VCF artifact is linked to a different specimen")
    if (
        artifact.validation_status not in {"VALID", "VALIDATED"}
        or not isinstance(artifact.sha256, str)
        or len(artifact.sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in artifact.sha256)
    ):
        raise HTTPException(409, "Source VCF must be validated and have a SHA-256 digest before identity binding")
    if not body.sample_name.strip() or not body.binding_method.strip():
        raise HTTPException(422, "Sample name and binding method must be non-empty")
    configured_sample = (analysis.configuration or {}).get("vcf_sample_name")
    if not configured_sample or configured_sample != body.sample_name.strip():
        raise HTTPException(409, "Sample name must exactly match the analysis-selected VCF sample")
    if (analysis.configuration or {}).get("input_artifact_id") != str(artifact.id):
        raise HTTPException(409, "Artifact is not the immutable source VCF selected for this analysis")
    specimen_sample = (specimen.metadata_json or {}).get("vcf_sample_name")
    if specimen_sample and specimen_sample != body.sample_name.strip():
        raise HTTPException(409, "Sample name conflicts with the specimen's registered sample-name hint")
    payload = {
        "schema_version": 1, "case_id": str(case_id), "member_id": str(member.id),
        "specimen_id": str(specimen.id), "analysis_id": str(analysis.id),
        "artifact_id": str(artifact.id), "source_artifact_sha256": artifact.sha256, "sample_name": body.sample_name.strip(),
        "binding_status": "UNVERIFIED", "binding_method": body.binding_method.strip(),
        "evidence_reference": body.evidence_reference, "version": 1,
        "supersedes_binding_id": None,
    }
    binding_fingerprint = _sample_binding_fingerprint(payload)
    existing = db.scalar(select(PedigreeSampleBinding).where(
        PedigreeSampleBinding.case_id == case_id,
        PedigreeSampleBinding.binding_fingerprint == binding_fingerprint,
    ))
    if existing is not None:
        return _sample_binding_payload(existing)
    row = PedigreeSampleBinding(
        id=uuid4(), case_id=case_id, pedigree_member_id=member.id,
        specimen_id=specimen.id, analysis_id=analysis.id, artifact_id=artifact.id,
        source_artifact_sha256=artifact.sha256, sample_name=body.sample_name.strip(), binding_status="UNVERIFIED",
        binding_method=body.binding_method.strip(), evidence_reference=body.evidence_reference,
        version=1, binding_fingerprint=binding_fingerprint,
        recorded_by=principal.user_id,
    )
    db.add(row)
    AuditService(db).record(
        event_type="PEDIGREE_SAMPLE_BINDING_RECORDED", case_id=case_id,
        analysis_id=analysis.id, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="PEDIGREE_SAMPLE_BINDING", subject_id=str(row.id),
        operation="CREATE_UNVERIFIED", after_state=_sample_binding_payload(row),
    )
    create_case_change_candidates(
        db, case=case, trigger_type="PEDIGREE_UPDATE",
        reason="Family sample identity claim changed; analyses may require reanalysis.",
        metadata={"change_type": "SAMPLE_BINDING_RECORDED", "binding_id": str(row.id)},
    )
    db.commit()
    return _sample_binding_payload(row)


@router.post("/cases/{case_id}/pedigree/sample-bindings/{binding_id}/supersede", status_code=201)
def supersede_sample_binding(
    case_id: UUID,
    binding_id: UUID,
    body: SampleBindingInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Append a corrected identity claim without mutating a reviewed binding."""
    case = db.get(Case, case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    previous = db.get(PedigreeSampleBinding, binding_id)
    if previous is None or previous.case_id != case_id:
        raise HTTPException(404, "Sample binding not found")
    member = db.get(PedigreeMember, body.member_id)
    specimen = db.get(Specimen, body.specimen_id)
    analysis = db.get(Analysis, body.analysis_id)
    artifact = db.get(Artifact, body.artifact_id)
    if member is None or member.case_id != case_id:
        raise HTTPException(404, "Pedigree member not found in this case")
    if specimen is None or specimen.case_id != case_id:
        raise HTTPException(404, "Specimen not found in this case")
    if analysis is None or analysis.case_id != case_id:
        raise HTTPException(404, "Analysis not found in this case")
    if artifact is None or artifact.case_id != case_id or artifact.artifact_type not in {"VCF", "SOURCE_VCF"}:
        raise HTTPException(404, "Source VCF artifact not found in this case")
    if artifact.specimen_id is not None and artifact.specimen_id != specimen.id:
        raise HTTPException(409, "Source VCF artifact is linked to a different specimen")
    if (
        artifact.validation_status not in {"VALID", "VALIDATED"}
        or not isinstance(artifact.sha256, str)
        or len(artifact.sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in artifact.sha256)
    ):
        raise HTTPException(409, "Source VCF must be validated and have a SHA-256 digest before identity binding")
    if not body.sample_name.strip() or not body.binding_method.strip():
        raise HTTPException(422, "Sample name and binding method must be non-empty")
    configuration = analysis.configuration or {}
    if configuration.get("input_artifact_id") != str(artifact.id):
        raise HTTPException(409, "Artifact is not the immutable source VCF selected for this analysis")
    if configuration.get("vcf_sample_name") != body.sample_name.strip():
        raise HTTPException(409, "Sample name must exactly match the analysis-selected VCF sample")
    specimen_sample = (specimen.metadata_json or {}).get("vcf_sample_name")
    if specimen_sample and specimen_sample != body.sample_name.strip():
        raise HTTPException(409, "Sample name conflicts with the specimen's registered sample-name hint")

    payload = {
        "schema_version": 1, "case_id": str(case_id), "member_id": str(member.id),
        "specimen_id": str(specimen.id), "analysis_id": str(analysis.id),
        "artifact_id": str(artifact.id), "source_artifact_sha256": artifact.sha256,
        "sample_name": body.sample_name.strip(), "binding_status": "UNVERIFIED",
        "binding_method": body.binding_method.strip(), "evidence_reference": body.evidence_reference,
        "version": previous.version + 1, "supersedes_binding_id": str(previous.id),
    }
    binding_fingerprint = _sample_binding_fingerprint(payload)
    existing = db.scalar(select(PedigreeSampleBinding).where(
        PedigreeSampleBinding.case_id == case_id,
        PedigreeSampleBinding.binding_fingerprint == binding_fingerprint,
    ))
    if existing is not None:
        return _sample_binding_payload(existing)
    successor = db.scalar(select(PedigreeSampleBinding).where(
        PedigreeSampleBinding.supersedes_binding_id == previous.id,
    ))
    if successor is not None:
        raise HTTPException(409, "This sample binding already has a conflicting successor revision")
    row = PedigreeSampleBinding(
        id=uuid4(), case_id=case_id, pedigree_member_id=member.id,
        specimen_id=specimen.id, analysis_id=analysis.id, artifact_id=artifact.id,
        source_artifact_sha256=artifact.sha256, sample_name=body.sample_name.strip(),
        binding_status="UNVERIFIED", binding_method=body.binding_method.strip(),
        evidence_reference=body.evidence_reference, version=previous.version + 1,
        supersedes_binding_id=previous.id, binding_fingerprint=binding_fingerprint,
        recorded_by=principal.user_id,
    )
    db.add(row)
    AuditService(db).record(
        event_type="PEDIGREE_SAMPLE_BINDING_SUPERSEDED", case_id=case_id,
        analysis_id=analysis.id, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="PEDIGREE_SAMPLE_BINDING", subject_id=str(row.id),
        operation="APPEND_CORRECTED_UNVERIFIED_BINDING",
        before_state=_sample_binding_payload(previous),
        after_state=_sample_binding_payload(row),
        reason="Corrected family member, specimen, source artifact, or VCF sample association.",
    )
    create_case_change_candidates(
        db, case=case, trigger_type="PEDIGREE_UPDATE",
        reason="A family sample identity claim was corrected; dependent analyses may require reanalysis.",
        metadata={"change_type": "SAMPLE_BINDING_SUPERSEDED", "binding_id": str(row.id)},
    )
    db.commit()
    return _sample_binding_payload(row)


def _sample_identity_evidence_payload(row):
    return {
        "evidence_id": str(row.id),
        "case_id": str(row.case_id),
        "binding_id": str(row.binding_id),
        "evidence_type": row.evidence_type,
        "result": row.result,
        "method": row.method,
        "method_version": row.method_version,
        "evidence_reference": row.evidence_reference,
        "source_artifact_id": str(row.source_artifact_id) if row.source_artifact_id else None,
        "metrics": row.metrics_json or {},
        "review_status": row.review_status,
        "review_reason": row.review_reason,
        "version": row.version,
        "supersedes_evidence_id": str(row.supersedes_evidence_id) if row.supersedes_evidence_id else None,
        "recorded_by": str(row.recorded_by),
        "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }


def _sample_identity_evidence_fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _active_sample_identity_evidence(db: Session, binding_id: UUID):
    rows = db.scalars(select(PedigreeSampleIdentityEvidence).where(
        PedigreeSampleIdentityEvidence.binding_id == binding_id,
    )).all()
    superseded_ids = {
        row.supersedes_evidence_id for row in rows if row.supersedes_evidence_id is not None
    }
    return [row for row in rows if row.id not in superseded_ids]


def _sample_binding_evidence_owner(db: Session, binding: PedigreeSampleBinding) -> UUID:
    """Resolve evidence attached to the unverified claim promoted by an append-only review."""
    direct = _active_sample_identity_evidence(db, binding.id)
    if direct:
        return binding.id
    supersedes_binding_id = getattr(binding, "supersedes_binding_id", None)
    if binding.binding_status != "VERIFIED" or supersedes_binding_id is None:
        return binding.id
    predecessor = db.get(PedigreeSampleBinding, supersedes_binding_id)
    if predecessor is None or predecessor.binding_status != "UNVERIFIED":
        return binding.id
    same_claim = (
        predecessor.case_id == binding.case_id
        and predecessor.pedigree_member_id == binding.pedigree_member_id
        and predecessor.specimen_id == binding.specimen_id
        and predecessor.analysis_id == binding.analysis_id
        and predecessor.artifact_id == binding.artifact_id
        and predecessor.source_artifact_sha256 == binding.source_artifact_sha256
        and predecessor.sample_name == binding.sample_name
    )
    return predecessor.id if same_claim else binding.id


def _require_sample_identity_evidence(db: Session, binding_id: UUID) -> list[dict]:
    binding = db.get(PedigreeSampleBinding, binding_id)
    active = _active_sample_identity_evidence(db, binding_id)
    if not active and binding is not None:
        supersedes_binding_id = getattr(binding, "supersedes_binding_id", None)
        if binding.binding_status == "VERIFIED" and supersedes_binding_id is not None:
            predecessor = db.get(PedigreeSampleBinding, supersedes_binding_id)
            if predecessor is not None and predecessor.binding_status == "UNVERIFIED":
                same_claim = (
                    predecessor.case_id == binding.case_id
                    and predecessor.pedigree_member_id == binding.pedigree_member_id
                    and predecessor.specimen_id == binding.specimen_id
                    and predecessor.analysis_id == binding.analysis_id
                    and predecessor.artifact_id == binding.artifact_id
                    and predecessor.source_artifact_sha256 == binding.source_artifact_sha256
                    and predecessor.sample_name == binding.sample_name
                )
                if same_claim:
                    active = _active_sample_identity_evidence(db, predecessor.id)
    summary = []
    for evidence_type in ("CHAIN_OF_CUSTODY", "SAMPLE_IDENTITY_QC"):
        matching = [row for row in active if row.evidence_type == evidence_type]
        if (
            len(matching) != 1
            or matching[0].review_status != "ACCEPTED"
            or matching[0].result != "PASS"
        ):
            raise HTTPException(
                409,
                f"Binding verification requires exactly one reviewer-accepted PASS {evidence_type} record",
            )
        row = matching[0]
        summary.append({
            "evidence_type": row.evidence_type,
            "result": row.result,
            "method": row.method,
            "method_version": row.method_version,
            "evidence_reference": row.evidence_reference,
            "evidence_fingerprint": row.evidence_fingerprint,
            "review_status": row.review_status,
            "reviewed_by": str(row.reviewed_by),
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        })
    return summary


@router.get("/cases/{case_id}/pedigree/sample-bindings/{binding_id}/identity-evidence")
def list_sample_identity_evidence(
    case_id: UUID,
    binding_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Return the immutable identity-evidence revision history for one binding."""
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "read")
    binding = db.get(PedigreeSampleBinding, binding_id)
    if binding is None or binding.case_id != case_id:
        raise HTTPException(404, "Sample binding not found")
    owner_id = _sample_binding_evidence_owner(db, binding)
    rows = db.scalars(
        select(PedigreeSampleIdentityEvidence)
        .where(PedigreeSampleIdentityEvidence.case_id == case_id,
               PedigreeSampleIdentityEvidence.binding_id == owner_id)
        .order_by(PedigreeSampleIdentityEvidence.evidence_type,
                  PedigreeSampleIdentityEvidence.version)
    ).all()
    evidence = [_sample_identity_evidence_payload(row) for row in rows]
    if owner_id != binding_id:
        for item in evidence:
            item["inherited_from_binding_id"] = str(owner_id)
    return {
        "case_id": str(case_id),
        "binding_id": str(binding_id),
        "evidence": evidence,
    }


@router.post("/cases/{case_id}/pedigree/sample-bindings/{binding_id}/identity-evidence", status_code=201)
def create_sample_identity_evidence(
    case_id: UUID,
    binding_id: UUID,
    body: SampleIdentityEvidenceInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Record immutable laboratory chain-of-custody or sample-identity QC evidence."""
    case = db.get(Case, case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    binding = db.get(PedigreeSampleBinding, binding_id)
    if binding is None or binding.case_id != case_id:
        raise HTTPException(404, "Sample binding not found")
    if binding.binding_status != "UNVERIFIED":
        raise HTTPException(409, "Identity evidence can only be attached to an unverified binding")
    if not body.method.strip() or not body.method_version.strip() or not body.evidence_reference.strip():
        raise HTTPException(422, "Identity evidence method, version and reference must be non-empty")
    successor = db.scalar(select(PedigreeSampleBinding).where(
        PedigreeSampleBinding.supersedes_binding_id == binding.id,
    ))
    if successor is not None:
        raise HTTPException(409, "Cannot add evidence to a superseded sample binding")
    if body.source_artifact_id is not None:
        evidence_artifact = db.get(Artifact, body.source_artifact_id)
        if evidence_artifact is None or evidence_artifact.case_id != case_id:
            raise HTTPException(404, "Identity evidence artifact not found in this case")

    evidence_version = 1

    payload = {
        "schema_version": 1, "case_id": str(case_id), "binding_id": str(binding.id),
        "evidence_type": body.evidence_type, "result": body.result,
        "method": body.method.strip(), "method_version": body.method_version.strip(),
        "evidence_reference": body.evidence_reference.strip(),
        "source_artifact_id": str(body.source_artifact_id) if body.source_artifact_id else None,
        "metrics": body.metrics, "review_status": "PENDING", "version": evidence_version,
        "supersedes_evidence_id": None,
    }
    evidence_fingerprint = _sample_identity_evidence_fingerprint(payload)
    existing = db.scalar(select(PedigreeSampleIdentityEvidence).where(
        PedigreeSampleIdentityEvidence.case_id == case_id,
        PedigreeSampleIdentityEvidence.evidence_fingerprint == evidence_fingerprint,
    ))
    if existing is not None:
        return _sample_identity_evidence_payload(existing)
    active_evidence = _active_sample_identity_evidence(db, binding.id)
    if any(row.evidence_type == body.evidence_type for row in active_evidence):
        raise HTTPException(409, "An active evidence revision of this type already exists; append a correction instead")
    row = PedigreeSampleIdentityEvidence(
        id=uuid4(), case_id=case_id, binding_id=binding.id,
        evidence_type=body.evidence_type, result=body.result,
        method=body.method.strip(), method_version=body.method_version.strip(),
        evidence_reference=body.evidence_reference.strip(),
        source_artifact_id=body.source_artifact_id, metrics_json=body.metrics,
        review_status="PENDING", version=evidence_version,
        evidence_fingerprint=evidence_fingerprint, recorded_by=principal.user_id,
    )
    db.add(row)
    AuditService(db).record(
        event_type="PEDIGREE_SAMPLE_IDENTITY_EVIDENCE_RECORDED", case_id=case_id,
        analysis_id=binding.analysis_id, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="PEDIGREE_SAMPLE_IDENTITY_EVIDENCE", subject_id=str(row.id),
        operation="CREATE_PENDING", after_state=_sample_identity_evidence_payload(row),
    )
    create_case_change_candidates(
        db, case=case, trigger_type="PEDIGREE_UPDATE",
        reason="Laboratory sample identity evidence changed; dependent analyses may require reanalysis.",
        metadata={"change_type": "SAMPLE_IDENTITY_EVIDENCE_RECORDED", "evidence_id": str(row.id)},
    )
    db.commit()
    return _sample_identity_evidence_payload(row)


@router.post("/cases/{case_id}/pedigree/sample-bindings/{binding_id}/identity-evidence/{evidence_id}/review", status_code=201)
def review_sample_identity_evidence(
    case_id: UUID,
    binding_id: UUID,
    evidence_id: UUID,
    body: SampleIdentityEvidenceReviewInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Append reviewer acceptance/rejection of laboratory identity evidence."""
    case = db.get(Case, case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "review")
    require_role(principal, REVIEW_ROLES)
    binding = db.get(PedigreeSampleBinding, binding_id)
    if binding is None or binding.case_id != case_id:
        raise HTTPException(404, "Sample binding not found")
    if binding.binding_status != "UNVERIFIED":
        raise HTTPException(409, "Identity evidence review requires an unverified active binding")
    binding_successor = db.scalar(select(PedigreeSampleBinding).where(
        PedigreeSampleBinding.supersedes_binding_id == binding.id,
    ))
    if binding_successor is not None:
        raise HTTPException(409, "Cannot review identity evidence attached to a superseded binding")
    previous = db.get(PedigreeSampleIdentityEvidence, evidence_id)
    if previous is None or previous.case_id != case_id or previous.binding_id != binding_id:
        raise HTTPException(404, "Identity evidence not found for this binding")
    if previous.review_status != "PENDING":
        raise HTTPException(409, "Only pending identity evidence can be reviewed")
    prior_revision = db.scalar(select(PedigreeSampleIdentityEvidence).where(
        PedigreeSampleIdentityEvidence.supersedes_evidence_id == previous.id,
    ))
    if prior_revision is not None:
        if prior_revision.review_status == body.decision and prior_revision.review_reason == body.reason.strip():
            return _sample_identity_evidence_payload(prior_revision)
        raise HTTPException(409, "This identity evidence already has a conflicting review revision")
    if previous.recorded_by == principal.user_id:
        raise HTTPException(403, "Independent reviewer required; the evidence recorder cannot review their own identity evidence")

    payload = {
        "schema_version": 1, "case_id": str(previous.case_id), "binding_id": str(previous.binding_id),
        "evidence_type": previous.evidence_type, "result": previous.result,
        "method": previous.method, "method_version": previous.method_version,
        "evidence_reference": previous.evidence_reference,
        "source_artifact_id": str(previous.source_artifact_id) if previous.source_artifact_id else None,
        "metrics": previous.metrics_json or {}, "review_status": body.decision,
        "review_reason": body.reason.strip(), "version": previous.version + 1,
        "supersedes_evidence_id": str(previous.id),
    }
    row = PedigreeSampleIdentityEvidence(
        id=uuid4(), case_id=previous.case_id, binding_id=previous.binding_id,
        evidence_type=previous.evidence_type, result=previous.result,
        method=previous.method, method_version=previous.method_version,
        evidence_reference=previous.evidence_reference, source_artifact_id=previous.source_artifact_id,
        metrics_json=previous.metrics_json or {}, review_status=body.decision,
        review_reason=body.reason.strip(), version=previous.version + 1,
        supersedes_evidence_id=previous.id,
        evidence_fingerprint=_sample_identity_evidence_fingerprint(payload),
        recorded_by=principal.user_id, reviewed_by=principal.user_id,
        reviewed_at=datetime.now(UTC),
    )
    db.add(row)
    AuditService(db).record(
        event_type="PEDIGREE_SAMPLE_IDENTITY_EVIDENCE_REVIEWED", case_id=case_id,
        analysis_id=binding.analysis_id, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="PEDIGREE_SAMPLE_IDENTITY_EVIDENCE", subject_id=str(row.id),
        operation=body.decision, before_state=_sample_identity_evidence_payload(previous),
        after_state=_sample_identity_evidence_payload(row), reason=body.reason.strip(),
    )
    create_case_change_candidates(
        db, case=case, trigger_type="PEDIGREE_UPDATE",
        reason="Laboratory sample identity evidence review changed; dependent analyses may require reanalysis.",
        metadata={"change_type": "SAMPLE_IDENTITY_EVIDENCE_REVIEWED", "evidence_id": str(row.id)},
    )
    db.commit()
    return _sample_identity_evidence_payload(row)


@router.post("/cases/{case_id}/pedigree/sample-bindings/{binding_id}/identity-evidence/{evidence_id}/supersede", status_code=201)
def supersede_sample_identity_evidence(
    case_id: UUID,
    binding_id: UUID,
    evidence_id: UUID,
    body: SampleIdentityEvidenceInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Append corrected identity evidence; preserve the prior evidence revision."""
    case = db.get(Case, case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    binding = db.get(PedigreeSampleBinding, binding_id)
    if binding is None or binding.case_id != case_id:
        raise HTTPException(404, "Sample binding not found")
    if binding.binding_status != "UNVERIFIED":
        raise HTTPException(409, "Identity evidence correction requires an unverified active binding")
    binding_successor = db.scalar(select(PedigreeSampleBinding).where(
        PedigreeSampleBinding.supersedes_binding_id == binding.id,
    ))
    if binding_successor is not None:
        raise HTTPException(409, "Cannot correct evidence attached to a superseded binding")
    previous = db.get(PedigreeSampleIdentityEvidence, evidence_id)
    if previous is None or previous.case_id != case_id or previous.binding_id != binding_id:
        raise HTTPException(404, "Identity evidence not found for this binding")
    if body.evidence_type != previous.evidence_type:
        raise HTTPException(422, "An identity evidence revision must retain its original evidence type")
    if not body.method.strip() or not body.method_version.strip() or not body.evidence_reference.strip():
        raise HTTPException(422, "Identity evidence method, version and reference must be non-empty")
    if body.source_artifact_id is not None:
        evidence_artifact = db.get(Artifact, body.source_artifact_id)
        if evidence_artifact is None or evidence_artifact.case_id != case_id:
            raise HTTPException(404, "Identity evidence artifact not found in this case")

    payload = {
        "schema_version": 1, "case_id": str(case_id), "binding_id": str(binding.id),
        "evidence_type": body.evidence_type, "result": body.result,
        "method": body.method.strip(), "method_version": body.method_version.strip(),
        "evidence_reference": body.evidence_reference.strip(),
        "source_artifact_id": str(body.source_artifact_id) if body.source_artifact_id else None,
        "metrics": body.metrics, "review_status": "PENDING", "version": previous.version + 1,
        "supersedes_evidence_id": str(previous.id),
    }
    evidence_fingerprint = _sample_identity_evidence_fingerprint(payload)
    existing = db.scalar(select(PedigreeSampleIdentityEvidence).where(
        PedigreeSampleIdentityEvidence.case_id == case_id,
        PedigreeSampleIdentityEvidence.evidence_fingerprint == evidence_fingerprint,
    ))
    if existing is not None:
        return _sample_identity_evidence_payload(existing)
    successor = db.scalar(select(PedigreeSampleIdentityEvidence).where(
        PedigreeSampleIdentityEvidence.supersedes_evidence_id == previous.id,
    ))
    if successor is not None:
        raise HTTPException(409, "This identity evidence already has a conflicting successor revision")
    row = PedigreeSampleIdentityEvidence(
        id=uuid4(), case_id=case_id, binding_id=binding.id,
        evidence_type=body.evidence_type, result=body.result,
        method=body.method.strip(), method_version=body.method_version.strip(),
        evidence_reference=body.evidence_reference.strip(),
        source_artifact_id=body.source_artifact_id, metrics_json=body.metrics,
        review_status="PENDING", version=previous.version + 1,
        supersedes_evidence_id=previous.id, evidence_fingerprint=evidence_fingerprint,
        recorded_by=principal.user_id,
    )
    db.add(row)
    AuditService(db).record(
        event_type="PEDIGREE_SAMPLE_IDENTITY_EVIDENCE_SUPERSEDED", case_id=case_id,
        analysis_id=binding.analysis_id, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="PEDIGREE_SAMPLE_IDENTITY_EVIDENCE", subject_id=str(row.id),
        operation="CREATE_PENDING_SUCCESSOR", before_state=_sample_identity_evidence_payload(previous),
        after_state=_sample_identity_evidence_payload(row),
    )
    create_case_change_candidates(
        db, case=case, trigger_type="PEDIGREE_UPDATE",
        reason="Corrected laboratory identity evidence superseded a prior revision; dependent analyses may require reanalysis.",
        metadata={"change_type": "SAMPLE_IDENTITY_EVIDENCE_SUPERSEDED", "evidence_id": str(row.id)},
    )
    db.commit()
    return _sample_identity_evidence_payload(row)


@router.post("/cases/{case_id}/pedigree/sample-bindings/{binding_id}/review", status_code=201)
def review_sample_binding(case_id: UUID, binding_id: UUID, body: SampleBindingReviewInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    """Append a reviewed identity revision; never mutate the prior claim."""
    case = db.get(Case, case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "review")
    require_role(principal, REVIEW_ROLES)
    previous = db.get(PedigreeSampleBinding, binding_id)
    if previous is None or previous.case_id != case_id:
        raise HTTPException(404, "Sample binding not found")
    if previous.binding_status != "UNVERIFIED":
        raise HTTPException(409, "Only an unverified binding can be reviewed")
    prior_revision = db.scalar(select(PedigreeSampleBinding).where(
        PedigreeSampleBinding.supersedes_binding_id == previous.id,
    ))
    if prior_revision is not None:
        if prior_revision.binding_status == body.decision and prior_revision.review_reason == body.reason.strip():
            return _sample_binding_payload(prior_revision)
        raise HTTPException(409, "This binding already has a conflicting review revision")
    if previous.recorded_by == principal.user_id:
        raise HTTPException(403, "Independent reviewer required; the binding recorder cannot approve their own identity claim")
    if body.decision == "VERIFIED":
        analysis = db.get(Analysis, previous.analysis_id)
        if analysis is None or (analysis.configuration or {}).get("input_artifact_id") != str(previous.artifact_id):
            raise HTTPException(409, "Binding source artifact is no longer the selected analysis input")
        selected_sample = (analysis.configuration or {}).get("vcf_sample_name")
        if selected_sample != previous.sample_name:
            raise HTTPException(409, "Binding sample name differs from the analysis-selected sample")
        artifact = db.get(Artifact, previous.artifact_id)
        if artifact is None or artifact.case_id != case_id:
            raise HTTPException(409, "The bound source VCF artifact is no longer available in this case")
        if artifact.sha256 != previous.source_artifact_sha256:
            raise HTTPException(409, "The source VCF digest differs from the immutable identity claim")
        if artifact.specimen_id is not None and artifact.specimen_id != previous.specimen_id:
            raise HTTPException(409, "Source VCF artifact is linked to a different specimen")
        normalization_step = db.scalar(select(WorkflowStep).where(
            WorkflowStep.analysis_id == previous.analysis_id,
            WorkflowStep.step_id == "normalize",
        ))
        if (
            normalization_step is None
            or normalization_step.status != "SUCCEEDED"
            or str(previous.artifact_id) not in (normalization_step.input_artifacts or [])
        ):
            raise HTTPException(409, "No successful normalization provenance links this source VCF to the analysis")
        calls = get_analysis_sample_calls(db, previous.analysis_id)
        if not any(call.get("sample_name") == previous.sample_name for call in calls.values()):
            raise HTTPException(409, "No normalized calls contain the analysis-selected VCF sample")
        accepted_identity_evidence = _require_sample_identity_evidence(db, previous.id)
    version = previous.version + 1
    payload = {
        "schema_version": 1, "case_id": str(previous.case_id),
        "member_id": str(previous.pedigree_member_id), "specimen_id": str(previous.specimen_id),
        "analysis_id": str(previous.analysis_id), "artifact_id": str(previous.artifact_id),
        "source_artifact_sha256": previous.source_artifact_sha256,
        "sample_name": previous.sample_name, "binding_status": body.decision,
        "binding_method": previous.binding_method, "evidence_reference": previous.evidence_reference,
        "review_reason": body.reason.strip(), "version": version,
        "supersedes_binding_id": str(previous.id),
    }
    row = PedigreeSampleBinding(
        id=uuid4(), case_id=previous.case_id, pedigree_member_id=previous.pedigree_member_id,
        specimen_id=previous.specimen_id, analysis_id=previous.analysis_id, artifact_id=previous.artifact_id,
        source_artifact_sha256=previous.source_artifact_sha256, sample_name=previous.sample_name, binding_status=body.decision,
        binding_method=previous.binding_method, evidence_reference=previous.evidence_reference,
        review_reason=body.reason.strip(), version=version, supersedes_binding_id=previous.id,
        binding_fingerprint=_sample_binding_fingerprint(payload), recorded_by=principal.user_id,
        reviewed_by=principal.user_id, reviewed_at=datetime.now(UTC),
    )
    db.add(row)
    AuditService(db).record(
        event_type="PEDIGREE_SAMPLE_BINDING_REVIEWED", case_id=case_id,
        analysis_id=previous.analysis_id, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="PEDIGREE_SAMPLE_BINDING", subject_id=str(row.id),
        operation=body.decision, before_state=_sample_binding_payload(previous),
        after_state=_sample_binding_payload(row), reason=body.reason.strip(),
        payload={"accepted_identity_evidence": accepted_identity_evidence} if body.decision == "VERIFIED" else {},
    )
    create_case_change_candidates(
        db, case=case, trigger_type="PEDIGREE_UPDATE",
        reason="Family sample identity review changed; analyses may require reanalysis.",
        metadata={"change_type": "SAMPLE_BINDING_REVIEWED", "binding_id": str(row.id)},
    )
    db.commit()
    return _sample_binding_payload(row)


@router.post("/cases/{case_id}/pedigree/genotype-matrix")
def get_family_genotype_matrix(
    case_id: UUID,
    body: GenotypeMatrixInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Compose normalized sample calls from explicitly selected verified family bindings."""
    if len(set(body.binding_ids)) != len(body.binding_ids):
        raise HTTPException(422, "Binding IDs must be unique")
    if len(set(body.variant_ids)) != len(body.variant_ids):
        raise HTTPException(422, "Variant IDs must be unique")

    case = db.get(Case, case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "read")

    variants = {}
    for variant_id in body.variant_ids:
        variant = db.get(Variant, variant_id)
        if variant is None:
            raise HTTPException(404, "Canonical variant not found")
        variants[variant_id] = variant

    samples = []
    for binding_id in body.binding_ids:
        binding = db.get(PedigreeSampleBinding, binding_id)
        if binding is None or binding.case_id != case_id:
            raise HTTPException(404, "Sample binding not found in this case")
        if binding.binding_status != "VERIFIED":
            raise HTTPException(409, "Only reviewed VERIFIED sample bindings can enter the family genotype matrix")
        successor = db.scalar(select(PedigreeSampleBinding).where(
            PedigreeSampleBinding.supersedes_binding_id == binding.id,
        ))
        if successor is not None:
            raise HTTPException(409, "A superseded sample binding cannot be used in a current genotype matrix")
        member = db.get(PedigreeMember, binding.pedigree_member_id)
        specimen = db.get(Specimen, binding.specimen_id)
        analysis = db.get(Analysis, binding.analysis_id)
        artifact = db.get(Artifact, binding.artifact_id)
        if (
            member is None or member.case_id != case_id
            or specimen is None or specimen.case_id != case_id
            or analysis is None or analysis.case_id != case_id
            or artifact is None or artifact.case_id != case_id
        ):
            raise HTTPException(409, "A selected sample binding references inconsistent case-scoped records")
        if artifact.sha256 != binding.source_artifact_sha256:
            raise HTTPException(409, "Source VCF digest no longer matches the reviewed sample binding")
        if not isinstance(artifact.sha256, str) or len(artifact.sha256) != 64 or any(character not in "0123456789abcdefABCDEF" for character in artifact.sha256):
            raise HTTPException(409, "Reviewed source VCF artifact has no valid SHA-256 digest")
        configuration = analysis.configuration or {}
        if (
            configuration.get("input_artifact_id") != str(artifact.id)
            or configuration.get("vcf_sample_name") != binding.sample_name
        ):
            raise HTTPException(409, "Analysis input artifact or VCF sample selection differs from the reviewed binding")
        if artifact.specimen_id is not None and artifact.specimen_id != specimen.id:
            raise HTTPException(409, "Source VCF artifact is linked to a different specimen")

        normalization_step = db.scalar(select(WorkflowStep).where(
            WorkflowStep.analysis_id == analysis.id,
            WorkflowStep.step_id == "normalize",
        ))
        if (
            normalization_step is None
            or normalization_step.status != "SUCCEEDED"
            or str(artifact.id) not in (normalization_step.input_artifacts or [])
        ):
            raise HTTPException(409, "The source VCF has no successful normalization provenance for this analysis")
        partitions = db.scalars(select(AnalysisPartition).where(
            AnalysisPartition.analysis_id == analysis.id,
            AnalysisPartition.step_id == "normalize",
        ).order_by(AnalysisPartition.ordinal)).all()
        partition_input_artifact_ids = sorted({
            str(partition.input_artifact_id)
            for partition in partitions
            if partition.input_artifact_id is not None
        })
        normalization_output_artifact_ids = {
            str(value) for value in (normalization_step.output_artifacts or [])
        }
        if (
            not partitions
            or not partition_input_artifact_ids
            or not set(partition_input_artifact_ids).issubset(normalization_output_artifact_ids)
            or int(normalization_step.attempt or 0) < 1
        ):
            raise HTTPException(
                409,
                "Normalized partitions are not bound to the successful normalization attempt output artifacts",
            )
        calls = get_analysis_sample_calls(db, analysis.id)
        if not calls or any(call.get("sample_name") != binding.sample_name for call in calls.values()):
            raise HTTPException(409, "Normalized sample calls do not consistently identify the selected VCF sample")
        identity_evidence = _require_sample_identity_evidence(db, binding.id)
        for variant in variants.values():
            if variant.genome_build != analysis.reference_build:
                raise HTTPException(409, "Requested variant assembly does not match every selected family analysis")

        ploidy_rows = db.scalars(select(SpecimenPloidyEvidenceRevision).where(
            SpecimenPloidyEvidenceRevision.specimen_id == specimen.id,
        ).order_by(SpecimenPloidyEvidenceRevision.version.desc())).all()
        ploidy_evidence = None
        if ploidy_rows:
            latest = ploidy_rows[0]
            ploidy_evidence = {
                "version": latest.version,
                "status": latest.status,
                "reference_build": latest.reference_build,
                "revision_fingerprint": latest.revision_fingerprint,
                "region_copy_number": latest.region_copy_number,
                "source_type": latest.source_type,
                "evidence_reference": latest.evidence_reference,
                "recorded_by": str(latest.recorded_by),
                "recorded_at": latest.recorded_at.isoformat() if latest.recorded_at else None,
                "reviewed_by": str(latest.reviewed_by) if latest.reviewed_by else None,
                "reviewed_at": latest.reviewed_at.isoformat() if latest.reviewed_at else None,
            }

        samples.append({
            "member_id": member.id,
            "member_identifier": member.member_identifier,
            "relationship_to_proband": member.relationship_to_proband,
            "sex": member.sex,
            "affected_status": member.affected_status,
            "is_proband": member.is_proband,
            "specimen_id": specimen.id,
            "analysis_id": analysis.id,
            "analysis_version": analysis.analysis_version,
            "analysis_reference_build": analysis.reference_build,
            "artifact_id": artifact.id,
            "artifact_sha256": artifact.sha256,
            "sample_name": binding.sample_name,
            "binding_id": binding.id,
            "binding_fingerprint": binding.binding_fingerprint,
            "normalization_step_status": normalization_step.status,
            "normalization_step_provenance": {
                "step_id": normalization_step.step_id,
                "attempt": normalization_step.attempt,
                "input_artifacts": normalization_step.input_artifacts or [],
                "output_artifacts": normalization_step.output_artifacts or [],
                "metadata": normalization_step.metadata_json or {},
                "started_at": normalization_step.started_at.isoformat() if normalization_step.started_at else None,
                "completed_at": normalization_step.completed_at.isoformat() if normalization_step.completed_at else None,
            },
            "normalized_partition_count": len(partitions),
            "normalized_partition_input_artifact_ids": partition_input_artifact_ids,
            "ploidy_evidence": ploidy_evidence,
            "identity_evidence": identity_evidence,
            "calls": calls,
        })

    members = db.scalars(select(PedigreeMember).where(
        PedigreeMember.case_id == case_id,
    )).all()
    member_identifiers = {member.id: member.member_identifier for member in members}
    relationships = db.scalars(select(PedigreeRelationship).where(
        PedigreeRelationship.case_id == case_id,
    )).all()
    relationship_snapshot = [{
        "parent_member_identifier": member_identifiers.get(item.parent_member_id, "UNKNOWN_MEMBER"),
        "child_member_identifier": member_identifiers.get(item.child_member_id, "UNKNOWN_MEMBER"),
        "relationship_type": item.relationship_type,
        "metadata": item.metadata_json or {},
        "relationship_status": "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
    } for item in relationships]

    return build_family_genotype_matrix(
        case_id=case_id,
        variant_ids=body.variant_ids,
        samples=samples,
        relationships=relationship_snapshot,
    )


@router.get("/cases/{case_id}/pedigree")
def get_pedigree(case_id: UUID, db: Session=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    case=db.get(Case,case_id)
    if not case: raise HTTPException(404,"Case not found")
    require_case_permission(case, principal, db, "read")
    members=list(db.scalars(select(PedigreeMember).where(PedigreeMember.case_id==case_id).order_by(PedigreeMember.created_at,PedigreeMember.member_identifier)))
    rels=list(db.scalars(select(PedigreeRelationship).where(PedigreeRelationship.case_id==case_id).order_by(PedigreeRelationship.created_at)))
    _validate_pedigree_lineage(members, rels, case_id, db)
    return {"case_id":str(case_id),"members":[_member(m) for m in members],"relationships":[_relationship(r) for r in rels]}

@router.post("/cases/{case_id}/pedigree/members",status_code=201)
def add_member(case_id: UUID, body: MemberInput, db: Session=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    # Report drafts include the pedigree. Serialize member edits with report
    # generation and sign-out through the shared case-row lock.
    case=db.get(Case,case_id,with_for_update=True)
    if not case: raise HTTPException(404,"Case not found")
    db.refresh(case,with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    if body.specimen_id:
        specimen = db.get(Specimen, body.specimen_id)
        if not specimen or specimen.case_id != case_id:
            raise HTTPException(status_code=404, detail="Specimen not found in this case")
    if db.scalar(select(PedigreeMember).where(PedigreeMember.case_id==case_id,PedigreeMember.member_identifier==body.member_identifier.strip())):
        raise HTTPException(409,"Pedigree member identifier already exists")
    if body.is_proband and db.scalar(select(PedigreeMember).where(PedigreeMember.case_id==case_id,PedigreeMember.is_proband.is_(True))):
        raise HTTPException(409,"A case can have only one designated proband")
    row=PedigreeMember(id=uuid4(),case_id=case_id,member_identifier=body.member_identifier.strip(),relationship_to_proband=body.relationship_to_proband,sex=body.sex,affected_status=body.affected_status,is_proband=body.is_proband,sampled=body.sampled,specimen_id=body.specimen_id,metadata_json=body.metadata)
    db.add(row)
    AuditService(db).record(event_type="PEDIGREE_MEMBER_ADDED",case_id=case_id,analysis_id=None,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="PEDIGREE_MEMBER",subject_id=str(row.id),operation="CREATE",after_state=_member(row))
    create_case_change_candidates(
        db,
        case=case,
        trigger_type="PEDIGREE_UPDATE",
        reason=f"Family member context for case {case_id} changed; completed analyses may require reanalysis.",
        metadata={"change_type": "MEMBER_ADDED", "member_id": str(row.id)},
    )
    db.commit(); return _member(row)

@router.post("/cases/{case_id}/pedigree/relationships",status_code=201)
def add_relationship(case_id: UUID, body: RelationshipInput, db: Session=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    require_role(principal, CASE_WRITE_ROLES)
    # Serialize edits to one pedigree so concurrent writes cannot each pass a
    # cycle check against a stale graph and jointly create a cycle.
    case=db.get(Case,case_id,with_for_update=True)
    if not case: raise HTTPException(404,"Case not found")
    db.refresh(case,with_for_update=True)
    require_case_permission(case, principal, db, "write")
    parent=db.get(PedigreeMember,body.parent_member_id); child=db.get(PedigreeMember,body.child_member_id)
    if not parent or not child or parent.case_id!=case_id or child.case_id!=case_id or parent.id==child.id: raise HTTPException(400,"Parent and child must be distinct members in the same case")
    relationships = db.scalars(
        select(PedigreeRelationship).where(PedigreeRelationship.case_id == case_id)
    ).all()
    if _would_create_pedigree_cycle(relationships, parent.id, child.id):
        raise HTTPException(
            status_code=409,
            detail="Pedigree relationship would create a parentage cycle",
        )
    if db.scalar(select(PedigreeRelationship).where(PedigreeRelationship.case_id==case_id,PedigreeRelationship.parent_member_id==parent.id,PedigreeRelationship.child_member_id==child.id)):
        raise HTTPException(409,"Pedigree relationship already exists")
    row=PedigreeRelationship(id=uuid4(),case_id=case_id,parent_member_id=parent.id,child_member_id=child.id,relationship_type=body.relationship_type,metadata_json=body.metadata)
    db.add(row)
    AuditService(db).record(event_type="PEDIGREE_RELATIONSHIP_ADDED",case_id=case_id,analysis_id=None,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="PEDIGREE_RELATIONSHIP",subject_id=str(row.id),operation="CREATE",after_state=_relationship(row))
    create_case_change_candidates(
        db,
        case=case,
        trigger_type="PEDIGREE_UPDATE",
        reason=f"Family relationships for case {case_id} changed; completed analyses may require reanalysis.",
        metadata={"change_type": "RELATIONSHIP_ADDED", "relationship_id": str(row.id)},
    )
    db.commit(); return _relationship(row)

@router.get("/analyses/{analysis_id}/variants/{variant_id}/segregation")
def get_segregation(
    analysis_id: UUID,
    variant_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    require_role(principal, READ_ROLES)
    get_analysis_variant(analysis, variant_id, db)
    roots = list(db.scalars(
        select(SegregationObservation)
        .where(
            SegregationObservation.analysis_id == analysis_id,
            SegregationObservation.variant_id == variant_id,
        )
        .order_by(SegregationObservation.created_at)
    ))
    members = {
        member.id: member
        for member in db.scalars(
            select(PedigreeMember).where(PedigreeMember.case_id == analysis.case_id)
        )
    }
    _validate_observation_members(roots, members)
    root_ids = [row.id for row in roots]
    revisions = (
        list(db.scalars(
            select(SegregationObservationRevision)
            .where(SegregationObservationRevision.root_observation_id.in_(root_ids))
            .order_by(
                SegregationObservationRevision.root_observation_id,
                SegregationObservationRevision.version,
            )
        ))
        if root_ids else []
    )
    revisions_by_root = {}
    for revision in revisions:
        revisions_by_root.setdefault(revision.root_observation_id, []).append(revision)

    current_observations = []
    observation_history = []
    for root in roots:
        member = members.get(root.pedigree_member_id)
        root_payload = _seg(root, member)
        root_payload.update({
            "revision_id": None,
            "revision_version": 1,
            "observation_fingerprint": (root.metadata_json or {}).get("observation_fingerprint"),
        })
        history = [root_payload]
        for revision in revisions_by_root.get(root.id, []):
            history.append(_segregation_revision_payload(root, revision, member))
        observation_history.extend(history)
        current_observations.append(history[-1])

    assessments = list(db.scalars(
        select(InheritanceAssessment)
        .where(
            InheritanceAssessment.analysis_id == analysis_id,
            InheritanceAssessment.variant_id == variant_id,
        )
        .order_by(InheritanceAssessment.created_at.desc())
    ))
    return {
        "analysis_id": str(analysis_id),
        "variant_id": str(variant_id),
        "observations": current_observations,
        "observation_history": observation_history,
        "assessments": [
            {
                "id": str(item.id),
                "model": item.model,
                "status": item.status,
                "rationale": item.rationale,
                "fingerprint": item.observation_fingerprint,
                "reviewer_note": item.reviewer_note,
                "created_by": item.created_by,
                "created_at": item.created_at.isoformat(),
                "family_matrix_fingerprint": item.family_matrix_fingerprint,
                "family_matrix_snapshot_id": (
                    str(item.family_matrix_snapshot_id)
                    if item.family_matrix_snapshot_id else None
                ),
            }
            for item in assessments
        ],
    }


def _segregation_observation_fingerprint(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _segregation_revision_payload(root, revision, member) -> dict:
    payload = revision.payload or {}
    return {
        "id": str(root.id),
        "revision_id": str(revision.id),
        "revision_version": revision.version,
        "revision_reason": revision.revision_reason,
        "supersedes_revision_id": (
            str(revision.supersedes_revision_id)
            if revision.supersedes_revision_id else None
        ),
        "observation_fingerprint": revision.observation_fingerprint,
        "pedigree_member_id": str(root.pedigree_member_id),
        "member_identifier": member.member_identifier if member else None,
        "genotype": payload.get("genotype"),
        "zygosity": payload.get("zygosity"),
        "phase": payload.get("phase"),
        "allele_observed": payload.get("allele_observed"),
        "phenotype_status": payload.get("phenotype_status"),
        "source": "MANUALLY_REPORTED",
        "notes": payload.get("notes"),
        "metadata": payload.get("metadata") or {},
    }


@router.post("/analyses/{analysis_id}/variants/{variant_id}/segregation", status_code=201)
def add_segregation(
    analysis_id: UUID,
    variant_id: UUID,
    body: SegregationInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    require_role(principal, CASE_WRITE_ROLES)
    analysis = _lock_analysis_for_pedigree(db, analysis_id, principal, "write")
    get_analysis_variant(analysis, variant_id, db)
    member = db.get(PedigreeMember, body.pedigree_member_id)
    if not member or member.case_id != analysis.case_id:
        raise HTTPException(
            400,
            "Variant and pedigree member must belong to this analysis/case",
        )

    payload = {
        "genotype": body.genotype,
        "zygosity": body.zygosity,
        "phase": body.phase,
        "allele_observed": body.allele_observed,
        "phenotype_status": body.phenotype_status,
        "source": "MANUALLY_REPORTED",
        "notes": body.notes,
        "metadata": {
            **body.metadata,
            "pedigree_context_snapshot": _pedigree_context_snapshot(db, analysis.case_id),
        },
    }
    observation_fingerprint = _segregation_observation_fingerprint(payload)
    root = db.scalar(
        select(SegregationObservation).where(
            SegregationObservation.analysis_id == analysis_id,
            SegregationObservation.variant_id == variant_id,
            SegregationObservation.pedigree_member_id == member.id,
        )
    )

    if root is None:
        root_metadata = {
            **payload["metadata"],
            "observation_fingerprint": observation_fingerprint,
        }
        row = SegregationObservation(
            id=uuid4(),
            analysis_id=analysis_id,
            variant_id=variant_id,
            pedigree_member_id=member.id,
            genotype=payload["genotype"],
            zygosity=payload["zygosity"],
            phase=payload["phase"],
            allele_observed=payload["allele_observed"],
            phenotype_status=payload["phenotype_status"],
            source="MANUALLY_REPORTED",
            notes=payload["notes"],
            metadata_json=root_metadata,
        )
        db.add(row)
        AuditService(db).record(
            event_type="SEGREGATION_OBSERVATION_RECORDED",
            case_id=analysis.case_id,
            analysis_id=analysis_id,
            actor_type="HUMAN",
            actor_id=str(principal.user_id),
            subject_type="SEGREGATION_OBSERVATION",
            subject_id=str(row.id),
            operation="CREATE_VERSION_1",
            after_state={
                **_seg(row, member),
                "revision_version": 1,
                "observation_fingerprint": observation_fingerprint,
            },
        )
        db.commit()
        return {
            **_seg(row, member),
            "revision_id": None,
            "revision_version": 1,
            "observation_fingerprint": observation_fingerprint,
        }

    revisions = list(db.scalars(
        select(SegregationObservationRevision)
        .where(SegregationObservationRevision.root_observation_id == root.id)
        .order_by(SegregationObservationRevision.version.desc())
    ))
    latest = revisions[0] if revisions else None
    current_fingerprint = (
        latest.observation_fingerprint
        if latest is not None
        else (root.metadata_json or {}).get("observation_fingerprint")
    )
    if current_fingerprint is None:
        current_payload = {
            "genotype": root.genotype,
            "zygosity": root.zygosity,
            "phase": root.phase,
            "allele_observed": root.allele_observed,
            "phenotype_status": root.phenotype_status,
            "source": "MANUALLY_REPORTED",
            "notes": root.notes,
            "metadata": root.metadata_json or {},
        }
        current_fingerprint = _segregation_observation_fingerprint(current_payload)
    if current_fingerprint == observation_fingerprint:
        if latest is not None:
            return _segregation_revision_payload(root, latest, member)
        return {
            **_seg(root, member),
            "revision_id": None,
            "revision_version": 1,
            "revision_reason": None,
            "observation_fingerprint": current_fingerprint,
        }

    if not body.revision_reason or not body.revision_reason.strip():
        raise HTTPException(
            422,
            "A non-empty correction reason is required to supersede a segregation observation",
        )

    revision = SegregationObservationRevision(
        id=uuid4(),
        root_observation_id=root.id,
        supersedes_revision_id=latest.id if latest is not None else None,
        version=(latest.version + 1) if latest is not None else 2,
        revision_reason=body.revision_reason.strip(),
        payload=payload,
        observation_fingerprint=observation_fingerprint,
        recorded_by=principal.user_id,
    )
    db.add(revision)
    AuditService(db).record(
        event_type="SEGREGATION_OBSERVATION_SUPERSEDED",
        case_id=analysis.case_id,
        analysis_id=analysis_id,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="SEGREGATION_OBSERVATION",
        subject_id=str(root.id),
        operation=f"CREATE_VERSION_{revision.version}",
        before_state=(
            _segregation_revision_payload(root, latest, member)
            if latest is not None else _seg(root, member)
        ),
        after_state=_segregation_revision_payload(root, revision, member),
        reason=revision.revision_reason,
    )
    db.commit()
    return _segregation_revision_payload(root, revision, member)

@router.post("/analyses/{analysis_id}/variants/{variant_id}/inheritance/assess")
def assess_inheritance(analysis_id: UUID,variant_id: UUID,body: AssessmentInput,db: Session=Depends(get_db),principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id,db,principal, "review")
    require_role(principal, REVIEW_ROLES)
    models = []
    for raw_model in body.models:
        try:
            model = normalize_model(raw_model)
            if model == "MITOCHONDRIAL":
                raise ValueError("Mitochondrial interpretation is outside the qualified SNV/INDEL trial scope")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if model in models:
            raise HTTPException(400, f"Duplicate inheritance model: {model}")
        models.append(model)
    # Lock case before analysis and matrix projection to serialize this
    # review against concurrent family-binding changes. Model validation above
    # intentionally runs before any database read.
    case = db.get(Case, analysis.case_id, with_for_update=True)
    if case is None:
        raise HTTPException(404, "Case not found")
    db.refresh(case, with_for_update=True)
    analysis = _lock_analysis_for_pedigree(db, analysis_id, principal, "review")
    get_analysis_variant(analysis,variant_id,db)
    rows=list(db.scalars(select(SegregationObservation).where(SegregationObservation.analysis_id==analysis_id,SegregationObservation.variant_id==variant_id)))
    members={m.id:m for m in db.scalars(select(PedigreeMember).where(PedigreeMember.case_id==analysis.case_id))}
    _validate_observation_members(rows, members)

    family_matrix = None
    family_matrix_snapshot = None
    if body.binding_ids:
        if len(set(body.binding_ids)) != len(body.binding_ids):
            raise HTTPException(422, "Family binding IDs must be unique")
        family_matrix = get_family_genotype_matrix(
            analysis.case_id,
            GenotypeMatrixInput(binding_ids=body.binding_ids, variant_ids=[variant_id]),
            db,
            principal,
        )
        proband_samples = [
            sample for sample in family_matrix["samples"]
            if sample["is_proband"] and sample["analysis_id"] == str(analysis_id)
        ]
        if len(proband_samples) != 1:
            raise HTTPException(
                409,
                "Inheritance review requires exactly one verified proband binding from the target analysis",
            )
        if family_matrix.get("provenance_completeness_status") != "COMPLETE":
            raise HTTPException(
                409,
                "Inheritance review requires complete source-artifact, normalization-output and per-record digest provenance",
            )
        family_matrix_snapshot = db.scalar(select(FamilyGenotypeMatrixSnapshot).where(
            FamilyGenotypeMatrixSnapshot.case_id == analysis.case_id,
            FamilyGenotypeMatrixSnapshot.matrix_fingerprint == family_matrix["matrix_fingerprint"],
        ))
        if family_matrix_snapshot is None:
            family_matrix_snapshot = FamilyGenotypeMatrixSnapshot(
                id=uuid4(),
                case_id=analysis.case_id,
                analysis_id=analysis_id,
                variant_id=variant_id,
                schema_version=family_matrix["schema_version"],
                matrix_fingerprint=family_matrix["matrix_fingerprint"],
                matrix_payload=family_matrix,
                created_by=principal.user_id,
            )
            db.add(family_matrix_snapshot)

    # Manually entered SegregationObservation rows remain reviewer notes only.
    # They are never converted into normalized calls or inheritance evidence.
    obs=[]
    observation_fp=fingerprint(obs)
    family_matrix_fp=family_matrix["matrix_fingerprint"] if family_matrix else None
    family_matrix_snapshot_id=family_matrix_snapshot.id if family_matrix_snapshot else None
    fp = (
        hashlib.sha256(json.dumps({
            "schema_version": 2,
            "manual_observation_fingerprint": observation_fp,
            "family_matrix_fingerprint": family_matrix_fp,
        },sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if family_matrix_fp else observation_fp
    )
    results=[]; audit_changes=[]
    for model in models:
        result=assess_model(model,obs)
        # The matrix is source-bound context, not a qualified inheritance model.
        # Do not issue compatibility conclusions even when calls are present.
        result = {
            **result,
            "status": "REQUIRES_REVIEW",
            "rationale": (
                "A verified family genotype matrix is attached as reproducible evidence context. "
                "Automated inheritance compatibility is not qualified; review disease mechanism, "
                "penetrance, age, pedigree relationship confidence, phase, ploidy and callability."
                if family_matrix else
                "No verified family genotype matrix was supplied. Manually reported genotype fields "
                "are not source evidence; review the missing identity, genotype and disease-specific evidence."
            ),
        }
        row=db.scalar(select(InheritanceAssessment).where(
            InheritanceAssessment.analysis_id==analysis_id,
            InheritanceAssessment.variant_id==variant_id,
            InheritanceAssessment.model==model,
            InheritanceAssessment.observation_fingerprint==fp,
        ))
        if row is None:
            row=InheritanceAssessment(id=uuid4(),analysis_id=analysis_id,variant_id=variant_id,model=model,status=result["status"],score=None,rationale=result["rationale"],observation_fingerprint=fp,family_matrix_fingerprint=family_matrix_fp,family_matrix_snapshot_id=family_matrix_snapshot_id,reviewer_note=body.reviewer_note,created_by=str(principal.user_id))
            db.add(row)
            audit_changes.append({"operation":"CREATE","assessment_id":str(row.id),"after_state":{"model":model,"status":result["status"],"reviewer_note":body.reviewer_note,"observation_fingerprint":fp,"family_matrix_fingerprint":family_matrix_fp,"family_matrix_snapshot_id":str(family_matrix_snapshot_id) if family_matrix_snapshot_id else None}})
        elif row.reviewer_note != body.reviewer_note:
            before_state={"model":row.model,"status":row.status,"reviewer_note":row.reviewer_note,"observation_fingerprint":row.observation_fingerprint}
            row.reviewer_note=body.reviewer_note
            audit_changes.append({"operation":"UPDATE","assessment_id":str(row.id),"before_state":before_state,"after_state":{"model":model,"status":row.status,"reviewer_note":row.reviewer_note,"observation_fingerprint":fp}})
        results.append({"id":str(row.id),**result,"fingerprint":fp,"reviewer_note":row.reviewer_note})
        # Store only neutral pointers to the immutable matrix snapshot and the
        # separately labeled manual review notes; neither is a calculated
        # segregation or inheritance criterion.
        payload={"model":model,"status":"REQUIRES_REVIEW","observations_available":result["observations_available"],"observation_fingerprint":fp,"family_matrix_fingerprint":family_matrix_fp,"family_matrix_snapshot_id":str(family_matrix_snapshot_id) if family_matrix_snapshot_id else None,"family_matrix_binding_ids":sorted(str(value) for value in body.binding_ids),"reviewer_note":body.reviewer_note,"interpretation":"REQUIRES_HUMAN_REVIEW","manual_segregation_rows_excluded":True,"manual_segregation_observation_ids":[str(r.id) for r in rows]}
        evidence_fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        stmt=select(Evidence).where(Evidence.analysis_id==analysis_id,Evidence.variant_id==variant_id,Evidence.evidence_type=="SEGREGATION",Evidence.evidence_fingerprint==evidence_fingerprint)
        if not db.scalar(stmt):
            db.add(Evidence(id=uuid4(),variant_id=variant_id,analysis_id=analysis_id,evidence_type="SEGREGATION",statement=f"Family observations recorded for {model}; disease-specific interpretation requires human review.",direction="CONTEXTUAL",source_name="SIRALOOM Pedigree Observation Workflow",source_version="M12_FAMILY_MATRIX_REVIEW_CONTEXT",source_record_id=None,observation_ids=[],payload=payload,created_by_type="SYSTEM",created_by_id="inheritance",evidence_fingerprint=evidence_fingerprint))
    if audit_changes:
        AuditService(db).record(event_type="INHERITANCE_ASSESSMENT_RECORDED",case_id=analysis.case_id,analysis_id=analysis_id,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="VARIANT_INHERITANCE",subject_id=str(variant_id),operation="UPSERT",after_state={"changes":audit_changes,"observation_fingerprint":fp},reason=body.reviewer_note)
    db.commit(); return {"analysis_id":str(analysis_id),"variant_id":str(variant_id),"observation_fingerprint":fp,"family_matrix_fingerprint":family_matrix_fp,"family_matrix_snapshot_id":str(family_matrix_snapshot_id) if family_matrix_snapshot_id else None,"family_matrix_attached":family_matrix is not None,"results":results,"important_note":"Inheritance remains REQUIRES_REVIEW. The family matrix is provenance-bearing context only; no automated compatibility conclusion or ACMG/ClinGen criterion is generated. Review disease-specific mechanism, penetrance, age, relationship confidence, phase, ploidy and callability."}
