from backend.app.config import settings

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
        },
    )

    def _finalize_transient_retry_exhaustion(db, analysis_id, error_message):
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
            step.error_code = "ANNOTATION_PROVIDER_RETRY_EXHAUSTED"
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
            partition.error_code = "ANNOTATION_PROVIDER_RETRY_EXHAUSTED"
            partition.error_message = error_message

        analysis.status = AnalysisStatus.FAILED
        analysis.completed_at = datetime.now(timezone.utc)
        AuditService(db).record(
            event_type="ANNOTATION_RETRY_EXHAUSTED",
            case_id=analysis.case_id,
            analysis_id=analysis.id,
            actor_type="SYSTEM",
            actor_id="celery",
            reason=error_message,
            payload={"error_code": "ANNOTATION_PROVIDER_RETRY_EXHAUSTED", "max_retries": 3},
        )
        db.commit()
        return True

    def _claim_analysis_execution(db, analysis_id, *, allow_running: bool = False) -> bool:
        """Atomically claim one persisted analysis for one Celery execution.

        Duplicate broker deliveries are possible around queue publication/recovery.
        The analysis row is the durable execution fence: only the first worker may
        move QUEUED/CREATED to RUNNING. A redelivery or Celery retry may resume an
        already-RUNNING analysis because those executions are continuations of the
        same durable workflow, not a second laboratory analysis.
        """
        from backend.app.domain.enums import AnalysisStatus
        from backend.app.infrastructure.db.models import Analysis

        analysis = db.get(Analysis, analysis_id, with_for_update=True)
        if analysis is None:
            return False
        if analysis.status == AnalysisStatus.RUNNING:
            return allow_running
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
                analysis.queue_task_id = None
                db.add(dispatch)
                db.add(analysis)
                db.commit()

            analysis = db.get(Analysis, dispatch.analysis_id, with_for_update=True)
            if analysis is None:
                dispatch.status = "SUPERSEDED"
                db.commit()
                return None
            if str(analysis.status) != "QUEUED":
                dispatch.status = "SUPERSEDED"
                db.commit()
                return analysis.queue_task_id

            dispatch.attempts += 1
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
        from backend.app.infrastructure.db.session import SessionLocal

        redelivered = bool((self.request.delivery_info or {}).get("redelivered"))
        is_retry = self.request.retries > 0
        claim_db = SessionLocal()
        try:
            claimed = _claim_analysis_execution(
                claim_db,
                UUID(analysis_id),
                allow_running=redelivered or is_retry,
            )
        finally:
            claim_db.close()

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
            if self.request.retries >= self.max_retries:
                terminal_db = SessionLocal()
                try:
                    _finalize_transient_retry_exhaustion(
                        terminal_db,
                        UUID(analysis_id),
                        str(exc),
                    )
                finally:
                    terminal_db.close()
                raise
            raise self.retry(exc=exc, countdown=exc.countdown)
        from backend.app.infrastructure.db.models import Analysis
        from backend.app.infrastructure.db.session import SessionLocal
        db = SessionLocal()
        try:
            analysis = db.get(Analysis, UUID(analysis_id))
            return {"analysis_id": analysis_id, "status": str(analysis.status) if analysis else "NOT_FOUND"}
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
        from backend.app.infrastructure.db.models import AnalysisDispatch
        from backend.app.infrastructure.db.session import SessionLocal

        db = SessionLocal()
        try:
            pending_ids = list(db.scalars(
                select(AnalysisDispatch.id).where(
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

                try:
                    task = run_analysis_task.delay(str(analysis.id))
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
                            "celery_state": task_state,
                            "error_type": type(exc).__name__,
                        },
                    )
                    continue

                analysis.queue_task_id = task.id
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
                        "replacement_task_id": task.id,
                        "celery_state": task_state,
                    },
                )
                recovered += 1

            db.commit()
            return {"inspected": inspected, "recovered": recovered}
        finally:
            db.close()

    @celery_app.task(bind=True, autoretry_for=(), acks_late=True)
    def run_case_export_task(self, export_id: str):
        from uuid import UUID
        from backend.app.reporting.export_task import run_case_export
        run_case_export(UUID(export_id))
        return {"export_id": export_id, "status": "completed"}
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
