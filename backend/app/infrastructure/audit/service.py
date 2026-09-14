from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.models import AuditEvent

class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def record(self, *, event_type: str, case_id: UUID | None, analysis_id: UUID | None,
               actor_type: str, actor_id: str, subject_type: str | None = None,
               subject_id: str | None = None, operation: str | None = None,
               before_state: dict | None = None, after_state: dict | None = None,
               reason: str | None = None, input_artifacts: list | None = None,
               output_artifacts: list | None = None, software: dict | None = None,
               workflow: dict | None = None, resource_versions: dict | None = None,
               correlation_id: str | None = None, payload: dict | None = None) -> UUID:
        event_id = uuid4()
        now = datetime.now(timezone.utc)
        previous = self.db.scalar(select(AuditEvent).order_by(desc(AuditEvent.occurred_at)).limit(1))
        previous_hash = previous.event_hash if previous else None
        body = {
            "event_id": str(event_id), "event_version": "1.0", "event_type": event_type,
            "case_id": str(case_id) if case_id else None, "analysis_id": str(analysis_id) if analysis_id else None,
            "actor_type": actor_type, "actor_id": actor_id, "subject_type": subject_type,
            "subject_id": subject_id, "operation": operation, "before_state": before_state,
            "after_state": after_state, "reason": reason, "input_artifacts": input_artifacts or [],
            "output_artifacts": output_artifacts or [], "software": software or {"name": "SIRALOOM", "version": "0.1.0"},
            "workflow": workflow or {}, "resource_versions": resource_versions or {},
            "correlation_id": correlation_id, "payload": payload or {}, "occurred_at": now.isoformat(),
            "previous_event_hash": previous_hash,
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        event_hash = hashlib.sha256(canonical.encode()).hexdigest()
        event = AuditEvent(
            id=event_id, event_version="1.0", event_type=event_type, case_id=case_id,
            analysis_id=analysis_id, actor_type=actor_type, actor_id=actor_id,
            subject_type=subject_type, subject_id=subject_id, operation=operation,
            before_state=before_state, after_state=after_state, reason=reason,
            input_artifacts=input_artifacts or [], output_artifacts=output_artifacts or [],
            software=software or {"name": "SIRALOOM", "version": "0.1.0"},
            workflow=workflow or {}, resource_versions=resource_versions or {},
            correlation_id=correlation_id, payload=payload or {}, occurred_at=now,
            previous_event_hash=previous_hash, event_hash=event_hash,
        )
        self.db.add(event)
        self.db.flush()
        return event_id
