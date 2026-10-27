"""Exercise production workflow resumption after a human resolves an ACMG resource gap.

This verifies stage reconciliation and downstream gate ordering. It does not claim
scientific validity of the manually entered classification or end-to-end clinical
validation; those require separately governed reviewer and truth-set tests.
"""
import gzip
from datetime import datetime, timezone
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


def test_manual_acmg_approval_resumes_workflow_to_next_human_gate(monkeypatch, tmp_path):
    import importlib

    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")
    reportability = importlib.import_module("backend.app.reporting.reportability")

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'manual-acmg-resume.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id, variant_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
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
                id=organization_id, name="Manual ACMG Resume Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Manual ACMG Resume Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"MANUAL-ACMG-{case_id}", status="OPEN",
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
                status=AnalysisStatus.REQUIRES_REVIEW, queue_task_id="manual-acmg-resume-test",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(input_artifact.id)},
                started_at=datetime.now(timezone.utc), completed_at=None,
                created_by=user_id, analysis_version=1,
            ))
            db.flush()
            canonical_key = "GRCh38:1:555:T:C"
            variant_id = stable_variant_uuid(canonical_key)
            variant = Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1", position=555,
                reference="T", alternate="C", normalization_status="NORMALIZED",
                canonical_key=canonical_key,
                identifiers={"canonical_key_sha256": __import__("hashlib").sha256(canonical_key.encode()).hexdigest()},
            )
            db.add(variant)
            db.flush()
            db.add(Annotation(
                id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                provider_name="test-provider", provider_version="test",
                resource_id=None, resource_name="test-annotation", resource_version="test",
                request_fingerprint="manual-acmg-resume-request",
                response_sha256="manual-acmg-resume-response",
                request_metadata={"test_fixture": True}, payload={"test_fixture": True},
            ))
            db.add(Classification(
                id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                framework_name="ACMG/AMP", framework_version="2015",
                specification_provider=None, specification_id=None, specification_version=None,
                result="VUS", criterion_ids=[],
                metadata_json={
                    "decision_mode": "MANUAL",
                    "human_review_reason": "ClinGen specification unavailable; manually assessed by authorized reviewer",
                },
                state="FINAL", review_status="APPROVED", version=1,
                supersedes_classification_id=None, review_version=1,
                reviewed_by=user_id, approved_at=datetime.now(timezone.utc),
            ))
            db.flush()
            stage_ids = [
                "validate_input", "normalize", "annotate", "population",
                "build_evidence", "acmg_assessment", "review",
                "reportability", "report", "export_provenance",
            ]
            for order, stage_id in enumerate(stage_ids, start=1):
                if stage_id in {"validate_input", "normalize", "annotate", "population", "build_evidence"}:
                    status = StepStatus.SUCCEEDED
                    metadata = {"seeded_test_checkpoint": True}
                elif stage_id == "acmg_assessment":
                    status = StepStatus.REQUIRES_REVIEW
                    metadata = {
                        "next_step": "review", "human_action_required": True,
                        "resource_gap": True, "error_code": "CLINGEN_SPECIFICATION_UNAVAILABLE",
                    }
                else:
                    status = StepStatus.PENDING
                    metadata = {}
                db.add(WorkflowStep(
                    id=uuid4(), analysis_id=analysis_id, step_id=stage_id,
                    step_order=order, status=status, attempt=0,
                    input_artifacts=[], output_artifacts=[], metadata_json=metadata,
                ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(
            workflow, "artifact_store_for_organization",
            lambda *_args, **_kwargs: store,
        )
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_a, **_k: store)
        # No final reportability disposition has been entered yet. The real
        # workflow must resume through classification review and stop at that gate.
        monkeypatch.setattr(reportability, "evaluate_analysis", lambda *_args: None)
        monkeypatch.setattr(
            reportability, "final_reportability_state",
            lambda *_args: (False, ["missing_final_reportability_disposition"]),
        )

        workflow.run_variant_analysis(analysis_id)

        # Re-entry after a human classification has been reconciled must remain
        # safe while the downstream reportability gate is unresolved. It must
        # not duplicate the reconciliation audit event or prematurely create a
        # report on the second execution.
        workflow.run_variant_analysis(analysis_id)

        with LocalSession() as db:
            analysis = db.get(Analysis, analysis_id)
            acmg = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "acmg_assessment",
            ))
            review = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "review",
            ))
            reportability_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "reportability",
            ))
            report_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "report",
            ))
            assert acmg.status == StepStatus.SUCCEEDED
            assert acmg.metadata_json["reconciled_after_review"] is True
            assert acmg.metadata_json["classification_automation"] == "MANUAL_REVIEWED"
            assert acmg.metadata_json["manual_classification_count"] == 1
            assert review.status == StepStatus.SUCCEEDED
            assert reportability_step.status == StepStatus.REQUIRES_REVIEW
            assert "missing_final_reportability_disposition" in reportability_step.metadata_json["errors"]
            assert report_step.status == StepStatus.PENDING
            assert analysis.status == AnalysisStatus.REQUIRES_REVIEW
            assert analysis.completed_at is None
            assert db.scalar(select(func.count(Report.id)).where(
                Report.analysis_id == analysis_id,
            )) == 0
            assert db.scalar(select(func.count(AuditEvent.id)).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "ACMG_MANUAL_CLASSIFICATION_RECONCILED",
            )) == 1
    finally:
        engine.dispose()
