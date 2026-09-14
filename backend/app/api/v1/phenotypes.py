from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.auth.authorization import get_accessible_analysis
from backend.app.auth.principal import Principal, get_current_principal, require_case_tenant
from backend.app.infrastructure.db.models import Case, Analysis, PhenotypeObservation
from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.audit.service import AuditService
from backend.app.phenotype import normalize_hpo_id

router = APIRouter(tags=["phenotypes"])
class PhenotypeInput(BaseModel):
    hpo_id: str
    label: str | None = Field(default=None, max_length=500)
    present: bool = True
    onset: str | None = None
    severity: str | None = None
    source: str = "CLINICAL_INPUT"
    evidence: dict = Field(default_factory=dict)

def _payload(row):
    return {"phenotype_id": str(row.id), "case_id": str(row.case_id), "analysis_id": str(row.analysis_id) if row.analysis_id else None,
            "hpo_id": row.hpo_id, "label": row.label, "present": row.present, "onset": row.onset, "severity": row.severity,
            "source": row.source, "evidence": row.evidence or {}, "created_at": row.created_at.isoformat()}

@router.get("/cases/{case_id}/phenotypes")
def list_case_phenotypes(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case: raise HTTPException(404, "Case not found")
    require_case_tenant(case, principal)
    rows = db.scalars(select(PhenotypeObservation).where(PhenotypeObservation.case_id == case_id).order_by(PhenotypeObservation.created_at, PhenotypeObservation.id)).all()
    return {"case_id": str(case_id), "count": len(rows), "phenotypes": [_payload(r) for r in rows]}

@router.post("/cases/{case_id}/phenotypes", status_code=201)
def add_case_phenotype(case_id: UUID, body: PhenotypeInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case: raise HTTPException(404, "Case not found")
    require_case_tenant(case, principal)
    try: hpo = normalize_hpo_id(body.hpo_id)
    except ValueError as exc: raise HTTPException(400, str(exc))
    row = db.scalar(select(PhenotypeObservation).where(PhenotypeObservation.case_id == case_id, PhenotypeObservation.analysis_id.is_(None), PhenotypeObservation.hpo_id == hpo, PhenotypeObservation.present == body.present))
    if row: return _payload(row)
    row = PhenotypeObservation(id=uuid4(), case_id=case_id, analysis_id=None, hpo_id=hpo, label=body.label, present=body.present, onset=body.onset, severity=body.severity, source=body.source, evidence=body.evidence)
    db.add(row)
    AuditService(db).record(event_type="PHENOTYPE_ADDED", case_id=case_id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="PHENOTYPE", subject_id=str(row.id), operation="CREATE", after_state={"hpo_id": hpo, "present": body.present})
    db.commit()
    return _payload(row)

@router.get("/analyses/{analysis_id}/phenotypes")
def list_analysis_phenotypes(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    rows = db.scalars(select(PhenotypeObservation).where(PhenotypeObservation.case_id == analysis.case_id, (PhenotypeObservation.analysis_id == analysis_id) | (PhenotypeObservation.analysis_id.is_(None))).order_by(PhenotypeObservation.created_at)).all()
    return {"analysis_id": str(analysis_id), "count": len(rows), "phenotypes": [_payload(r) for r in rows]}
