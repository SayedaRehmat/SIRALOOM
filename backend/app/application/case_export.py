from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import CaseExport, CaseExportDispatch


def enqueue_case_export(db: Session, export: CaseExport) -> str:
    """Persist a durable case-export dispatch intent before broker publication."""
    locked = db.get(CaseExport, export.id, with_for_update=True)
    if locked is None:
        raise ValueError("Case export not found")
    db.refresh(locked, with_for_update=True)

    if locked.status in {"QUEUED", "RUNNING"} and locked.queue_task_id:
        return str(locked.queue_task_id)
    if locked.status != "QUEUED":
        raise ValueError(f"Case export is not queueable from status {locked.status}")

    generation = (
        db.scalar(
            select(func.coalesce(func.max(CaseExportDispatch.dispatch_generation), 0))
            .where(CaseExportDispatch.case_export_id == locked.id)
        )
        or 0
    ) + 1

    dispatch = CaseExportDispatch(
        id=uuid4(),
        case_export_id=locked.id,
        dispatch_generation=generation,
        status="PENDING",
        task_id=None,
        attempts=0,
    )
    locked.queue_task_id = str(dispatch.id)
    db.add(dispatch)
    db.add(locked)
    db.commit()

    from backend.app.infrastructure.queue.celery_app import publish_case_export_dispatch

    try:
        publish_case_export_dispatch(dispatch.id)
    except (ImportError, RuntimeError):
        # The durable PENDING intent remains recoverable by the outbox relay.
        pass
    except Exception:
        # Broker publication is deliberately outside the DB transaction. Any
        # unexpected publication failure leaves the committed PENDING intent
        # recoverable rather than rolling back the user's export request.
        pass
    return str(dispatch.id)