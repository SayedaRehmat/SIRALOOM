from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.clingen.cspec import CSpecClient, CSpecClientError
from backend.app.acmg.clingen_registry import fetch_ruleset
from backend.app.acmg.specification_selection import ClinGenSpecificationSelector, validate_snapshot_for_automation
from backend.app.infrastructure.db.models import ClinGenSpecification
from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.audit.service import AuditService

router = APIRouter(tags=["clingen"])

class ClinGenImportRequest(BaseModel):
    ruleset_id: str = Field(min_length=1)
    activate_for_automation: bool = False

class ClinGenValidationRequest(BaseModel):
    approved_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    validation_reference: str | None = None

@router.post("/clingen/specifications/import")
def import_specification(payload: ClinGenImportRequest, db: Session = Depends(get_db)):
    try:
        snapshot = fetch_ruleset(CSpecClient(), payload.ruleset_id)
    except (CSpecClientError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    existing = db.scalar(select(ClinGenSpecification).where(ClinGenSpecification.specification_id == snapshot.specification_id, ClinGenSpecification.version == snapshot.version))
    row = existing or ClinGenSpecification(id=uuid4(), specification_id=snapshot.specification_id, version=snapshot.version)
    row.provider = snapshot.provider; row.framework = snapshot.framework; row.source_iri = snapshot.source_iri
    row.modified_at = snapshot.modified_at; row.gene_scope = list(snapshot.gene_scope); row.disease_scope = list(snapshot.disease_scope)
    row.criteria = snapshot.criteria; row.raw_payload = snapshot.raw_entity
    row.retrieved_at = datetime.now(timezone.utc)
    row.validated_for_automation = False
    row.validation_status = "UNVALIDATED"
    db.add(row)
    AuditService(db).record(event_type="CLINGEN_SPECIFICATION_IMPORTED", case_id=None, analysis_id=None, actor_type="SYSTEM", actor_id="siraloom-clingen", subject_type="CLINGEN_SPECIFICATION", subject_id=str(row.id), operation="IMPORT", after_state={"specification_id": row.specification_id, "version": row.version, "validated_for_automation": False}, reason="Imported from ClinGen Criteria Specification Registry")
    db.commit()
    return {"id": str(row.id), "specification_id": row.specification_id, "version": row.version, "validated_for_automation": row.validated_for_automation, "validation_status": row.validation_status, "criteria": sorted(row.criteria), "gene_scope": row.gene_scope, "disease_scope": row.disease_scope}

@router.get("/clingen/specifications/select")
def select_specification(gene: str, disease: str | None = None, db: Session = Depends(get_db)):
    result = ClinGenSpecificationSelector().select(db, gene=gene, disease=disease)
    return {
        "status": result.status,
        "reason": result.reason,
        "selected": result.selected.__dict__ if result.selected else None,
        "candidates": [c.__dict__ for c in result.candidates],
    }

@router.post("/clingen/specifications/{specification_id}/validate")
def validate_specification(specification_id: UUID, payload: ClinGenValidationRequest, db: Session = Depends(get_db)):
    row = db.get(ClinGenSpecification, specification_id)
    if not row:
        raise HTTPException(status_code=404, detail="ClinGen specification not found")
    try:
        metadata = validate_snapshot_for_automation(row, approved_by=payload.approved_by, reason=payload.reason, validation_reference=payload.validation_reference)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    before = {"validation_status": row.validation_status, "validated_for_automation": row.validated_for_automation}
    row.validated_for_automation = True
    row.validation_status = "APPROVED_FOR_AUTOMATION"
    row.validated_by = payload.approved_by
    row.validation_reason = payload.reason
    row.validation_reference = payload.validation_reference
    row.validated_at = datetime.now(timezone.utc)
    db.add(row)
    AuditService(db).record(event_type="CLINGEN_SPECIFICATION_VALIDATED", case_id=None, analysis_id=None, actor_type="HUMAN", actor_id=payload.approved_by, subject_type="CLINGEN_SPECIFICATION", subject_id=str(row.id), operation="VALIDATE", before_state=before, after_state={"validation_status": row.validation_status, "validated_for_automation": True, **metadata}, reason=payload.reason)
    db.commit()
    return {"id": str(row.id), "specification_id": row.specification_id, "version": row.version, "validation_status": row.validation_status, "validated_for_automation": row.validated_for_automation, "validated_by": row.validated_by, "validated_at": row.validated_at.isoformat() if row.validated_at else None}
