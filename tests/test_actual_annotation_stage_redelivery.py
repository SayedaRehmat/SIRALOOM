"""Exercise annotation recovery through the actual workflow body and Celery task wrapper.

The provider/resource plan are deterministic test doubles; the workflow's annotation
stage, response artifact checkpointing, row persistence, partition scheduling, and
redelivery recovery remain production code. This is orchestration coverage, not a
live provider or clinical truth-set validation.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis, AnalysisPartition, Annotation, Artifact, Case, Organization,
    Resource, User, Variant, WorkflowStep,
)
from backend.app.partition_scheduler import configure_partition


def test_actual_annotation_stage_recovers_after_row_commit_and_task_redelivery(
    monkeypatch, tmp_path
):
    import importlib

    queue = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'actual-annotation-recovery.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id, resource_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    key = canonical_key("GRCh38", "1", 555, "T", "C")
    variant_id = stable_variant_uuid(key)
    task_id = "actual-annotation-stage-redelivery"
    provider_calls = {"count": 0}
    persistence_calls = {"count": 0}

    try:
        source = tmp_path / "source.vcf"
        source.write_text(
            "##fileformat=VCFv4.2\n"
            "##contig=<ID=1,length=1000000>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "1\t555\t.\tT\tC\t.\tPASS\t.\n",
            encoding="utf-8",
        )
        # Use a plain VCF here: this fixture is testing annotation recovery,
        # not BGZF/index handling by bcftools.
        import subprocess

        normalized = tmp_path / "normalized.vcf.gz"
        subprocess.run(
            ["bcftools", "view", "-Oz", "-o", str(normalized), str(source)],
            check=True,
            capture_output=True,
            text=True,
        )

        with LocalSession() as db:
            db.add(Organization(
                id=organization_id, name="Actual Stage Recovery Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Actual Stage Recovery", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"ACTUAL-ANNOTATION-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            source_artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=source, filename="source.vcf",
                artifact_type="SOURCE_VCF", media_type="text/plain",
                genome_build="GRCh38", metadata={},
            )
            normalized_artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=normalized, filename="normalized.vcf.gz",
                artifact_type="NORMALIZED_VCF", media_type="application/gzip",
                genome_build="GRCh38", metadata={},
            )
            db.flush()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.QUEUED, queue_task_id=task_id,
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(source_artifact.id)},
                started_at=None, completed_at=None, created_by=user_id,
                analysis_version=1,
            ))
            db.flush()
            db.add(Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1",
                position=555, reference="T", alternate="C",
                normalization_status="NORMALIZED", canonical_key=key,
                identifiers={},
            ))
            resource = Resource(
                id=resource_id, organization_id=organization_id,
                name="Pinned test annotation release", provider="GeneBe",
                resource_type="ANNOTATION", version="test-release",
                genome_build="GRCh38", access_method="API", license_text=None,
                checksum="a" * 64, location="https://fixture.invalid/annotation",
                status="ACTIVE", population_definition=None, metadata_json={},
            )
            db.add(resource)
            for order, step_id, status, metadata, outputs in [
                (1, "validate_input", StepStatus.SUCCEEDED, {"test_checkpoint": True}, [str(source_artifact.id)]),
                (2, "normalize", StepStatus.SUCCEEDED, {"record_count": 1, "test_checkpoint": True}, [str(normalized_artifact.id)]),
                (3, "annotate", StepStatus.PENDING, {}, []),
                (4, "population", StepStatus.PENDING, {}, []),
                (5, "build_evidence", StepStatus.PENDING, {}, []),
                (6, "acmg_assessment", StepStatus.PENDING, {}, []),
                (7, "review", StepStatus.PENDING, {}, []),
                (8, "reportability", StepStatus.PENDING, {}, []),
                (9, "report", StepStatus.PENDING, {}, []),
                (10, "export_provenance", StepStatus.PENDING, {}, []),
            ]:
                db.add(WorkflowStep(
                    id=uuid4(), analysis_id=analysis_id, step_id=step_id,
                    step_order=order, status=status, attempt=1 if step_id == "annotate" else 0,
                    input_artifacts=[], output_artifacts=outputs, metadata_json=metadata,
                ))
            normalize_partition = AnalysisPartition(
                id=uuid4(), analysis_id=analysis_id, step_id="normalize",
                partition_key="0:1", ordinal=0, record_start=0, record_end=1,
                variant_count=1, status="SUCCEEDED",
                metadata_json={"variant_ids": [str(variant_id)]},
                resource_class="STANDARD", cpu_request=1.0, memory_mb=1024,
                attempt=1, lease_owner=None, lease_token=None, lease_expires_at=None,
            )
            configure_partition(normalize_partition, "STANDARD")
            normalize_partition.status = "SUCCEEDED"
            db.add(normalize_partition)
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(db_module, "engine", engine)
        monkeypatch.setattr(workflow, "artifact_store_for_organization", lambda *_a, **_k: store)
        # Isolate the annotation recovery boundary from VCF parser/normalizer
        # behavior: the production workflow still validates the source artifact,
        # loads the persisted normalized artifact, schedules partitions, calls
        # the provider adapter boundary, and persists/reconciles annotations.
        monkeypatch.setattr(
            workflow,
            "_iter_variant_batches",
            lambda *_a, **_k: iter([(
                0,
                [SimpleNamespace(
                    genome_build="GRCh38",
                    chromosome="1",
                    position=555,
                    reference="T",
                    alternate="C",
                )],
            )]),
        )

        class FakeProvider:
            provider_id = "GeneBe"
            provider_version = "api-public-v1"

            def annotate(self, variants, _params):
                provider_calls["count"] += 1
                return [{
                    "chr": v.chromosome, "pos": v.position, "ref": v.reference,
                    "alt": v.alternate, "gene_symbol": "TEST1",
                    "effect": "missense_variant",
                    "_siraloom_annotation_provenance": {
                        "provider": self.provider_id,
                        "provider_version": self.provider_version,
                        "request_fingerprint": "d" * 64,
                        "response_sha256": "e" * 64,
                        "observed_at": "2026-10-10T00:00:00+00:00",
                        "retry_count": 0, "genome": "hg38",
                    },
                } for v in variants]

        provider = FakeProvider()
        contract = SimpleNamespace(
            provider_id="GeneBe",
            provider_version=provider.provider_version,
            access_method="API",
            endpoint="https://fixture.invalid/annotation",
            location="https://fixture.invalid/annotation",
            dataset=None,
            as_dict=lambda: {
                "provider_id": "GeneBe",
                "provider_version": provider.provider_version,
                "access_method": "API",
                "endpoint": "https://fixture.invalid/annotation",
                "location": "https://fixture.invalid/annotation",
                "dataset": None,
            },
        )
        execution = SimpleNamespace(
            resource_id=resource_id,
            resource_version=resource.version,
            qualification_id=uuid4(),
            qualification_version="test-qualification-v1",
            contract=contract,
            contract_hash="f" * 64,
        )
        candidate = SimpleNamespace(resource=resource, execution=execution)
        registry = SimpleNamespace(
            require=lambda **_k: SimpleNamespace(factory=lambda _contract: provider),
            # Population is outside this test's boundary; no population adapter
            # is advertised by the fixture, so the workflow can take its normal
            # missing-optional-capability path after annotation recovery.
            resolve=lambda **_k: None,
        )
        monkeypatch.setattr(workflow, "register_builtin_providers", lambda: registry)

        def fake_execution_plan(*_args, **kwargs):
            requirements = kwargs.get("requirements", ())
            capability = requirements[0].capability if requirements else None
            candidates = [candidate] if capability == workflow.ResourceCapability.ANNOTATION else []
            return SimpleNamespace(
                profile_type="TRIAL_PUBLIC", profile_version="test",
                unavailable_optional=[], for_capability=lambda _capability: candidates,
            )

        monkeypatch.setattr(workflow, "build_resource_execution_plan", fake_execution_plan)
        monkeypatch.setattr(workflow, "resolve_resource_execution", lambda *_a, **_k: execution)
        monkeypatch.setattr(
            workflow, "resolve_resource_with_fallback",
            lambda *_a, **_k: SimpleNamespace(
                resource=resource, used_fallback=False, requested_resource_id=resource_id,
                fallback_resource_id=None,
                decision=workflow.decide_step_outcome(
                    "annotate", workflow.OutcomeKind.SUCCESS,
                    code="TEST_RESOURCE_SELECTED", message="Controlled test resource selected.",
                ),
            ),
        )
        monkeypatch.setattr(workflow, "record_workflow_decision", lambda *_a, **_k: None)

        real_persist = workflow._persist_annotation_batch_rows

        def crash_once_after_durable_annotation_rows(*args, **kwargs):
            result = real_persist(*args, **kwargs)
            persistence_calls["count"] += 1
            if persistence_calls["count"] == 1:
                # The helper has committed annotation rows, but the caller has not
                # yet committed the batch-success checkpoint/partition completion.
                raise SystemExit(73)
            return result

        monkeypatch.setattr(workflow, "_persist_annotation_batch_rows", crash_once_after_durable_annotation_rows)
        real_step = workflow._step

        def stop_after_annotation_is_reconciled(db, received_analysis_id, step_id):
            # ensure_steps() reads/creates all workflow steps before annotation
            # begins, including population. Stop only on the redelivered delivery,
            # after annotation has been reconciled. A correct implementation may
            # reconcile the durable row from its checkpoint without invoking the
            # persistence helper a second time.
            delivery_info = queue.run_analysis_task.request.delivery_info or {}
            if step_id == "population" and delivery_info.get("redelivered"):
                raise SystemExit(74)
            return real_step(db, received_analysis_id, step_id)

        monkeypatch.setattr(workflow, "_step", stop_after_annotation_is_reconciled)

        # Delivery 1 simulates a worker dying after the annotation-row commit.
        # The broker, not the first task invocation, performs redelivery.
        queue.run_analysis_task.push_request(
            id=task_id, retries=0, delivery_info={"redelivered": False}
        )
        first_delivery_exit = None
        try:
            try:
                queue.run_analysis_task.run(str(analysis_id))
            except SystemExit as exc:
                first_delivery_exit = exc
        finally:
            queue.run_analysis_task.pop_request()
        if first_delivery_exit is None:
            with LocalSession() as db:
                current_analysis = db.get(Analysis, analysis_id)
                step_states = [
                    (step.step_id, str(step.status), step.error_code, step.error_message)
                    for step in db.scalars(
                        select(WorkflowStep).where(WorkflowStep.analysis_id == analysis_id)
                        .order_by(WorkflowStep.step_order)
                    ).all()
                ]
            pytest.fail(
                "First delivery did not reach the injected post-commit worker-loss boundary; "
                f"provider_calls={provider_calls['count']}, "
                f"persistence_calls={persistence_calls['count']}, "
                f"analysis_status={current_analysis.status if current_analysis else None}, "
                f"step_states={step_states}"
            )
        assert str(first_delivery_exit.code) == "73"

        # Delivery 2 must use the same task ID with Celery's redelivered flag so
        # the production wrapper runs interrupted-execution reconciliation.
        queue.run_analysis_task.push_request(
            id=task_id, retries=0, delivery_info={"redelivered": True}
        )
        try:
            with pytest.raises(SystemExit, match="74"):
                queue.run_analysis_task.run(str(analysis_id))
        finally:
            queue.run_analysis_task.pop_request()

        with LocalSession() as db:
            annotations = db.scalars(select(Annotation).where(
                Annotation.analysis_id == analysis_id
            )).all()
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id, WorkflowStep.step_id == "annotate"
            ))
            partitions = db.scalars(select(AnalysisPartition).where(
                AnalysisPartition.analysis_id == analysis_id,
                AnalysisPartition.step_id == "annotate",
            )).all()
            assert len(annotations) == 1
            assert annotations[0].resource_id == resource_id
            assert annotations[0].resource_version == "test-release"
            assert annotations[0].request_fingerprint == "d" * 64
            assert annotations[0].response_sha256 == "e" * 64
            assert step.status == StepStatus.SUCCEEDED
            assert step.metadata_json["batches"]["0:1"]["status"] == "SUCCEEDED"
            assert partitions and all(p.status == "SUCCEEDED" for p in partitions)
            assert db.get(Analysis, analysis_id).parent_analysis_id is None
        assert provider_calls["count"] == 1
        assert 1 <= persistence_calls["count"] <= 2
    finally:
        engine.dispose()
