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

    @celery_app.task(bind=True, autoretry_for=(), acks_late=True, max_retries=3)
    def run_analysis_task(self, analysis_id: str):
        from uuid import UUID
        from backend.app.workflows.variant import (
            recover_interrupted_execution,
            run_variant_analysis,
            TransientWorkflowError,
        )
        from backend.app.infrastructure.db.session import SessionLocal
        if (self.request.delivery_info or {}).get("redelivered"):
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
