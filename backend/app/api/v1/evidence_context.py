from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.auth.authorization import get_accessible_analysis
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.db.models import Analysis, Annotation, Evidence
from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.audit.service import AuditService
from backend.app.domain.evidence import evidence_fingerprint
from backend.app.evidence.engine import EvidenceEngine

router = APIRouter(tags=["evidence-context"])
class ContextEvidenceRequest(BaseModel):
    evidence_type: str
    source_name: str = Field(min_length=1, max_length=300)
    source_version: str | None = None
    statement: str = Field(min_length=1, max_length=10000)
    payload: dict = Field(default_factory=dict)
    direction: str = "NEUTRAL"

@router.post("/analyses/{analysis_id}/variants/{variant_id}/context-evidence", status_code=201)
def add_context_evidence(analysis_id: UUID, variant_id: UUID, body: ContextEvidenceRequest, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    ann = db.scalar(select(Annotation).where(Annotation.analysis_id == analysis_id, Annotation.variant_id == variant_id))
    if not ann: raise HTTPException(404, "Variant annotation not found in analysis")
    typ = body.evidence_type.upper()
    if typ not in {"LITERATURE", "GENE_DISEASE", "PHENOTYPE"}: raise HTTPException(400, "Only LITERATURE, GENE_DISEASE or PHENOTYPE context evidence may be added here")
    direction = body.direction.upper()
    if direction not in {"SUPPORTS", "REFUTES", "NEUTRAL", "UNKNOWN"}: raise HTTPException(400, "Invalid evidence direction")
    fp = evidence_fingerprint(variant_id=variant_id, analysis_id=analysis_id, evidence_type=typ, statement=body.statement, direction=direction, source_name=body.source_name, source_version=body.source_version, observation_ids=tuple(), payload=body.payload)
    existing = db.scalar(select(Evidence).where(Evidence.analysis_id == analysis_id, Evidence.evidence_fingerprint == fp))
    if existing:
        return {"evidence_id": str(existing.id), "created": False}
    row = Evidence(id=uuid4(), variant_id=variant_id, analysis_id=analysis_id, evidence_type=typ, statement=body.statement, direction=direction, source_name=body.source_name, source_version=body.source_version, source_record_id=str(body.payload.get("source_id") or body.payload.get("pmid") or "") or None, observation_ids=[], payload=body.payload, created_by_type="HUMAN", created_by_id=str(principal.user_id), evidence_fingerprint=fp)
    db.add(row)
    AuditService(db).record(event_type="CONTEXT_EVIDENCE_ADDED", case_id=analysis.case_id, analysis_id=analysis_id, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="EVIDENCE", subject_id=str(row.id), operation="CREATE", after_state={"evidence_type": typ, "source_name": body.source_name})
    db.commit()
    return {"evidence_id": str(row.id), "created": True}
