from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID
from backend.app.config import settings
from backend.app.infrastructure.db.session import SessionLocal
from backend.app.infrastructure.db.models import CaseExport, Case
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.domain.storage_profiles import artifact_store_for_organization, StorageProfileError
from backend.app.infrastructure.audit.service import AuditService
from backend.app.reporting.export_service import build_case_export

def run_case_export(export_id: UUID) -> None:
    db = SessionLocal()
    try:
        export = db.get(CaseExport, export_id, with_for_update=True)
        if export is None:
            return
        if export.status == "SUCCEEDED" and export.artifact_id:
            return
        if export.status != "RUNNING":
            export.status = "RUNNING"
            db.add(export)
            db.commit()
        case = db.get(Case, export.case_id)
        if case is None:
            raise RuntimeError("Case not found for export")
        try:
            store = artifact_store_for_organization(
                db, organization_id=case.organization_id
            )
        except StorageProfileError as exc:
            raise RuntimeError(str(exc)) from exc
        artifact = build_case_export(db, export=export, store=store)
        export.artifact_id = artifact.id; export.status = "SUCCEEDED"; export.completed_at = datetime.now(timezone.utc); db.flush()
        AuditService(db).record(event_type="CASE_EXPORT_COMPLETED", case_id=export.case_id, analysis_id=None, actor_type="SYSTEM", actor_id="siraloom-export", subject_type="CASE_EXPORT", subject_id=str(export.id), operation="CREATE", output_artifacts=[{"artifact_id": str(artifact.id), "sha256": artifact.sha256}])
        db.commit()
    except Exception as exc:
        db.rollback()
        export = db.get(CaseExport, export_id)
        if export:
            export.status = "FAILED"; export.error_code = "CASE_EXPORT_FAILED"; export.error_message = str(exc)[:4000]; export.completed_at = datetime.now(timezone.utc); db.commit()
            AuditService(db).record(event_type="CASE_EXPORT_FAILED", case_id=export.case_id, analysis_id=None, actor_type="SYSTEM", actor_id="siraloom-export", subject_type="CASE_EXPORT", subject_id=str(export.id), operation="CREATE", reason=str(exc)[:4000]); db.commit()
    finally:
        db.close()