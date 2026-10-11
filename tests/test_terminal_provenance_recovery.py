from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from celery.exceptions import Retry
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisPartition,
    Annotation,
    Artifact,
    Case,
    Classification,
    Organization,
    Report,
    User,
    Variant,
    WorkflowStep,
)


def test_resumed_signed_out_analysis_retries_provenance_failure_and_completes(
    monkeypatch, tmp_path
):
    """A transient provenance write failure must not strand a signed-out case."""
    import importlib

    queue_module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'provenance-resume.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    variant_id = uuid4()
    task_id = "signed-out-provenance-retry"

    try:
        with LocalSession() as db:
            db.add(Organization(
                id=organization_id,
                name="Provenance Recovery Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Authorized Reviewer",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"PROV-RECOVERY-{case_id}",
                status="ACTIVE",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            analysis = Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="test",
                status=AnalysisStatus.QUEUED,
                queue_task_id=task_id,
                reference_build="GRCh38",
                configuration={},
                started_at=datetime.now(timezone.utc),
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            )
            db.add(analysis)
            db.flush()

            input_path = tmp_path / "signed-out-input.vcf"
            input_path.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                "1\t555\t.\tT\tC\t.\tPASS\t.\n",
                encoding="utf-8",
            )
            input_artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=input_path,
                filename="input.vcf",
                artifact_type="VCF",
                media_type="text/vcf",
                genome_build="GRCh38",
                validation_status="VALID",
            )
            analysis.configuration = {"input_artifact_id": str(input_artifact.id)}
            normalized_artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=input_path,
                filename="normalized.vcf",
                artifact_type="NORMALIZED_VCF",
                media_type="text/vcf",
                genome_build="GRCh38",
                validation_status="VALID",
            )

            variant = Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=555,
                reference="T",
                alternate="C",
                normalization_status="NORMALIZED",
                canonical_key="GRCh38:1:555:T:C",
                identifiers={},
            )
            db.add(variant)
            db.flush()
            db.add(Annotation(
                id=uuid4(),
                variant_id=variant_id,
                analysis_id=analysis_id,
                provider_name="TestProvider",
                provider_version="test-v1",
                resource_id=None,
                resource_name="Test annotation resource",
                resource_version="test-v1",
                request_fingerprint="a" * 64,
                response_sha256="b" * 64,
                request_metadata={},
                retry_count=0,
                payload={"normalized": {"gene_symbol": "TEST1"}},
            ))
            db.add(Classification(
                id=uuid4(),
                variant_id=variant_id,
                analysis_id=analysis_id,
                framework_name="Manual clinical classification",
                framework_version="manual-review-v1",
                specification_provider=None,
                specification_id=None,
                specification_version=None,
                result="VUS",
                criterion_ids=[],
                metadata_json={"decision_mode": "MANUAL"},
                state="FINAL",
                review_status="APPROVED",
                version=1,
                review_version=1,
                reviewed_by=user_id,
                approved_at=datetime.now(timezone.utc),
            ))
            db.add(Report(
                id=uuid4(),
                case_id=case_id,
                analysis_id=analysis_id,
                report_version=1,
                language="en",
                report_type="CLINICAL_INTERPRETATION",
                status="FINAL",
                content_json={"report_status": "FINAL", "findings": []},
            ))
            for partition_step in ("normalize", "annotate"):
                db.add(AnalysisPartition(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    step_id=partition_step,
                    partition_key="0:1",
                    ordinal=0,
                    record_start=0,
                    record_end=1,
                    variant_count=1,
                    status="SUCCEEDED",
                    input_artifact_id=normalized_artifact.id,
                    metadata_json={"variant_ids": [str(variant_id)]},
                    resource_class="STANDARD",
                    cpu_request=1.0,
                    memory_mb=1024,
                    attempt=1,
                ))

            for step_id, order in (
                ("validate_input", 1),
                ("normalize", 2),
                ("annotate", 3),
                ("population", 4),
                ("build_evidence", 5),
                ("acmg_assessment", 6),
                ("review", 7),
                ("reportability", 8),
                ("report", 9),
                ("export_provenance", 10),
            ):
                db.add(WorkflowStep(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    step_id=step_id,
                    step_order=order,
                    status=(
                        StepStatus.RETRYING
                        if step_id == "export_provenance"
                        else StepStatus.SUCCEEDED
                    ),
                    attempt=1,
                    input_artifacts=[],
                    output_artifacts=[],
                    metadata_json=({"record_count": 1} if step_id == "normalize" else {}),
                ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(db_module, "engine", engine)
        monkeypatch.setattr(
            workflow,
            "artifact_store_for_organization",
            lambda *_args, **_kwargs: store,
        )

        original_put_file = store.put_file
        failures_remaining = {"count": 1}

        def fail_first_provenance_write(**kwargs):
            if kwargs.get("filename") == "provenance.json" and failures_remaining["count"]:
                failures_remaining["count"] -= 1
                raise OSError("simulated transient provenance storage interruption")
            return original_put_file(**kwargs)

        monkeypatch.setattr(store, "put_file", fail_first_provenance_write)

        queue_module.run_analysis_task.push_request(
            id=task_id,
            retries=0,
            delivery_info={"redelivered": False},
        )
        try:
            with pytest.raises(Retry):
                queue_module.run_analysis_task.run(str(analysis_id))
        finally:
            queue_module.run_analysis_task.pop_request()

        with LocalSession() as db:
            analysis = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "export_provenance",
            ))
            assert analysis.status == AnalysisStatus.RUNNING
            assert analysis.completed_at is None
            assert step.status == StepStatus.RETRYING
            assert step.error_code == "PROVENANCE_EXPORT_RETRYING"
            assert step.metadata_json["next_step"] == "export_provenance"
            assert db.scalar(select(Artifact.id).where(
                Artifact.analysis_id == analysis_id,
                Artifact.filename == "provenance.json",
            )) is None

        queue_module.run_analysis_task.push_request(
            id=task_id,
            retries=1,
            delivery_info={"redelivered": False},
        )
        try:
            result = queue_module.run_analysis_task.run(str(analysis_id))
        finally:
            queue_module.run_analysis_task.pop_request()

        assert result["status"] == str(AnalysisStatus.SUCCEEDED)
        assert failures_remaining["count"] == 0
        with LocalSession() as db:
            analysis = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "export_provenance",
            ))
            artifacts = list(db.scalars(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.filename == "provenance.json",
            )))
            assert analysis.status == AnalysisStatus.SUCCEEDED
            assert analysis.completed_at is not None
            assert step.status == StepStatus.SUCCEEDED
            assert len(artifacts) == 1
            assert step.output_artifacts == [str(artifacts[0].id)]
            assert step.metadata_json["next_step"] == "analysis_complete"
            assert db.scalar(select(AnalysisPartition.status).where(
                AnalysisPartition.analysis_id == analysis_id,
                AnalysisPartition.step_id == "normalize",
                AnalysisPartition.partition_key == "0:1",
            )) == "SUCCEEDED"
            assert db.scalar(select(AnalysisPartition.status).where(
                AnalysisPartition.analysis_id == analysis_id,
                AnalysisPartition.step_id == "annotate",
                AnalysisPartition.partition_key == "0:1",
            )) == "SUCCEEDED"
    finally:
        engine.dispose()
