from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    Case,
    Organization,
    User,
    WorkflowStep,
)


@pytest.mark.parametrize(
    ("filename", "vcf", "expected_code", "profile_key"),
    [
        (
            "input.gvcf",
            "##fileformat=VCFv4.3\n"
            '##ALT=<ID=NON_REF,Description="Represents any possible alternative allele">\n'
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "1\t1\t.\tA\t<NON_REF>\t.\tPASS\tEND=10\n",
            "UNSUPPORTED_GVCF_INPUT",
            "gvcf_markers",
        ),
        (
            "input.sv.vcf",
            "##fileformat=VCFv4.3\n"
            '##ALT=<ID=DEL,Description="Deletion">\n'
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "1\t5\t.\tA\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=10\n",
            "UNSUPPORTED_STRUCTURAL_VARIANT",
            "symbolic_records",
        ),
    ],
)
def test_production_worker_blocks_unsupported_vcf_before_reference_resolution(
    monkeypatch, tmp_path, filename, vcf, expected_code, profile_key
):
    import importlib

    workflow = importlib.import_module("backend.app.workflows.variant")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'unsupported-input.db'}")
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()

    source = tmp_path / filename
    source.write_text(vcf, encoding="utf-8")
    try:
        with local_session() as db:
            db.add(Organization(id=organization_id, name="Input Scope Lab"))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Input Scope Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"UNSUPPORTED-{analysis_id}",
                status="ACTIVE",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            input_artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=source,
                filename=filename,
                artifact_type="SOURCE_VCF",
                media_type="text/plain",
                genome_build="GRCh38",
                metadata={},
                validation_status="VALID",
            )
            db.flush()
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="test",
                status=AnalysisStatus.QUEUED,
                queue_task_id="unsupported-input-test",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(input_artifact.id)},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", local_session)
        monkeypatch.setattr(
            workflow,
            "artifact_store_for_organization",
            lambda *_args, **_kwargs: store,
        )

        def unexpected_reference_lookup(*_args, **_kwargs):
            raise AssertionError("unsupported input must be classified before reference lookup")

        monkeypatch.setattr(workflow, "resolve_resource_with_fallback", unexpected_reference_lookup)
        monkeypatch.setattr(workflow, "load_reference_package", unexpected_reference_lookup)

        workflow.run_variant_analysis(analysis_id)

        with local_session() as db:
            analysis = db.get(Analysis, analysis_id)
            normalization = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "normalize",
            ))
            validation = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "validate_input",
            ))
            events = db.scalars(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "NORMALIZATION_BLOCKED",
            )).all()

            assert analysis.status == AnalysisStatus.BLOCKED
            assert analysis.completed_at is None
            assert normalization.status == StepStatus.BLOCKED
            assert normalization.error_code == expected_code
            assert normalization.metadata_json["next_step"] == "SUPPORTED_INPUT_REQUIRED"
            assert normalization.metadata_json["input_profile"][profile_key] > 0
            assert validation.status == StepStatus.SUCCEEDED
            assert len(events) == 1
            assert events[0].payload["error_code"] == expected_code
            assert events[0].payload["next_step"] == "SUPPORTED_INPUT_REQUIRED"
    finally:
        engine.dispose()
