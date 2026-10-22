"""Verify missing final reportability disposition fails closed through the workflow entry point.

Upstream scientific stages are represented by durable successful checkpoints so this
test targets the production reportability gate, not the full VCF-to-report pipeline.
"""
import gzip
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

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


def test_missing_reportability_disposition_blocks_report_creation_on_reexecution(
    monkeypatch, tmp_path
):
    import importlib

    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")
    reportability = importlib.import_module("backend.app.reporting.reportability")

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'reportability-gate.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
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
                id=organization_id, name="Reportability Gate Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Reportability Gate Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"REPORTABILITY-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            input_artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=input_vcf, filename="input.vcf",
                artifact_type="SOURCE_VCF", media_type="text/plain",
                genome_build="GRCh38", metadata={},
            )
            store.put_file(
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
                status=AnalysisStatus.RUNNING, queue_task_id="reportability-gate-test",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(input_artifact.id)},
                started_at=datetime.now(UTC), completed_at=None,
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
                        StepStatus.PENDING if stage_id in {
                            "reportability", "report", "export_provenance"
                        } else StepStatus.SUCCEEDED
                    ),
                    attempt=0, input_artifacts=[], output_artifacts=[],
                    metadata_json={"seeded_test_checkpoint": True},
                ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(
            workflow, "artifact_store_for_organization",
            lambda *_args, **_kwargs: store,
        )
        # This test starts at reportability, so upstream classification review
        # is deliberately considered complete rather than re-tested here.
        monkeypatch.setattr(workflow, "_classification_review_gate_ready", lambda *_args: True)
        # Exercise the workflow's real gate orchestration while deterministically
        # modeling the domain service's fail-closed result for missing dispositions.
        evaluation_calls = {"count": 0}

        def fail_reportability_database_once(*_args):
            evaluation_calls["count"] += 1
            if evaluation_calls["count"] == 1:
                raise OperationalError(
                    "SELECT reportability decisions",
                    {},
                    RuntimeError("injected temporary database outage"),
                )

        monkeypatch.setattr(reportability, "evaluate_analysis", fail_reportability_database_once)
        monkeypatch.setattr(
            reportability, "final_reportability_state",
            lambda *_args: (False, ["missing_final_reportability_disposition"]),
        )

        with pytest.raises(workflow.TransientWorkflowError) as retry_error:
            workflow.run_variant_analysis(analysis_id)
        assert retry_error.value.error_code == "REPORTABILITY_PERSISTENCE_RETRY_EXHAUSTED"

        with LocalSession() as db:
            analysis = db.get(Analysis, analysis_id)
            gate = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "reportability",
            ))
            assert analysis.status == AnalysisStatus.RUNNING
            assert analysis.completed_at is None
            assert gate.status == StepStatus.RETRYING
            assert gate.error_code == "REPORTABILITY_PERSISTENCE_RETRYING"
            assert gate.metadata_json["next_step"] == "reportability"
            assert db.scalar(select(func.count(Report.id)).where(
                Report.analysis_id == analysis_id,
            )) == 0
            assert db.scalar(select(func.count(AuditEvent.id)).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "REPORTABILITY_PERSISTENCE_RETRY_SCHEDULED",
            )) == 1

        for _attempt in range(2):
            workflow.run_variant_analysis(analysis_id)
            with LocalSession() as db:
                analysis = db.get(Analysis, analysis_id)
                gate = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "reportability",
                ))
                report_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "report",
                ))
                assert analysis.status == AnalysisStatus.REQUIRES_REVIEW
                assert analysis.completed_at is None
                assert gate.status == StepStatus.REQUIRES_REVIEW
                assert gate.metadata_json["next_step"] == "reportability"
                assert "missing_final_reportability_disposition" in gate.metadata_json["errors"]
                assert report_step.status == StepStatus.PENDING
                assert db.scalar(select(func.count(Report.id)).where(
                    Report.analysis_id == analysis_id,
                )) == 0
                assert db.scalar(select(func.count(AuditEvent.id)).where(
                    AuditEvent.analysis_id == analysis_id,
                    AuditEvent.event_type == "WORKFLOW_AWAITING_REPORTABILITY",
                )) >= 1
    finally:
        engine.dispose()
