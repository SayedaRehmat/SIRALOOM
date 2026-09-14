from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.db.models import AuditEvent, Case
from backend.app.auth.principal import Principal, get_current_principal, require_case_tenant

router = APIRouter(tags=["audit"])

@router.get("/cases/{case_id}/audit")
def audit(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case: return []
    require_case_tenant(case, principal)
    rows = db.scalars(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.occurred_at)).all()
    return [{"event_id": str(x.id), "event_version": x.event_version, "event_type": x.event_type, "analysis_id": str(x.analysis_id) if x.analysis_id else None, "actor_type": x.actor_type, "actor_id": x.actor_id, "subject_type": x.subject_type, "subject_id": x.subject_id, "operation": x.operation, "before_state": x.before_state, "after_state": x.after_state, "reason": x.reason, "input_artifacts": x.input_artifacts, "output_artifacts": x.output_artifacts, "software": x.software, "workflow": x.workflow, "resource_versions": x.resource_versions, "occurred_at": x.occurred_at} for x in rows]
