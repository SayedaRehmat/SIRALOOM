from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    REPORT_FINALIZE_ROLES,
    get_accessible_analysis,
    get_analysis_variant,
    require_role,
)
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    ConfirmationRecord,
    FollowUpPlan,
    SecondaryFindingDecision,
)
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["clinical-governance"])

class ConfirmationInput(BaseModel):
    required: bool = False
    method: str | None = Field(default=None, max_length=150)
    status: str = Field(
        default="PENDING",
        pattern=r"^(PENDING|COMPLETED|WAIVED|FAILED|NOT_REQUIRED)$",
    )
    result: str | None = Field(default=None, max_length=100)
    laboratory: str | None = Field(default=None, max_length=200)
    accession: str | None = Field(default=None, max_length=150)
    performed_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict = Field(default_factory=dict)

class FollowUpInput(BaseModel):
    action_type: str = Field(min_length=1, max_length=150)
    status: str = Field(
        default="PLANNED",
        pattern=r"^(PLANNED|IN_PROGRESS|COMPLETED|CANCELLED)$",
    )
    due_date: datetime | None = None
    responsible_role: str | None = Field(default=None, max_length=100)
    outcome: str | None = Field(default=None, max_length=5000)
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict = Field(default_factory=dict)

class SecondaryFindingInput(BaseModel):
    policy_name: str = Field(min_length=1, max_length=200)
    policy_version: str = Field(min_length=1, max_length=100)
    eligibility: str = Field(default="REVIEW", max_length=50)
    consent_status: str = Field(default="NOT_DOCUMENTED", max_length=50)
    disposition: str = Field(default="REVIEW", max_length=50)
    status: str = Field(default="DRAFT", pattern=r"^(DRAFT|FINAL)$")
    rationale: str | None = Field(default=None, max_length=5000)
    gene_disease_context: dict = Field(default_factory=dict)


def _confirmation(r):
    return {"id":str(r.id),"analysis_id":str(r.analysis_id),"variant_id":str(r.variant_id),"version":r.version,"required":r.required,"method":r.method,"status":r.status,"result":r.result,"laboratory":r.laboratory,"accession":r.accession,"performed_at":r.performed_at.isoformat() if r.performed_at else None,"reviewed_by":str(r.reviewed_by) if r.reviewed_by else None,"reviewed_at":r.reviewed_at.isoformat() if r.reviewed_at else None,"notes":r.notes,"metadata":r.metadata_json or {},"created_at":r.created_at.isoformat()}

def _followup(r):
    return {"id":str(r.id),"case_id":str(r.case_id),"analysis_id":str(r.analysis_id),"variant_id":str(r.variant_id) if r.variant_id else None,"action_type":r.action_type,"status":r.status,"due_date":r.due_date.isoformat() if r.due_date else None,"responsible_role":r.responsible_role,"outcome":r.outcome,"notes":r.notes,"metadata":r.metadata_json or {},"created_by":str(r.created_by),"completed_by":str(r.completed_by) if r.completed_by else None,"completed_at":r.completed_at.isoformat() if r.completed_at else None,"created_at":r.created_at.isoformat()}

def _secondary(r):
    return {"id":str(r.id),"analysis_id":str(r.analysis_id),"variant_id":str(r.variant_id),"version":r.version,"policy_name":r.policy_name,"policy_version":r.policy_version,"eligibility":r.eligibility,"consent_status":r.consent_status,"disposition":r.disposition,"status":r.status,"rationale":r.rationale,"gene_disease_context":r.gene_disease_context or {},"reviewed_by":str(r.reviewed_by) if r.reviewed_by else None,"reviewed_at":r.reviewed_at.isoformat() if r.reviewed_at else None,"created_at":r.created_at.isoformat()}

def _variant_access(analysis, variant_id, db):
    return get_analysis_variant(analysis, variant_id, db)

def _validate_followup_case_link(row, analysis) -> None:
    if row.case_id != analysis.case_id:
        raise HTTPException(
            status_code=409,
            detail="Follow-up plan case does not match its analysis",
        )

def _validate_variant_link(row, variant_id: UUID, record_type: str) -> None:
    if row.variant_id != variant_id:
        raise HTTPException(
            status_code=409,
            detail=f"{record_type} variant does not match the requested variant",
        )

@router.get("/analyses/{analysis_id}/variants/{variant_id}/clinical-governance")
def get_governance(analysis_id: UUID, variant_id: UUID, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id,db,principal); _variant_access(analysis,variant_id,db)
    confirmations=list(db.scalars(select(ConfirmationRecord).where(ConfirmationRecord.analysis_id==analysis_id,ConfirmationRecord.variant_id==variant_id).order_by(ConfirmationRecord.version.desc())))
    for confirmation in confirmations:
        _validate_variant_link(confirmation, variant_id, "Confirmation record")
    followups=list(db.scalars(select(FollowUpPlan).where(FollowUpPlan.analysis_id==analysis_id,FollowUpPlan.variant_id==variant_id).order_by(FollowUpPlan.created_at.desc())))
    for followup in followups:
        _validate_followup_case_link(followup, analysis)
        _validate_variant_link(followup, variant_id, "Follow-up plan")
    secondary=list(db.scalars(select(SecondaryFindingDecision).where(SecondaryFindingDecision.analysis_id==analysis_id,SecondaryFindingDecision.variant_id==variant_id).order_by(SecondaryFindingDecision.version.desc())))
    for decision in secondary:
        _validate_variant_link(decision, variant_id, "Secondary-finding decision")
    return {"analysis_id":str(analysis_id),"variant_id":str(variant_id),"confirmation":_confirmation(confirmations[0]) if confirmations else None,"confirmation_history":[_confirmation(x) for x in confirmations],"follow_up":[_followup(x) for x in followups],"secondary_finding":_secondary(secondary[0]) if secondary else None,"secondary_finding_history":[_secondary(x) for x in secondary]}

@router.post("/analyses/{analysis_id}/variants/{variant_id}/confirmation",status_code=201)
def record_confirmation(analysis_id: UUID, variant_id: UUID, body: ConfirmationInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id,db,principal); _variant_access(analysis,variant_id,db); require_role(principal,CASE_WRITE_ROLES)
    previous=db.scalar(select(ConfirmationRecord).where(ConfirmationRecord.analysis_id==analysis_id,ConfirmationRecord.variant_id==variant_id).order_by(ConfirmationRecord.version.desc()))
    row=ConfirmationRecord(id=uuid4(),analysis_id=analysis_id,variant_id=variant_id,version=(previous.version+1 if previous else 1),supersedes_record_id=previous.id if previous else None,required=body.required,method=body.method,status=body.status,result=body.result,laboratory=body.laboratory,accession=body.accession,performed_at=body.performed_at,reviewed_by=principal.user_id,reviewed_at=datetime.now(timezone.utc),notes=body.notes,metadata_json=body.metadata)
    db.add(row)
    # created_at is generated by the database/ORM insert default. Flush before
    # serializing the immutable audit snapshot so the event and response carry
    # the same persisted record identity and timestamp.
    db.flush()
    AuditService(db).record(event_type="CONFIRMATION_RECORDED",case_id=analysis.case_id,analysis_id=analysis_id,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="CONFIRMATION",subject_id=str(row.id),operation="CREATE",after_state=_confirmation(row)); db.commit(); return _confirmation(row)

@router.post("/analyses/{analysis_id}/variants/{variant_id}/follow-up",status_code=201)
def create_followup(analysis_id: UUID, variant_id: UUID, body: FollowUpInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id,db,principal); _variant_access(analysis,variant_id,db); require_role(principal,CASE_WRITE_ROLES)
    row=FollowUpPlan(id=uuid4(),case_id=analysis.case_id,analysis_id=analysis_id,variant_id=variant_id,action_type=body.action_type.strip(),status=body.status,due_date=body.due_date,responsible_role=body.responsible_role,outcome=body.outcome,notes=body.notes,metadata_json=body.metadata,created_by=principal.user_id,completed_by=principal.user_id if body.status in {"COMPLETED","CANCELLED"} else None,completed_at=datetime.now(timezone.utc) if body.status in {"COMPLETED","CANCELLED"} else None)
    db.add(row)
    db.flush()
    AuditService(db).record(event_type="FOLLOW_UP_PLAN_CREATED",case_id=analysis.case_id,analysis_id=analysis_id,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="FOLLOW_UP_PLAN",subject_id=str(row.id),operation="CREATE",after_state=_followup(row)); db.commit(); return _followup(row)

@router.patch("/follow-up/{follow_up_id}")
def update_followup(follow_up_id: UUID, body: FollowUpInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    row=db.get(FollowUpPlan,follow_up_id)
    if not row: raise HTTPException(404,"Follow-up plan not found")
    try:
        analysis=get_accessible_analysis(row.analysis_id,db,principal)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(404,"Follow-up plan not found") from exc
        raise
    require_role(principal,CASE_WRITE_ROLES)
    _validate_followup_case_link(row, analysis)
    if row.variant_id is not None:
        _variant_access(analysis, row.variant_id, db)
    row.action_type=body.action_type.strip(); row.status=body.status; row.due_date=body.due_date; row.responsible_role=body.responsible_role; row.outcome=body.outcome; row.notes=body.notes; row.metadata_json=body.metadata
    if body.status in {"COMPLETED","CANCELLED"}: row.completed_by=principal.user_id; row.completed_at=datetime.now(timezone.utc)
    AuditService(db).record(event_type="FOLLOW_UP_PLAN_UPDATED",case_id=analysis.case_id,analysis_id=row.analysis_id,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="FOLLOW_UP_PLAN",subject_id=str(row.id),operation="UPDATE",after_state=_followup(row)); db.commit(); return _followup(row)

@router.post("/analyses/{analysis_id}/variants/{variant_id}/secondary-finding",status_code=201)
def record_secondary_finding(analysis_id: UUID, variant_id: UUID, body: SecondaryFindingInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id,db,principal); _variant_access(analysis,variant_id,db); require_role(principal,REPORT_FINALIZE_ROLES)
    allowed_consent={"ACCEPTED","DECLINED","NOT_DOCUMENTED","NOT_APPLICABLE"}; allowed_disp={"REPORT","DO_NOT_REPORT","REVIEW"}; allowed_status={"DRAFT","FINAL"}
    if body.consent_status not in allowed_consent or body.disposition not in allowed_disp or body.status not in allowed_status: raise HTTPException(400,"Invalid secondary-finding governance value")
    if body.status=="FINAL" and body.disposition=="REPORT" and body.consent_status!="ACCEPTED": raise HTTPException(409,"A secondary finding cannot be finalized for reporting without documented accepted consent")
    previous=db.scalar(select(SecondaryFindingDecision).where(SecondaryFindingDecision.analysis_id==analysis_id,SecondaryFindingDecision.variant_id==variant_id).order_by(SecondaryFindingDecision.version.desc()))
    row=SecondaryFindingDecision(id=uuid4(),analysis_id=analysis_id,variant_id=variant_id,version=(previous.version+1 if previous else 1),supersedes_decision_id=previous.id if previous else None,policy_name=body.policy_name,policy_version=body.policy_version,eligibility=body.eligibility,consent_status=body.consent_status,disposition=body.disposition,status=body.status,rationale=body.rationale,gene_disease_context=body.gene_disease_context,reviewed_by=principal.user_id if body.status=="FINAL" else None,reviewed_at=datetime.now(timezone.utc) if body.status=="FINAL" else None)
    db.add(row)
    db.flush()
    AuditService(db).record(event_type="SECONDARY_FINDING_DECISION_RECORDED",case_id=analysis.case_id,analysis_id=analysis_id,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="SECONDARY_FINDING",subject_id=str(row.id),operation="CREATE",after_state=_secondary(row),reason=body.rationale); db.commit(); return _secondary(row)

@router.get("/analyses/{analysis_id}/secondary-findings")
def list_secondary_findings(analysis_id: UUID, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id,db,principal)
    rows=list(db.scalars(select(SecondaryFindingDecision).where(SecondaryFindingDecision.analysis_id==analysis_id).order_by(SecondaryFindingDecision.variant_id,SecondaryFindingDecision.version)))
    for row in rows:
        _variant_access(analysis, row.variant_id, db)
    latest={}
    for r in rows: latest[r.variant_id]=r
    return {"analysis_id":str(analysis_id),"items":[_secondary(r) for r in latest.values()]}
