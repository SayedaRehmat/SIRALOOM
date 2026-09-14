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
    )

    @celery_app.task(bind=True, autoretry_for=(), acks_late=True, max_retries=3)
    def run_analysis_task(self, analysis_id: str):
        from uuid import UUID
        from backend.app.workflows.variant import run_variant_analysis, TransientWorkflowError
        try:
            run_variant_analysis(UUID(analysis_id))
        except TransientWorkflowError as exc:
            raise self.retry(exc=exc, countdown=exc.countdown)
        from backend.app.infrastructure.db.session import SessionLocal
        from backend.app.infrastructure.db.models import Analysis
        db = SessionLocal()
        try:
            analysis = db.get(Analysis, UUID(analysis_id))
            return {"analysis_id": analysis_id, "status": str(analysis.status) if analysis else "NOT_FOUND"}
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
