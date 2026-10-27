"""Exercise population-stage scientific-gap handling through the production workflow entry point.

This test proves the orchestration continues without inventing zero frequency and routes
ACMG to review. The resource plan is deliberately empty; it is not a provider integration
test or clinical-validity claim.
"""
import gzip
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.variant_identity import stable_variant_uuid
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Annotation,
    AuditEvent,
    Case,
    Classification,
    Organization,
    Report,
    User,
    Variant,
    WorkflowStep,
)


def test_missing_population_observation_continues_to_acmg_human_review(monkeypatch, tmp_path):
    import importlib

    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'population-gap-review.db'}")
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

        canonical_key = "GRCh38:1:555:T:C"
        variant_id = stable_variant_uuid(canonical_key)
        with LocalSession() as db:
            db.add(Organization(
                id=organization_id, name="Population Gap Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Population Gap Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"POPULATION-GAP-{case_id}", status="OPEN",
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
                status=AnalysisStatus.RUNNING, queue_task_id="population-gap-review-test",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(input_artifact.id)},
                started_at=datetime.now(timezone.utc), completed_at=None,
                created_by=user_id, analysis_version=1,
            ))
            db.flush()
            db.add(Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1", position=555,
                reference="T", alternate="C", normalization_status="NORMALIZED",
                canonical_key=canonical_key,
                identifiers={"canonical_key_sha256": __import__("hashlib").sha256(canonical_key.encode()).hexdigest()},
            ))
            db.flush()
            db.add(Annotation(
                id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                provider_name="test-provider", provider_version="test",
                resource_id=None, resource_name="test-annotation", resource_version="test",
                request_fingerprint="population-gap-request",
                response_sha256="population-gap-response",
                request_metadata={"test_fixture": True}, payload={"normalized": {}},
            ))
            db.flush()
            stages = [
                "validate_input", "normalize", "annotate", "population",
                "build_evidence", "acmg_assessment", "review",
                "reportability", "report", "export_provenance",
            ]
            for order, stage_id in enumerate(stages, start=1):
                if stage_id in {"validate_input", "normalize", "annotate", "build_evidence"}:
                    status = StepStatus.SUCCEEDED
                elif stage_id == "population":
                    status = StepStatus.PENDING
                else:
                    status = StepStatus.PENDING
                db.add(WorkflowStep(
                    id=uuid4(), analysis_id=analysis_id, step_id=stage_id,
                    step_order=order, status=status, attempt=0,
                    input_artifacts=[], output_artifacts=[],
                    metadata_json={"seeded_test_checkpoint": True} if status == StepStatus.SUCCEEDED else {},
                ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(
            workflow, "artifact_store_for_organization",
            lambda *_args, **_kwargs: store,
        )
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_a, **_k: store)
        # An empty optional population-resource plan exercises the real stage body
        # and its per-variant missing-observation check without a live provider.
        monkeypatch.setattr(
            workflow, "build_resource_execution_plan",
            lambda *_args, **_kwargs: SimpleNamespace(
                profile_type="TRIAL_PUBLIC",
                profile_version="test",
                unavailable_optional=[],
                for_capability=lambda *_args, **_kwargs: [],
            ),
        )
        monkeypatch.setattr(
            workflow, "register_builtin_providers",
            lambda: SimpleNamespace(resolve=lambda **_kwargs: None),
        )

        workflow.run_variant_analysis(analysis_id)

        with LocalSession() as db:
            analysis = db.get(Analysis, analysis_id)
            population = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "population",
            ))
            acmg = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "acmg_assessment",
            ))
            report_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "report",
            ))
            assert population.metadata_json["scientific_limitation"] is True
            assert population.error_code == "POPULATION_OBSERVATIONS_MISSING"
            assert population.metadata_json["variants_without_population_observations"] == [str(variant_id)]
            assert "must not be interpreted as zero" in population.error_message
            assert acmg.status == StepStatus.REQUIRES_REVIEW
            assert acmg.metadata_json["population_scientific_gap"] is True
            assert acmg.metadata_json["next_step"] == "review"
            assert analysis.status == AnalysisStatus.REQUIRES_REVIEW
            assert analysis.completed_at is None
            assert report_step.status == StepStatus.PENDING
            assert db.scalar(select(func.count(Report.id)).where(
                Report.analysis_id == analysis_id,
            )) == 0
            assert db.scalar(select(func.count(Classification.id)).where(
                Classification.analysis_id == analysis_id,
            )) == 0
            assert db.scalar(select(func.count(AuditEvent.id)).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "ACMG_ASSESSMENT_REQUIRES_MANUAL_REVIEW",
            )) == 1
    finally:
        engine.dispose()
