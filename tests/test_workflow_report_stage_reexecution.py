"""Exercise the production workflow entry point across a real report-artifact failure.

Earlier stages are seeded as durable completed checkpoints so this test isolates the
report stage body. The real run_variant_analysis entry point executes twice, with a
one-shot artifact-store failure on the first attempt.
"""
import gzip
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    Case,
    Organization,
    Report,
    User,
    WorkflowStep,
)


def test_real_workflow_entrypoint_retries_report_artifact_failure_without_duplicate_report(
    monkeypatch, tmp_path
):
    import importlib

    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")
    report_service = importlib.import_module("backend.app.reporting.service")

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'report-stage-retry.db'}")
    Base.metadata.create_all(engine)
    case_lock_requests = []

    class CaseLockTrackingSession(Session):
        def get(self, entity, ident, **kwargs):
            if entity is Case and kwargs.get("with_for_update"):
                case_lock_requests.append(ident)
            return super().get(entity, ident, **kwargs)

    LocalSession = sessionmaker(
        bind=engine,
        class_=CaseLockTrackingSession,
        expire_on_commit=False,
    )
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    fail_report_artifact_once = {"pending": True}
    original_put_file = store.put_file

    def fail_once_at_report_artifact_boundary(**kwargs):
        if (
            kwargs.get("filename", "").startswith("report_v")
            and fail_report_artifact_once["pending"]
        ):
            fail_report_artifact_once["pending"] = False
            raise OSError("injected report artifact-store outage")
        return original_put_file(**kwargs)

    try:
        input_vcf = tmp_path / "input.vcf"
        input_vcf.write_text(
            "##fileformat=VCFv4.2\n"
            "##contig=<ID=1,length=1000000>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "1\t555\t.\tT\tC\t.\tPASS\t.\n",
            encoding="utf-8",
        )
        normalized_vcf = tmp_path / "normalized.vcf.gz"
        normalized_vcf.write_bytes(gzip.compress(input_vcf.read_bytes()))
        with LocalSession() as db:
            db.add(Organization(
                id=organization_id, name="Report Retry Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Report Retry Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"REPORT-RETRY-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            input_artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=input_vcf, filename="input.vcf",
                artifact_type="SOURCE_VCF", media_type="text/plain",
                genome_build="GRCh38", metadata={},
            )
            normalized_artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=normalized_vcf, filename="normalized.vcf.gz",
                artifact_type="NORMALIZED_VCF", media_type="application/gzip",
                genome_build="GRCh38", metadata={},
            )
            db.flush()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.RUNNING, queue_task_id="report-retry-test",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(input_artifact.id)},
                started_at=datetime.now(timezone.utc), completed_at=None,
                created_by=user_id, analysis_version=1,
            ))
            db.flush()
            stage_ids = [
                "validate_input", "normalize", "annotate", "population",
                "build_evidence", "acmg_assessment", "review",
                "reportability", "report", "export_provenance",
            ]
            for order, stage_id in enumerate(stage_ids, start=1):
                db.add(WorkflowStep(
                    id=uuid4(), analysis_id=analysis_id, step_id=stage_id,
                    step_order=order,
                    status=(
                        StepStatus.RETRYING
                        if stage_id == "report"
                        else StepStatus.SUCCEEDED
                    ),
                    attempt=1, input_artifacts=[], output_artifacts=[],
                    metadata_json={
                        "seeded_test_checkpoint": True,
                        **(
                            {"next_step": "report", "retry_policy": "bounded_transient_retry"}
                            if stage_id == "report" else {}
                        ),
                    },
                ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(
            workflow, "artifact_store_for_organization",
            lambda *_args, **_kwargs: store,
        )
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_a, **_k: store)
        monkeypatch.setattr(store, "put_file", fail_once_at_report_artifact_boundary)
        monkeypatch.setattr(workflow, "_classification_review_gate_ready", lambda *_args: True)
        monkeypatch.setattr(
            report_service, "build_report_content",
            lambda *_args, **_kwargs: {
                "language": "en",
                "report_type": "CLINICAL_INTERPRETATION",
                "report_schema_version": "test-schema",
                "report_version": 1,
                "findings": [],
            },
        )
        monkeypatch.setattr(report_service, "render_pdf", lambda _content: b"%PDF-test-report")

        with pytest.raises(workflow.TransientWorkflowError):
            workflow.run_variant_analysis(analysis_id)
        assert case_lock_requests.count(case_id) >= 1

        with LocalSession() as db:
            analysis = db.get(Analysis, analysis_id)
            report_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "report",
            ))
            retry_event = db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "REPORT_GENERATION_RETRY_SCHEDULED",
            ))
            assert analysis.status == AnalysisStatus.RUNNING
            assert analysis.completed_at is None
            assert report_step.status == StepStatus.RETRYING
            assert report_step.error_code == "REPORT_GENERATION_RETRYING"
            assert report_step.metadata_json["next_step"] == "report"
            assert retry_event is not None
            assert retry_event.payload["error_code"] == "REPORT_GENERATION_RETRYING"
            assert db.scalar(select(func.count(Report.id)).where(
                Report.analysis_id == analysis_id,
            )) == 0

        # Re-enter through the production workflow function. The completed upstream
        # stages remain checkpoints; only the failed report artifact operation retries.
        workflow.run_variant_analysis(analysis_id)
        assert case_lock_requests.count(case_id) >= 2

        with LocalSession() as db:
            analysis = db.get(Analysis, analysis_id)
            report_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "report",
            ))
            reports = db.scalars(select(Report).where(
                Report.analysis_id == analysis_id,
            )).all()
            assert analysis.status == AnalysisStatus.REQUIRES_REVIEW
            assert report_step.status == StepStatus.SUCCEEDED
            assert report_step.metadata_json["report_status"] == "DRAFT"
            assert len(reports) == 1
            assert reports[0].status == "DRAFT"
            assert reports[0].artifact_id is not None
            assert Path(store.local_path(
                db.get(__import__(
                    "backend.app.infrastructure.db.models", fromlist=["Artifact"]
                ).Artifact, reports[0].artifact_id).storage_uri
            )).is_file()
            assert db.scalar(select(func.count(AuditEvent.id)).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "REPORT_GENERATION_RETRY_SCHEDULED",
            )) == 1
    finally:
        engine.dispose()
