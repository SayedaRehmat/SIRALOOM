from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
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
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Analysis, Case, PhenotypeObservation
from backend.app.infrastructure.db.session import get_db
from backend.app.phenotype import normalize_hpo_id

router = APIRouter(tags=["phenotypes"])
class PhenotypeInput(BaseModel):
    hpo_id: str
    label: str | None = Field(default=None, max_length=500)
    phenotype_status: str = "PRESENT"
    present: bool | None = None
    onset: str | None = None
    severity: str | None = None
    source: str = "CLINICAL_INPUT"
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
    def validate_presence_consistency(self):
        from backend.app.phenotype import PHENOTYPE_STATUSES

        self.phenotype_status = self.phenotype_status.strip().upper()
        if self.phenotype_status not in PHENOTYPE_STATUSES:
            raise ValueError("Unsupported phenotype_status")
        if self.present is not None and self.present != (self.phenotype_status == "PRESENT"):
            raise ValueError("phenotype_status conflicts with legacy present flag")
        return self

def _payload(row):
    legacy_present = (
        True if row.phenotype_status == "PRESENT"
        else False if row.phenotype_status in {"ABSENT", "EXCLUDED"}
        else None
    )
    return {"phenotype_id": str(row.id), "case_id": str(row.case_id), "analysis_id": str(row.analysis_id) if row.analysis_id else None,
            "hpo_id": row.hpo_id, "label": row.label, "present": legacy_present,
            "phenotype_status": row.phenotype_status, "onset": row.onset, "severity": row.severity,
            "source": row.source, "evidence": row.evidence or {}, "created_at": row.created_at.isoformat()}

@router.get("/cases/{case_id}/phenotypes")
def list_case_phenotypes(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case: raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "read")
    rows = db.scalars(select(PhenotypeObservation).where(PhenotypeObservation.case_id == case_id).order_by(PhenotypeObservation.created_at, PhenotypeObservation.id)).all()
    for row in rows:
        if row.analysis_id is not None:
            analysis = db.get(Analysis, row.analysis_id)
            if analysis is None or analysis.case_id != case.id:
                raise HTTPException(409, "Phenotype analysis does not match its case")
    return {"case_id": str(case_id), "count": len(rows), "phenotypes": [_payload(r) for r in rows]}

@router.post("/cases/{case_id}/phenotypes", status_code=201)
def add_case_phenotype(case_id: UUID, body: PhenotypeInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case: raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    try: hpo = normalize_hpo_id(body.hpo_id)
    except ValueError as exc: raise HTTPException(400, str(exc))
    row = db.scalar(select(PhenotypeObservation).where(PhenotypeObservation.case_id == case_id, PhenotypeObservation.analysis_id.is_(None), PhenotypeObservation.hpo_id == hpo, PhenotypeObservation.phenotype_status == body.phenotype_status))
    if row: return _payload(row)
    present = body.phenotype_status == "PRESENT"
    row = PhenotypeObservation(id=uuid4(), case_id=case_id, analysis_id=None, hpo_id=hpo, label=body.label, present=present, phenotype_status=body.phenotype_status, onset=body.onset, severity=body.severity, source=body.source, evidence=body.evidence)
    db.add(row)
    AuditService(db).record(event_type="PHENOTYPE_ADDED", case_id=case_id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="PHENOTYPE", subject_id=str(row.id), operation="CREATE", after_state={"hpo_id": hpo, "present": present, "phenotype_status": body.phenotype_status})
    create_case_change_candidates(
        db,
        case=case,
        trigger_type="PHENOTYPE_UPDATE",
        reason=f"Phenotype {hpo} was added to case {case.case_identifier}; completed analyses may require reanalysis.",
        metadata={"hpo_id": hpo, "present": present, "phenotype_status": body.phenotype_status, "phenotype_id": str(row.id)},
    )
    db.commit()
    return _payload(row)

@router.get("/analyses/{analysis_id}/phenotypes")
def list_analysis_phenotypes(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    rows = db.scalars(select(PhenotypeObservation).where(PhenotypeObservation.case_id == analysis.case_id, (PhenotypeObservation.analysis_id == analysis_id) | (PhenotypeObservation.analysis_id.is_(None))).order_by(PhenotypeObservation.created_at)).all()
    return {"analysis_id": str(analysis_id), "count": len(rows), "phenotypes": [_payload(r) for r in rows]}
