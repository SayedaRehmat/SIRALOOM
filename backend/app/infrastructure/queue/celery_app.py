from backend.app.config import settings

import hashlib

try:
    from celery import Celery
except ImportError:  # test/dev environments without queue dependencies installed
    Celery = None

if Celery is not None:
    celery_app = Celery("siraloom", broker=settings.redis_url, backend=settings.redis_url)
    celery_app.conf.update(
        task_track_started=True,
        task_time_limit=None,
        task_acks_late=True,
        worker_prefetch_multiplier=max(1, settings.celery_worker_prefetch_multiplier),
        worker_concurrency=max(1, settings.celery_concurrency),
        worker_max_tasks_per_child=max(1, settings.celery_worker_max_tasks_per_child),
        task_reject_on_worker_lost=True,
        timezone="UTC",
        beat_schedule={
            "scan-reanalysis-resources-daily": {
                "task": "siraloom.scan_reanalysis_resources",
                "schedule": 86400.0,
            },
            "recover-analysis-dispatch-outbox": {
                "task": "siraloom.dispatch_pending_analysis_outbox",
                "schedule": 30.0,
            },
            "recover-orphaned-analysis-dispatches": {
                "task": "siraloom.recover_orphaned_analysis_dispatches",
                "schedule": 300.0,
            },
            "dispatch-pending-case-export-outbox": {
                "task": "siraloom.dispatch_pending_case_export_outbox",
                "schedule": 30.0,
            },
            "recover-orphaned-case-export-dispatches": {
                "task": "siraloom.recover_orphaned_case_export_dispatches",
                "schedule": 300.0,
            },
        },
    )

    def _finalize_transient_retry_exhaustion(
        db, analysis_id, error_message, *, error_code="ANNOTATION_PROVIDER_RETRY_EXHAUSTED",
        max_retries=3,
    ):
        from datetime import datetime, timezone
        from sqlalchemy import select
        from backend.app.domain.enums import AnalysisStatus, StepStatus
        from backend.app.infrastructure.audit.service import AuditService
        from backend.app.infrastructure.db.models import Analysis, AnalysisPartition, WorkflowStep

        analysis = db.get(Analysis, analysis_id)
        if analysis is None:
            return False

        retrying_steps = list(db.scalars(
            select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.status == StepStatus.RETRYING,
            )
        ))
        for step in retrying_steps:
            metadata = dict(step.metadata_json or {})
            metadata["retry_exhausted"] = True
            step.status = StepStatus.FAILED
            step.error_code = error_code
            step.error_message = error_message
            step.metadata_json = metadata

        unfinished_partitions = list(db.scalars(
            select(AnalysisPartition).where(
                AnalysisPartition.analysis_id == analysis_id,
                AnalysisPartition.step_id == "annotate",
                AnalysisPartition.status.in_(("READY", "RUNNING")),
            )
        ))
        for partition in unfinished_partitions:
            partition.status = "FAILED"
            partition.lease_owner = None
            partition.lease_expires_at = None
            partition.error_code = error_code
            partition.error_message = error_message

        analysis.status = AnalysisStatus.FAILED
        analysis.completed_at = datetime.now(timezone.utc)
        AuditService(db).record(
            event_type="ANALYSIS_RETRY_EXHAUSTED",
            case_id=analysis.case_id,
            analysis_id=analysis.id,
            actor_type="SYSTEM",
            actor_id="celery",
            reason=error_message,
            payload={"error_code": error_code, "max_retries": max_retries},
        )
        db.commit()
        return True

    def _claim_analysis_execution(
        db,
        analysis_id,
        *,
        task_id: str | None = None,
        allow_running: bool = False,
        lock_connection=None,
    ) -> bool:
        """Atomically claim one persisted analysis for one Celery execution.

        The queue task ID is the durable dispatch-generation fence. A task from
        an older retry generation must not be allowed to claim an analysis that
        has since been queued with a newer dispatch intent. The pointer is
        persisted before broker publication, so this check also closes the
        publication-before-commit race.
        """
        from backend.app.domain.enums import AnalysisStatus
        from backend.app.infrastructure.db.models import Analysis
        from sqlalchemy import text

        # A PostgreSQL session-scoped advisory lock is the execution ownership
        # fence. Unlike a row lock, it remains held for the entire Celery task
        # because the claim session stays open until the task exits. If a worker
        # dies, PostgreSQL releases the lock with the connection, allowing the
        # broker-redelivered task to recover RUNNING state. A duplicate delivery
        # while the original worker is alive cannot acquire the lock and is
        # therefore fenced before it can touch workflow state.
        get_bind = getattr(db, "get_bind", None)
        bind = get_bind() if callable(get_bind) else None
        if bind is not None and bind.dialect.name == "postgresql":
            lock_key = int.from_bytes(
                hashlib.sha256(str(analysis_id).encode("utf-8")).digest()[:8],
                byteorder="big",
                signed=True,
            )
            lock_statement = text("SELECT pg_try_advisory_lock(:lock_key)")
            lock_parameters = {"lock_key": lock_key}
            if lock_connection is not None:
                # A dedicated connection must stay checked out for the whole
                # task. Session.commit() can return its own connection to the
                # pool even while the Session object remains open.
                acquired = bool(
                    lock_connection.execute(lock_statement, lock_parameters).scalar_one()
                )
                lock_connection.commit()
            else:
                acquired = bool(db.scalar(lock_statement, lock_parameters))
            if not acquired:
                return False

        analysis = db.get(Analysis, analysis_id, with_for_update=True)
        if analysis is None:
            return False
        if task_id is not None and analysis.queue_task_id != task_id:
            return False
        if analysis.status == AnalysisStatus.RUNNING:
            if allow_running:
                # Release the row lock before redelivery recovery uses a second
                # session to lock and reconcile the interrupted workflow. The
                # session-scoped advisory lock remains held by this claim session.
                db.commit()
                return True
            return False
        if analysis.status not in {AnalysisStatus.CREATED, AnalysisStatus.QUEUED}:
            return False

        analysis.status = AnalysisStatus.RUNNING
        db.add(analysis)
        db.commit()
        return True

    def publish_analysis_dispatch(dispatch_id):
        """Publish one durable analysis dispatch intent.

        The dispatch row is locked so multiple relay workers cannot publish the
        same pending intent concurrently. A crash after broker publication but
        before the DB commit may cause a later duplicate publication; the
        analysis execution fence is the authoritative protection against a
        second scientific execution.
        """
        from datetime import datetime, timezone
        from backend.app.infrastructure.db.models import Analysis, AnalysisDispatch
        from backend.app.infrastructure.db.session import SessionLocal

        db = SessionLocal()
        try:
            dispatch = db.get(AnalysisDispatch, dispatch_id, with_for_update=True)
            if dispatch is None:
                return None
            if dispatch.status == "PUBLISHED" and dispatch.task_id:
                analysis = db.get(Analysis, dispatch.analysis_id, with_for_update=True)
                if analysis is None:
                    dispatch.status = "SUPERSEDED"
                    db.commit()
                    return None
                if str(analysis.status) != "QUEUED":
                    return dispatch.task_id
                if analysis.queue_task_id != str(dispatch.id):
                    dispatch.status = "SUPERSEDED"
                    dispatch.last_error = (
                        "Dispatch generation is no longer current for this analysis."
                    )
                    db.add(dispatch)
                    db.commit()
                    return analysis.queue_task_id
                task_state = celery_app.AsyncResult(dispatch.task_id).state
                if task_state not in {"FAILURE", "REVOKED"}:
                    return dispatch.task_id
                # The previous publication is definitively dead and the
                # analysis is still QUEUED, so this durable intent is retryable.
                # Reset the durable intent in this transaction and continue
                # with one bounded publication attempt. Do not recurse: a
                # broker that immediately reports definitive failure must not
                # turn the relay into unbounded Python recursion.
                dispatch.status = "PENDING"
                dispatch.task_id = None
                dispatch.last_error = None
                # Keep the durable generation pointer on this dispatch while\n                # its broker publication is retried. Clearing it would make the\n                # current dispatch look stale to the generation fence below.\n                analysis.queue_task_id = str(dispatch.id)\n                db.add(dispatch)\n                db.add(analysis)\n                db.commit()

            analysis = db.get(Analysis, dispatch.analysis_id, with_for_update=True)
            if analysis is None:
                dispatch.status = "SUPERSEDED"
                db.commit()
                return None
            if str(analysis.status) != "QUEUED":
                dispatch.status = "SUPERSEDED"
                db.commit()
                return analysis.queue_task_id

            # A retry creates a new dispatch generation and moves the durable
            # queue pointer to that generation before publication. Older
            # PENDING/PUBLISHED intents must never reclaim ownership of the
            # analysis when the outbox relay revisits them.
            if analysis.queue_task_id != str(dispatch.id):
                dispatch.status = "SUPERSEDED"
                dispatch.last_error = (
                    "Dispatch generation is no longer current for this analysis."
                )
                db.add(dispatch)
                db.commit()
                return analysis.queue_task_id

            dispatch.attempts += 1
            # Persist the current dispatch generation before broker publication.
            # A stale broker message can therefore be fenced by the worker even
            # if publication and the following DB update are not atomic.
            analysis.queue_task_id = str(dispatch.id)
            db.add(analysis)
            try:
                task = run_analysis_task.apply_async(
                    args=[str(analysis.id)],
                    task_id=str(dispatch.id),
                )
            except Exception as exc:
                dispatch.last_error = str(exc)
                db.add(dispatch)
                db.commit()
                return None

            dispatch.status = "PUBLISHED"
            dispatch.task_id = task.id
            dispatch.last_error = None
            dispatch.published_at = datetime.now(timezone.utc)
            analysis.queue_task_id = task.id
            db.add(dispatch)
            db.add(analysis)
            db.commit()
            return task.id
        finally:
            db.close()


    @celery_app.task(bind=True, autoretry_for=(), acks_late=True, max_retries=3)
    def run_analysis_task(self, analysis_id: str):
        from uuid import UUID
        from backend.app.workflows.variant import (
            recover_interrupted_execution,
            run_variant_analysis,
            TransientWorkflowError,
        )
        from backend.app.infrastructure.db.session import SessionLocal, engine

        redelivered = bool((self.request.delivery_info or {}).get("redelivered"))
        is_retry = self.request.retries > 0
        # Hold the PostgreSQL session-level advisory lock on a dedicated
        # checked-out connection. Session.commit() releases a Session's
        # connection to the pool; keeping only the Session object alive is not
        # sufficient to preserve lock ownership across workflow commits.
        claim_lock_connection = (
            engine.connect() if engine.dialect.name == "postgresql" else None
        )
        claim_db = SessionLocal()
        try:
            claim_options = (
                {"lock_connection": claim_lock_connection}
                if claim_lock_connection is not None
                else {}
            )
            claimed = _claim_analysis_execution(
                claim_db,
                UUID(analysis_id),
                task_id=self.request.id,
                allow_running=redelivered or is_retry,
                **claim_options,
            )
            if not claimed:
                return {"analysis_id": analysis_id, "status": "ALREADY_CLAIMED_OR_TERMINAL"}

            if redelivered:
                recovery_db = SessionLocal()
                try:
                    recover_interrupted_execution(recovery_db, UUID(analysis_id))
                finally:
                    recovery_db.close()
            try:
                run_variant_analysis(UUID(analysis_id))
            except TransientWorkflowError as exc:
                if self.request.retries >= exc.max_retries:
                    terminal_db = SessionLocal()
                    try:
                        _finalize_transient_retry_exhaustion(
                            terminal_db,
                            UUID(analysis_id),
                            str(exc),
                            error_code=exc.error_code,
                            max_retries=exc.max_retries,
                        )
                    finally:
                        terminal_db.close()
                    raise
                raise self.retry(
                    exc=exc,
                    countdown=exc.countdown,
                    max_retries=exc.max_retries,
                )
            from backend.app.infrastructure.db.models import Analysis
            analysis = claim_db.get(Analysis, UUID(analysis_id))
            return {"analysis_id": analysis_id, "status": str(analysis.status) if analysis else "NOT_FOUND"}
        finally:
            claim_db.close()
            if claim_lock_connection is not None:
                claim_lock_connection.close()


    def _claim_case_export_execution(
        db,
        export_id,
        *,
        task_id: str | None = None,
        allow_running: bool = False,
    ) -> bool:
        from backend.app.infrastructure.db.models import CaseExport
        from sqlalchemy import text

        get_bind = getattr(db, "get_bind", None)
        bind = get_bind() if callable(get_bind) else None
        if bind is not None and bind.dialect.name == "postgresql":
            lock_key = int.from_bytes(
                hashlib.sha256(str(export_id).encode("utf-8")).digest()[:8],
                byteorder="big",
                signed=True,
            )
            if not bool(
                db.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            ):
                return False

        export = db.get(CaseExport, export_id, with_for_update=True)
        if export is None:
            return False
        if task_id is not None and export.queue_task_id != task_id:
            return False
        if export.status == "RUNNING":
            return allow_running
        if export.status != "QUEUED":
            return False
        export.status = "RUNNING"
        db.add(export)
        db.commit()
        return True


    def publish_case_export_dispatch(dispatch_id):
        from datetime import datetime, timezone
        from backend.app.infrastructure.db.models import CaseExport, CaseExportDispatch
        from backend.app.infrastructure.db.session import SessionLocal

        db = SessionLocal()
        try:
            dispatch = db.get(CaseExportDispatch, dispatch_id, with_for_update=True)
            if dispatch is None:
                return None
            export = db.get(CaseExport, dispatch.case_export_id, with_for_update=True)
            if export is None:
                dispatch.status = "SUPERSEDED"
                db.commit()
                return None

            if dispatch.status == "PUBLISHED" and dispatch.task_id:
                if export.status != "QUEUED" or export.queue_task_id != str(dispatch.id):
                    dispatch.status = "SUPERSEDED"
                    db.add(dispatch)
                    db.commit()
                    return export.queue_task_id
                task_state = celery_app.AsyncResult(dispatch.task_id).state
                if task_state not in {"FAILURE", "REVOKED"}:
                    return dispatch.task_id
                dispatch.status = "PENDING"
                dispatch.task_id = None
                dispatch.last_error = None
                export.queue_task_id = str(dispatch.id)
                db.add(dispatch)
                db.add(export)
                db.commit()

            if export.status != "QUEUED" or export.queue_task_id != str(dispatch.id):
                dispatch.status = "SUPERSEDED"
                db.add(dispatch)
                db.commit()
                return export.queue_task_id

            dispatch.attempts += 1
            export.queue_task_id = str(dispatch.id)
            db.add(export)
            try:
                task = run_case_export_task.apply_async(
                    args=[str(export.id)],
                    task_id=str(dispatch.id),
                )
            except Exception as exc:
                dispatch.last_error = str(exc)
                db.add(dispatch)
                db.commit()
                return None

            dispatch.status = "PUBLISHED"
            dispatch.task_id = task.id
            dispatch.last_error = None
            dispatch.published_at = datetime.now(timezone.utc)
            export.queue_task_id = task.id
            db.add(dispatch)
            db.add(export)
            db.commit()
            return task.id
        finally:
            db.close()


    @celery_app.task(name="siraloom.dispatch_pending_case_export_outbox", autoretry_for=(), acks_late=True)
    def dispatch_pending_case_export_outbox():
        from sqlalchemy import select
        from backend.app.infrastructure.db.models import CaseExport, CaseExportDispatch
        from backend.app.infrastructure.db.session import SessionLocal

        db = SessionLocal()
        try:
            pending_ids = list(db.scalars(
                select(CaseExportDispatch.id)
                .join(CaseExport, CaseExport.id == CaseExportDispatch.case_export_id)
                .where(
                    CaseExport.status == "QUEUED",
                    CaseExportDispatch.status.in_(("PENDING", "PUBLISHED")),
                )
            ))
        finally:
            db.close()

        dispatched = 0
        for dispatch_id in pending_ids:
            if publish_case_export_dispatch(dispatch_id):
                dispatched += 1
        return {"inspected": len(pending_ids), "dispatched": dispatched}


    @celery_app.task(name="siraloom.recover_orphaned_case_export_dispatches", autoretry_for=(), acks_late=True)
    def recover_orphaned_case_export_dispatches():
        from sqlalchemy import select, func
        from uuid import uuid4
        from backend.app.infrastructure.audit.service import AuditService
        from backend.app.infrastructure.db.models import CaseExport, CaseExportDispatch
        from backend.app.infrastructure.db.session import SessionLocal

        db = SessionLocal()
        inspected = 0
        recovered = 0
        try:
            export_ids = list(db.scalars(
                select(CaseExport.id).where(
                    CaseExport.status == "QUEUED",
                    CaseExport.queue_task_id.is_(None),
                )
            ))
            for export_id in export_ids:
                export = db.get(CaseExport, export_id, with_for_update=True)
                if export is None or export.status != "QUEUED" or export.queue_task_id is not None:
                    continue
                inspected += 1
                generation = (
                    db.scalar(
                        select(func.coalesce(func.max(CaseExportDispatch.dispatch_generation), 0))
                        .where(CaseExportDispatch.case_export_id == export.id)
                    )
                    or 0
                ) + 1
                dispatch = CaseExportDispatch(
                    id=uuid4(),
                    case_export_id=export.id,
                    dispatch_generation=generation,
                    status="PENDING",
                    task_id=None,
                    attempts=0,
                )
                export.queue_task_id = str(dispatch.id)
                db.add(dispatch)
                db.add(export)
                AuditService(db).record(
                    event_type="CASE_EXPORT_DISPATCH_RECOVERED",
                    case_id=export.case_id,
                    analysis_id=None,
                    actor_type="SYSTEM",
                    actor_id="case-export-recovery",
                    operation="RECOVER_QUEUED_EXPORT",
                    payload={
                        "replacement_dispatch_id": str(dispatch.id),
                        "dispatch_generation": generation,
                        "recovery_mode": "LEGACY_TO_DURABLE_OUTBOX",
                    },
                )
                db.commit()
                if publish_case_export_dispatch(dispatch.id):
                    recovered += 1
            return {"inspected": inspected, "recovered": recovered}
        finally:
            db.close()


    @celery_app.task(name="siraloom.scan_reanalysis_resources", autoretry_for=(), acks_late=True)
    def scan_reanalysis_resources():
        from backend.app.domain.reanalysis import scan_active_resources_for_reanalysis
        from backend.app.infrastructure.db.session import SessionLocal

        db = SessionLocal()
        try:
            candidates_created = scan_active_resources_for_reanalysis(db)
            return {"candidates_created": candidates_created}
        finally:
            db.close()

    @celery_app.task(name="siraloom.dispatch_pending_analysis_outbox", autoretry_for=(), acks_late=True)
    def dispatch_pending_analysis_outbox():
        """Relay durable analysis dispatch intents to Celery."""
        from sqlalchemy import select
        from backend.app.domain.enums import AnalysisStatus
        from backend.app.infrastructure.db.models import Analysis, AnalysisDispatch
        from backend.app.infrastructure.db.session import SessionLocal

        db = SessionLocal()
        try:
            # Only analyses that are currently QUEUED have an active broker
            # execution intent. A retry moves the analysis back to QUEUED before
            # creating its new generation, so this remains safe for retries while
            # preventing the periodic relay from repeatedly touching historical
            # dispatches after an analysis reaches RUNNING or a terminal state.
            pending_ids = list(db.scalars(
                select(AnalysisDispatch.id)
                .join(Analysis, Analysis.id == AnalysisDispatch.analysis_id)
                .where(
                    Analysis.status == AnalysisStatus.QUEUED,
                    AnalysisDispatch.status.in_(("PENDING", "PUBLISHED")),
                )
            ))
        finally:
            db.close()

        dispatched = 0
        for dispatch_id in pending_ids:
            if publish_analysis_dispatch(dispatch_id):
                dispatched += 1
        return {"inspected": len(pending_ids), "dispatched": dispatched}


    @celery_app.task(name="siraloom.recover_orphaned_analysis_dispatches", autoretry_for=(), acks_late=True)
    def recover_orphaned_analysis_dispatches():
        """Recover only definitively failed/revoked Celery dispatches.

        Each candidate analysis is row-locked before its Celery state is inspected
        and replacement dispatch is attempted. This prevents two scheduler
        instances from concurrently replacing the same failed queue task.

        A QUEUED task whose broker/backend state is PENDING is deliberately left
        untouched because PENDING does not prove that the task is absent. This
        prevents a scheduler from creating duplicate laboratory analyses.
        """
        from sqlalchemy import select
        from backend.app.domain.enums import AnalysisStatus
        from backend.app.infrastructure.audit.service import AuditService
        from backend.app.infrastructure.db.models import Analysis, AnalysisDispatch
        from backend.app.infrastructure.db.session import SessionLocal

        db = SessionLocal()
        recovered = 0
        inspected = 0
        try:
            queued_ids = list(db.scalars(
                select(Analysis.id).where(
                    Analysis.status == AnalysisStatus.QUEUED,
                    Analysis.queue_task_id.is_not(None),
                )
            ))
            for analysis_id in queued_ids:
                analysis = db.get(Analysis, analysis_id, with_for_update=True)
                if analysis is None:
                    continue
                # New dispatches are owned by the durable outbox relay. The
                # legacy scanner remains only for analyses created before 0036.
                dispatch_exists = db.scalars(
                    select(AnalysisDispatch.id).where(
                        AnalysisDispatch.analysis_id == analysis.id
                    )
                ).first()
                if dispatch_exists is not None:
                    continue
                if (
                    analysis.status != AnalysisStatus.QUEUED
                    or analysis.queue_task_id is None
                ):
                    continue

                inspected += 1
                previous_task_id = str(analysis.queue_task_id)
                task_state = celery_app.AsyncResult(previous_task_id).state
                if task_state not in {"FAILURE", "REVOKED"}:
                    continue

                # Legacy analyses predate AnalysisDispatch. Convert the
                # orphaned queue ownership into the same durable outbox used by
                # every current analysis instead of publishing a task directly.
                # The old task is already definitively dead, so a new dispatch
                # generation can safely take ownership under this row lock.
                from uuid import uuid4
                from sqlalchemy import func

                next_generation = (
                    db.scalar(
                        select(func.coalesce(func.max(AnalysisDispatch.dispatch_generation), 0))
                        .where(AnalysisDispatch.analysis_id == analysis.id)
                    )
                    or 0
                ) + 1
                dispatch = AnalysisDispatch(
                    id=uuid4(),
                    analysis_id=analysis.id,
                    dispatch_generation=next_generation,
                    status="PENDING",
                    task_id=None,
                    attempts=0,
                    last_error=None,
                    published_at=None,
                )
                analysis.queue_task_id = str(dispatch.id)
                db.add(dispatch)
                db.add(analysis)
                AuditService(db).record(
                    event_type="ANALYSIS_DISPATCH_RECOVERED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="celery-recovery",
                    operation="RECOVER_QUEUED_DISPATCH",
                    payload={
                        "previous_task_id": previous_task_id,
                        "replacement_dispatch_id": str(dispatch.id),
                        "dispatch_generation": next_generation,
                        "celery_state": task_state,
                        "recovery_mode": "LEGACY_TO_DURABLE_OUTBOX",
                    },
                )
                db.commit()

                try:
                    published_task_id = publish_analysis_dispatch(dispatch.id)
                except Exception as exc:
                    AuditService(db).record(
                        event_type="ANALYSIS_DISPATCH_RECOVERY_FAILURE",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SYSTEM",
                        actor_id="celery-recovery",
                        operation="RECOVER_QUEUED_DISPATCH",
                        reason=str(exc),
                        payload={
                            "previous_task_id": previous_task_id,
                            "replacement_dispatch_id": str(dispatch.id),
                            "celery_state": task_state,
                            "error_type": type(exc).__name__,
                        },
                    )
                    continue

                if published_task_id:
                    recovered += 1

            db.commit()
            return {"inspected": inspected, "recovered": recovered}
        finally:
            db.close()

    @celery_app.task(bind=True, autoretry_for=(), acks_late=True)
    def run_case_export_task(self, export_id: str):
        from uuid import UUID
        from backend.app.infrastructure.db.session import SessionLocal
        from backend.app.reporting.export_task import run_case_export

        redelivered = bool((self.request.delivery_info or {}).get("redelivered"))
        is_retry = self.request.retries > 0
        claim_db = SessionLocal()
        try:
            claimed = _claim_case_export_execution(
                claim_db,
                UUID(export_id),
                task_id=self.request.id,
                allow_running=redelivered or is_retry,
            )
            if not claimed:
                return {"export_id": export_id, "status": "ALREADY_CLAIMED_OR_TERMINAL"}
            run_case_export(UUID(export_id))
            return {"export_id": export_id, "status": "completed"}
        finally:
            claim_db.close()
else:
    class _UnavailableTask:
        def delay(self, *_args, **_kwargs):
            raise RuntimeError("Celery is not installed. Install production dependencies before starting background jobs.")
    class _UnavailableCeleryApp:
        pass
    celery_app = _UnavailableCeleryApp()
    run_analysis_task = _UnavailableTask()
    run_case_export_task = _UnavailableTask()


    @celery_app.task(name="siraloom.discover_scientific_resources", autoretry_for=(), acks_late=True)
    def discover_scientific_resources():
        from backend.app.domain.resource_discovery import discover_resource_candidates
        from backend.app.infrastructure.db.session import SessionLocal

        db = SessionLocal()
        try:
            return discover_resource_candidates(db)
        finally:
            db.close()