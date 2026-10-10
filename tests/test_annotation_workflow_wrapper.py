"""Production-wrapper continuation test: worker loss after annotation rows commit.

Uses the real run_analysis_task and run_variant_analysis workflow with a local
controlled annotation provider. The only injected fault is a process-like
SystemExit after the production annotation persistence helper commits rows and
before the batch-success checkpoint. No external scientific API is called.
"""
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Annotation,
    Artifact,
    Case,
    Evidence,
    Organization,
    Resource,
    User,
    WorkflowStep,
)


def test_production_celery_wrapper_recovers_annotation_and_persists_evidence(
    monkeypatch, tmp_path
):
    import importlib

    queue_module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")
    from backend.app.domain.resource_capabilities import ResourceCapability

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'wrapper-recovery.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    analysis_id, case_id, organization_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    resource_id = uuid4()
    task_id = "annotation-evidence-recovery-test"
    provider_calls = {"count": 0}
    fault = {"armed": True}

    vcf_text = (
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "##contig=<ID=1,length=248956422>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t555\t.\tT\tC\t.\tPASS\t.\n"
    )
    source_path = tmp_path / "input.vcf"
    source_path.write_text(vcf_text, encoding="utf-8")

    try:
        with LocalSession() as db:
            db.add(Organization(
                id=organization_id, name="Wrapper Recovery Lab",
                external_identifier=str(organization_id),
            ))
            db.commit()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Wrapper Recovery Test", role="ADMIN", status="ACTIVE",
            ))
            db.commit()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"WRAP-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.commit()

            input_artifact = artifact_store.put_file(
                db=db, case_id=case_id, analysis_id=None, source_path=source_path,
                filename="input.vcf", artifact_type="VCF", media_type="text/vcf",
                genome_build="GRCh38", validation_status="VALIDATED",
            )
            db.commit()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.QUEUED, queue_task_id=task_id,
                reference_build="GRCh38",
                configuration={
                    "input_artifact_id": str(input_artifact.id),
                    "annotation_resource_id": str(resource_id),
                    "partition_size": 1,
                    "evidence_batch_size": 1,
                },
                started_at=None, completed_at=None, created_by=user_id,
                analysis_version=1,
            ))
            db.commit()
            input_artifact.analysis_id = analysis_id
            db.add(input_artifact)
            normalized_artifact = artifact_store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id, source_path=source_path,
                filename="normalized.vcf", artifact_type="NORMALIZED_VCF",
                media_type="text/vcf", genome_build="GRCh38",
                validation_status="VALIDATED",
            )
            resource = Resource(
                id=resource_id, organization_id=organization_id,
                name="GeneBe controlled test provider", provider="GeneBe",
                resource_type="ANNOTATION", version="test-release",
                genome_build="GRCh38", access_method="API", license_text=None,
                checksum="a" * 64, location="https://fixture.invalid/annotation",
                status="ACTIVE", population_definition=None, metadata_json={},
            )
            db.add(resource)
            db.commit()

            succeeded_before_annotation = {
                "validate_input", "normalize", "population",
                "acmg_assessment", "review", "reportability", "report",
                "export_provenance",
            }
            for step_id, step_order in workflow.WORKFLOW_STEPS:
                db.add(WorkflowStep(
                    id=uuid4(), analysis_id=analysis_id, step_id=step_id,
                    step_order=step_order,
                    status=(
                        StepStatus.SUCCEEDED
                        if step_id in succeeded_before_annotation
                        else StepStatus.PENDING
                    ),
                    attempt=1 if step_id in succeeded_before_annotation else 0,
                    input_artifacts=(
                        [str(normalized_artifact.id)] if step_id == "normalize" else []
                    ),
                    output_artifacts=(
                        [str(normalized_artifact.id)] if step_id == "normalize" else []
                    ),
                    metadata_json=(
                        {"record_count": 1, "variant_count": 1}
                        if step_id == "normalize" else {}
                    ),
                ))
            db.commit()

        class FakeProvider:
            provider_id = "GeneBe"
            provider_version = "api-public-v1"

            def annotate(self, variants, _params):
                provider_calls["count"] += 1
                output = []
                for variant in variants:
                    output.append({
                        "chr": variant.chromosome,
                        "pos": variant.position,
                        "ref": variant.reference,
                        "alt": variant.alternate,
                        "gene_symbol": "TEST1",
                        "effect": "missense_variant",
                        "frequency_reference_population": 0.00001,
                        "computational_score_selected": 0.91,
                        "_siraloom_annotation_provenance": {
                            "provider": self.provider_id,
                            "provider_version": self.provider_version,
                            "request_fingerprint": "d" * 64,
                            "response_sha256": "e" * 64,
                            "observed_at": "2026-10-10T00:00:00+00:00",
                            "retry_count": 0,
                        },
                    })
                return output

        fake_provider = FakeProvider()
        contract = SimpleNamespace(
            provider_id="GeneBe", provider_version="api-public-v1",
            access_method="API", endpoint="https://fixture.invalid/annotation",
            location=None, dataset=None,
        )
        resolved = SimpleNamespace(
            contract=contract, resource_id=resource_id, resource_version="test-release",
            contract_hash="f" * 64,
            snapshot={
                "resource_id": str(resource_id), "resource_version": "test-release",
                "provider_id": "GeneBe", "provider_version": "api-public-v1",
                "contract_hash": "f" * 64,
            },
        )
        candidate = SimpleNamespace(resource=resource, execution=resolved)

        def plan_builder(_db, *, organization_id, requirements):
            capability = requirements[0].capability if requirements else None
            is_annotation = capability == ResourceCapability.ANNOTATION
            return SimpleNamespace(
                profile_type="TRIAL_PUBLIC", profile_version="test",
                unavailable_optional=[],
                for_capability=lambda requested: [candidate] if (
                    is_annotation and requested == ResourceCapability.ANNOTATION
                ) else [],
            )

        class Registry:
            def require(self, *, provider_id, provider_version):
                assert provider_id == "GeneBe"
                assert provider_version == "api-public-v1"
                return SimpleNamespace(factory=lambda _contract: fake_provider)

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(db_module, "engine", engine)
        monkeypatch.setattr(
            workflow, "artifact_store_for_organization",
            lambda *_args, **_kwargs: artifact_store,
        )
        monkeypatch.setattr(
            workflow, "_materialize_artifact_for_worker",
            lambda artifact, _temporary_paths: Path(unquote(urlparse(artifact.storage_uri).path)),
        )
        monkeypatch.setattr(workflow, "build_resource_execution_plan", plan_builder)
        monkeypatch.setattr(workflow, "register_builtin_providers", lambda: Registry())
        monkeypatch.setattr(
            workflow, "resolve_resource_execution",
            lambda _db, *, resource: resolved,
        )
        monkeypatch.setattr(
            workflow, "resolve_resource_with_fallback",
            lambda _db, **kwargs: SimpleNamespace(
                resource=resource, used_fallback=False,
                requested_resource_id=resource_id, fallback_resource_id=None,
                decision=SimpleNamespace(
                    code="RESOURCE_SELECTED", action=SimpleNamespace(value="CONTINUE"),
                    message="controlled test resource",
                ),
            ),
        )
        monkeypatch.setattr(workflow, "record_workflow_decision", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            workflow, "start_resource_execution",
            lambda *_args, **_kwargs: SimpleNamespace(id=uuid4()),
        )
        monkeypatch.setattr(workflow, "complete_resource_execution", lambda *_args, **_kwargs: None)

        # These fixture preconditions are already validated/persisted artifacts;
        # pin the corresponding upstream steps as complete while exercising the
        # actual annotation, recovery, and evidence stages below.
        original_step = workflow._step

        def step_with_prevalidated_inputs(db, requested_analysis_id, step_id):
            step = original_step(db, requested_analysis_id, step_id)
            if step_id in succeeded_before_annotation:
                step.status = StepStatus.SUCCEEDED
                if step_id == "normalize":
                    step.metadata_json = {
                        **(step.metadata_json or {}),
                        "record_count": 1,
                        "variant_count": 1,
                    }
                db.add(step)
                db.commit()
            return step

        monkeypatch.setattr(workflow, "_step", step_with_prevalidated_inputs)

        original_persist_rows = workflow._persist_annotation_batch_rows

        def persist_rows_then_lose_worker(*args, **kwargs):
            result = original_persist_rows(*args, **kwargs)
            if fault["armed"]:
                fault["armed"] = False
                # SystemExit bypasses workflow's ordinary Exception handler,
                # analogous to abrupt process death, after the row transaction.
                raise SystemExit(73)
            return result

        monkeypatch.setattr(
            workflow, "_persist_annotation_batch_rows", persist_rows_then_lose_worker
        )

        # First execution is the real production Celery task and workflow.
        queue_module.run_analysis_task.push_request(
            id=task_id, retries=0, delivery_info={"redelivered": False}
        )
        did_crash = False
        try:
            try:
                queue_module.run_analysis_task.run(str(analysis_id))
            except SystemExit:
                did_crash = True
        finally:
            queue_module.run_analysis_task.pop_request()

        if not did_crash:
            with LocalSession() as diagnostic_db:
                failed_step = diagnostic_db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "annotate",
                ))
                normalize_step = diagnostic_db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "normalize",
                ))
                all_steps = {
                    row.step_id: str(row.status)
                    for row in diagnostic_db.scalars(select(WorkflowStep).where(
                        WorkflowStep.analysis_id == analysis_id
                    )).all()
                }
                current_analysis = diagnostic_db.get(Analysis, analysis_id)
                raise AssertionError(
                    "annotation persistence failpoint was not reached; "
                    f"fault_armed={fault['armed']}, provider_calls={provider_calls['count']}, "
                    f"analysis_status={current_analysis.status}, "
                    f"normalize_status={normalize_step.status}, "
                    f"normalize_error={normalize_step.error_code}:{normalize_step.error_message}, "
                    f"annotation_step_status={failed_step.status}, "
                    f"error_code={failed_step.error_code}, error_message={failed_step.error_message}, "
                    f"all_steps={all_steps}"
                )

        with LocalSession() as db:
            assert db.scalar(select(func.count(Annotation.id)).where(
                Annotation.analysis_id == analysis_id
            )) == 1
            assert db.scalar(select(func.count(Evidence.id)).where(
                Evidence.analysis_id == analysis_id
            )) == 0
            annotation = db.scalar(select(Annotation).where(
                Annotation.analysis_id == analysis_id
            ))
            assert annotation.resource_id == resource_id
            assert annotation.resource_version == "test-release"
            assert annotation.request_fingerprint == "d" * 64
            assert annotation.response_sha256 == "e" * 64
            annotation_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "annotate",
            ))
            assert annotation_step.status == StepStatus.RUNNING
            assert annotation_step.metadata_json["batches"]["0:1"]["status"] == "RESPONSE_PERSISTED"

        # Broker redelivery: the production wrapper runs its recovery path before
        # calling the real run_variant_analysis again.
        monkeypatch.setattr(workflow, "_persist_annotation_batch_rows", original_persist_rows)
        queue_module.run_analysis_task.push_request(
            id=task_id, retries=0, delivery_info={"redelivered": True}
        )
        try:
            result = queue_module.run_analysis_task.run(str(analysis_id))
        finally:
            queue_module.run_analysis_task.pop_request()

        assert result["status"] == str(AnalysisStatus.SUCCEEDED)
        assert provider_calls["count"] == 1
        with LocalSession() as db:
            analysis = db.get(Analysis, analysis_id)
            assert analysis.status == AnalysisStatus.SUCCEEDED
            assert db.scalar(select(func.count(Annotation.id)).where(
                Annotation.analysis_id == analysis_id
            )) == 1
            evidence_rows = db.scalars(select(Evidence).where(
                Evidence.analysis_id == analysis_id
            )).all()
            assert evidence_rows, "real evidence stage must persist evidence rows"
            assert all(row.variant_id == db.scalar(select(Annotation.variant_id).where(
                Annotation.analysis_id == analysis_id
            )) for row in evidence_rows)
            assert all(row.analysis_id == analysis_id for row in evidence_rows)
            assert all(row.resource_id == resource_id for row in evidence_rows)
            assert all(row.source_version == "test-release" for row in evidence_rows)
            annotation_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "annotate",
            ))
            evidence_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "build_evidence",
            ))
            assert annotation_step.status == StepStatus.SUCCEEDED
            assert annotation_step.metadata_json["batches"]["0:1"]["status"] == "SUCCEEDED"
            assert evidence_step.status == StepStatus.SUCCEEDED
            assert evidence_step.metadata_json["batches"]["0:1"]["status"] == "SUCCEEDED"
    finally:
        engine.dispose()
