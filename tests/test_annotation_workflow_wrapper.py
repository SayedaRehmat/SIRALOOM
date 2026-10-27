"""Production Celery wrapper recovery through durable annotation and evidence.

The wrapper, recovery function, response artifact/checkpoint helpers, annotation
row persistence helper, evidence engine, and DB models are production code. The
controlled workflow delegate avoids external scientific providers and focuses
this test on the worker-recovery boundary; the full scientific benchmark is a
separate gate.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.evidence import evidence_fingerprint
from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid
from backend.app.evidence.engine import EvidenceContext, EvidenceEngine
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisPartition,
    Annotation,
    Artifact,
    Case,
    Evidence,
    Organization,
    Resource,
    User,
    Variant,
    WorkflowStep,
)
from backend.app.partition_scheduler import PartitionScheduler, configure_partition


def test_production_task_wrapper_recovers_annotation_and_persists_evidence(
    monkeypatch, tmp_path
):
    import importlib

    queue_module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'wrapper-recovery.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    parent_id, analysis_id = uuid4(), uuid4()
    resource_id = uuid4()
    variant_key = canonical_key("GRCh38", "1", 555, "T", "C")
    variant_id = stable_variant_uuid(variant_key)
    task_id = "production-wrapper-annotation-recovery"
    provider_calls = {"count": 0}
    delegate_calls = {"count": 0}

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
            db.add(Analysis(
                id=parent_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.SUCCEEDED, queue_task_id=None,
                reference_build="GRCh38", configuration={}, started_at=None,
                completed_at=None, created_by=user_id, analysis_version=1,
            ))
            db.commit()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=parent_id,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.QUEUED, queue_task_id=task_id,
                reference_build="GRCh38", configuration={}, started_at=None,
                completed_at=None, created_by=user_id, analysis_version=2,
            ))
            db.commit()
            db.add(Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1",
                position=555, reference="T", alternate="C",
                normalization_status="NORMALIZED", canonical_key=variant_key,
                identifiers={},
            ))
            resource = Resource(
                id=resource_id, organization_id=organization_id,
                name="GeneBe controlled test provider", provider="GeneBe",
                resource_type="ANNOTATION", version="test-release",
                genome_build="GRCh38", access_method="API", license_text=None,
                checksum="a" * 64, location="https://fixture.invalid/annotation",
                status="ACTIVE", population_definition=None, metadata_json={},
            )
            db.add(resource)
            step = WorkflowStep(
                id=uuid4(), analysis_id=analysis_id, step_id="annotate", step_order=3,
                status=StepStatus.RUNNING, attempt=1, input_artifacts=[], output_artifacts=[],
                metadata_json={"batches": {"0:1": {"status": "RUNNING", "attempt": 1}}},
            )
            evidence_step = WorkflowStep(
                id=uuid4(), analysis_id=analysis_id, step_id="build_evidence", step_order=5,
                status=StepStatus.PENDING, attempt=0, input_artifacts=[], output_artifacts=[],
                metadata_json={},
            )
            partition = AnalysisPartition(
                id=uuid4(), analysis_id=analysis_id, step_id="annotate",
                partition_key="0:1", ordinal=0, record_start=0, record_end=1,
                variant_count=1, status="RUNNING", metadata_json={"variant_ids": [str(variant_id)]},
                resource_class="STANDARD", cpu_request=1.0, memory_mb=1024,
                attempt=1, lease_owner="worker-before-crash", lease_token="lease-before-crash",
                lease_expires_at=None,
            )
            configure_partition(partition, "STANDARD")
            partition.status = "RUNNING"
            partition.lease_owner = "worker-before-crash"
            partition.lease_token = "lease-before-crash"
            db.add_all([step, evidence_step, partition])
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(db_module, "engine", engine)
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_args, **_kwargs: store)

        class FakeProvider:
            provider_id = "GeneBe"
            provider_version = "api-public-v1"

            def annotate(self, variants, _params):
                provider_calls["count"] += 1
                return [{
                    "chr": item.chromosome, "pos": item.position,
                    "ref": item.reference, "alt": item.alternate,
                    "gene_symbol": "TEST1", "effect": "missense_variant",
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
                } for item in variants]

        provider = FakeProvider()
        variant = SimpleNamespace(
            genome_build="GRCh38", chromosome="1", position=555,
            reference="T", alternate="C",
        )

        def persist_test_evidence(db, received_analysis_id):
            annotation = db.scalar(select(Annotation).where(
                Annotation.analysis_id == received_analysis_id
            ))
            assert annotation is not None
            records = EvidenceEngine().build_from_annotation(
                variant_id=annotation.variant_id,
                annotation=annotation.payload["normalized"],
                provider_name=annotation.provider_name,
                provider_version=annotation.provider_version,
                resource_name=annotation.resource_name,
                resource_version=annotation.resource_version,
                context=EvidenceContext(analysis_id=received_analysis_id),
            )
            created_count = 0
            for record in records:
                fingerprint = evidence_fingerprint(
                    variant_id=record.variant_id,
                    analysis_id=received_analysis_id,
                    evidence_type=record.evidence_type,
                    statement=record.statement,
                    direction=record.direction,
                    source_name=record.source_name,
                    source_version=record.source_version,
                    observation_ids=record.observation_ids,
                    payload=record.payload,
                    resource_id=annotation.resource_id,
                    source_record_id=None,
                    request_fingerprint=annotation.request_fingerprint,
                    response_sha256=annotation.response_sha256,
                )
                exists = db.scalar(select(Evidence.id).where(
                    Evidence.analysis_id == received_analysis_id,
                    Evidence.evidence_fingerprint == fingerprint,
                ))
                if exists:
                    continue
                db.add(Evidence(
                    id=record.evidence_id, variant_id=record.variant_id,
                    analysis_id=received_analysis_id, evidence_type=record.evidence_type,
                    statement=record.statement, direction=record.direction,
                    source_name=record.source_name, source_version=record.source_version,
                    resource_id=annotation.resource_id, source_record_id=None,
                    request_fingerprint=annotation.request_fingerprint,
                    response_sha256=annotation.response_sha256,
                    request_metadata=annotation.request_metadata or {},
                    observed_at=annotation.observed_at,
                    observation_ids=[str(x) for x in record.observation_ids],
                    payload=record.payload, created_by_type="SYSTEM",
                    created_by_id="siraloom-evidence", evidence_fingerprint=fingerprint,
                ))
                created_count += 1
            db.commit()
            return created_count

        def controlled_workflow_delegate(received_analysis_id):
            assert str(received_analysis_id) == str(analysis_id)
            delegate_calls["count"] += 1
            with LocalSession() as db:
                analysis = db.get(Analysis, analysis_id)
                annotation_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "annotate",
                ))
                resource_row = db.get(Resource, resource_id)
                if delegate_calls["count"] == 1:
                    payloads = provider.annotate([variant], {"genome": "hg38"})
                    workflow._persist_annotation_response_checkpoint(
                        db, store, analysis=analysis, step=annotation_step,
                        start=0, end=1, payloads=payloads, resource=resource_row,
                        provider_id=provider.provider_id,
                        provider_version=provider.provider_version,
                    )
                    workflow._persist_annotation_batch_rows(
                        db, analysis=analysis, provider=provider,
                        annotation_resource=resource_row,
                        variant_ids={variant_key: variant_id}, existing_rows=[],
                        payloads=[dict(payloads[0])], batch_key="0:1",
                    )
                    # Persist evidence, then simulate worker death before the
                    # evidence-step/batch success checkpoint is committed.
                    created_before_crash = persist_test_evidence(db, analysis_id)
                    assert created_before_crash > 0
                    raise SystemExit(73)

                # The production task wrapper has already invoked the production
                # recover_interrupted_execution() before this second delegate call.
                replay_payloads = workflow._load_annotation_response_checkpoint(
                    db, step=annotation_step, start=0, end=1, analysis=analysis,
                    resource=resource_row, provider_id=provider.provider_id,
                    provider_version=provider.provider_version, temporary_paths=[],
                )
                assert replay_payloads is not None
                existing_rows = db.scalars(select(Annotation).where(
                    Annotation.analysis_id == analysis_id,
                    Annotation.variant_id == variant_id,
                    Annotation.resource_id == resource_id,
                    Annotation.resource_version == resource_row.version,
                )).all()
                created, returned = workflow._persist_annotation_batch_rows(
                    db, analysis=analysis, provider=provider,
                    annotation_resource=resource_row,
                    variant_ids={variant_key: variant_id}, existing_rows=existing_rows,
                    payloads=replay_payloads, batch_key="0:1",
                )
                assert (created, returned) == (0, 1)

                claimed = PartitionScheduler(
                    db, cpu_capacity=1, memory_mb=1024, lease_seconds=60
                ).claim_next(analysis_id, "annotate", "worker-after-redelivery")
                assert claimed is not None
                workflow._save_batch_checkpoint(
                    db, annotation_step, 0, 1, status="SUCCEEDED", attempt=2,
                    metadata={
                        "provider": provider.provider_id, "new_annotation_rows": 0,
                        "returned_rows": 1, "resource_id": str(resource_id),
                        "resource_version": resource_row.version,
                    }, commit=False,
                )
                PartitionScheduler(
                    db, cpu_capacity=1, memory_mb=1024, lease_seconds=60
                ).succeed(
                    claimed.id, "worker-after-redelivery", claimed.lease_token,
                    metadata={"provider": provider.provider_id, "variant_count": 1},
                )
                db.commit()

                created_evidence = persist_test_evidence(db, analysis_id)
                persisted_evidence_count = workflow._count_persisted_evidence(db, analysis_id)
                assert persisted_evidence_count > 0
                # The first attempt committed evidence but died before recording
                # success. A retry must deduplicate the evidence and derive its
                # outcome from durable rows, not this attempt's insertion count.
                assert created_evidence == 0
                annotation_step.status = StepStatus.SUCCEEDED
                evidence_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "build_evidence",
                ))
                evidence_step.status = StepStatus.SUCCEEDED
                evidence_step.metadata_json = {
                    **(evidence_step.metadata_json or {}),
                    "batches": {"0:1": {"status": "SUCCEEDED", "created_evidence": created_evidence}},
                    "created_evidence": created_evidence,
                    "persisted_evidence": persisted_evidence_count,
                }
                analysis.status = AnalysisStatus.SUCCEEDED
                db.commit()

        # Use the real production Celery task wrapper. Only the workflow delegate
        # is controlled so no external provider/network call can occur in CI.
        monkeypatch.setattr(workflow, "run_variant_analysis", controlled_workflow_delegate)
        queue_module.run_analysis_task.push_request(
            id=task_id, retries=0, delivery_info={"redelivered": False}
        )
        try:
            with pytest.raises(SystemExit):
                queue_module.run_analysis_task.run(str(analysis_id))
        finally:
            queue_module.run_analysis_task.pop_request()

        with LocalSession() as db:
            assert db.scalar(select(func.count(Annotation.id)).where(
                Annotation.analysis_id == analysis_id
            )) == 1
            # Evidence was committed before the worker died, while the
            # evidence success checkpoint was intentionally not committed.
            assert db.scalar(select(func.count(Evidence.id)).where(
                Evidence.analysis_id == analysis_id
            )) > 0
            evidence_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "build_evidence",
            ))
            assert evidence_step.status == StepStatus.PENDING
            annotation_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "annotate",
            ))
            assert annotation_step.status == StepStatus.RUNNING
            assert annotation_step.metadata_json["batches"]["0:1"]["status"] == "RESPONSE_PERSISTED"

        queue_module.run_analysis_task.push_request(
            id=task_id, retries=0, delivery_info={"redelivered": True}
        )
        try:
            result = queue_module.run_analysis_task.run(str(analysis_id))
        finally:
            queue_module.run_analysis_task.pop_request()

        assert result["status"] == str(AnalysisStatus.SUCCEEDED)
        assert delegate_calls["count"] == 2
        assert provider_calls["count"] == 1
        with LocalSession() as db:
            child = db.get(Analysis, analysis_id)
            assert child.parent_analysis_id == parent_id
            assert child.status == AnalysisStatus.SUCCEEDED
            assert db.scalar(select(func.count(Annotation.id)).where(
                Annotation.analysis_id == analysis_id
            )) == 1
            annotation = db.scalar(select(Annotation).where(
                Annotation.analysis_id == analysis_id
            ))
            assert annotation.resource_id == resource_id
            assert annotation.resource_version == "test-release"
            assert annotation.request_fingerprint == "d" * 64
            assert annotation.response_sha256 == "e" * 64
            evidence_rows = db.scalars(select(Evidence).where(
                Evidence.analysis_id == analysis_id
            )).all()
            assert evidence_rows
            assert all(row.variant_id == variant_id for row in evidence_rows)
            assert all(row.resource_id == resource_id for row in evidence_rows)
            # Source-version semantics vary by evidence type; the immutable
            # resource foreign key is the release identity for this observation.
            assert db.get(Resource, resource_id).version == "test-release"
            assert all(row.request_fingerprint == "d" * 64 for row in evidence_rows)
            assert all(row.response_sha256 == "e" * 64 for row in evidence_rows)
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
            assert db.scalar(select(AnalysisPartition.status).where(
                AnalysisPartition.analysis_id == analysis_id,
                AnalysisPartition.step_id == "annotate",
            )) == "SUCCEEDED"
    finally:
        engine.dispose()


def test_run_variant_analysis_resolves_case_without_local_name_shadowing(
    monkeypatch, tmp_path
):
    """Guard the real workflow entry point against a local-import UnboundLocalError."""
    import importlib

    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow-entry.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        with LocalSession() as db:
            db.add(Organization(
                id=organization_id, name="Workflow Entry Lab",
                external_identifier=str(organization_id),
            ))
            db.commit()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Workflow Entry Test", role="ADMIN", status="ACTIVE",
            ))
            db.commit()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"ENTRY-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.commit()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.RUNNING, queue_task_id=None,
                reference_build="GRCh38", configuration={}, started_at=None,
                completed_at=None, created_by=user_id, analysis_version=1,
            ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(
            workflow, "artifact_store_for_organization",
            lambda *_args, **_kwargs: ArtifactStore(tmp_path / "workflow-artifacts"),
        )
        # Reaching the expected missing-input configuration error proves the
        # Case lookup succeeded; the regression was an UnboundLocalError first.
        with pytest.raises(KeyError, match="input_artifact_id"):
            workflow.run_variant_analysis(analysis_id)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("foreign_case", "artifact_type", "validation_status", "artifact_build", "message"),
    [
        (True, "VCF", "VALID", "GRCh38", "different case"),
        (False, "NORMALIZED_VCF", "VALID", "GRCh38", "not a primary VCF"),
        (False, "VCF", "INVALID", "GRCh38", "pass ingestion validation"),
        (False, "VCF", "VALID", "GRCh37", "reference assembly must match"),
    ],
)
def test_worker_rejects_unbound_or_invalid_analysis_input_before_reading(
    monkeypatch,
    tmp_path,
    foreign_case,
    artifact_type,
    validation_status,
    artifact_build,
    message,
):
    import hashlib
    import importlib

    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-input-lineage.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    organization_id, foreign_organization_id = uuid4(), uuid4()
    user_id, foreign_user_id = uuid4(), uuid4()
    case_id, foreign_case_id, analysis_id, artifact_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    try:
        with LocalSession() as db:
            db.add_all([
                Organization(id=organization_id, name="Input Owner Lab"),
                Organization(id=foreign_organization_id, name="Other Lab"),
            ])
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Input Lineage Test", role="ADMIN", status="ACTIVE",
            ))
            db.add(User(
                id=foreign_user_id, organization_id=foreign_organization_id,
                external_subject=str(foreign_user_id), email=f"{foreign_user_id}@test.local",
                display_name="Foreign Input Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add_all([
                Case(
                    id=case_id, organization_id=organization_id,
                    case_identifier=f"INPUT-{case_id}", status="OPEN",
                    clinical_context={}, language="en", created_by=user_id,
                ),
                Case(
                    id=foreign_case_id, organization_id=foreign_organization_id,
                    case_identifier=f"FOREIGN-{foreign_case_id}", status="OPEN",
                    clinical_context={}, language="en", created_by=foreign_user_id,
                ),
            ])
            db.flush()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.RUNNING, queue_task_id=None,
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(artifact_id)},
                started_at=None, completed_at=None, created_by=user_id, analysis_version=1,
            ))
            db.flush()
            db.add(Artifact(
                id=artifact_id,
                case_id=foreign_case_id if foreign_case else case_id,
                analysis_id=None,
                artifact_type=artifact_type,
                filename="input.vcf",
                media_type="text/plain",
                size_bytes=0,
                sha256=hashlib.sha256(b"").hexdigest(),
                storage_uri="siraloom://must-not-be-read/input.vcf",
                genome_build=artifact_build,
                validation_status=validation_status,
                metadata_json={"validation": {"sample_names": ["PROBAND"]}},
            ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)

        def _store(_db, *, organization_id):
            assert organization_id == expected_organization_id
            return SimpleNamespace()

        expected_organization_id = organization_id
        monkeypatch.setattr(workflow, "artifact_store_for_organization", _store)
        monkeypatch.setattr(
            workflow,
            "_materialize_artifact_for_worker",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("invalid input must be rejected before reading bytes")
            ),
        )

        with pytest.raises(RuntimeError, match=message):
            workflow.run_variant_analysis(analysis_id)

        with LocalSession() as db:
            assert db.get(Analysis, analysis_id).status == AnalysisStatus.FAILED
    finally:
        engine.dispose()


def test_terminal_provenance_is_persisted_before_analysis_succeeds(tmp_path):
    import json
    from datetime import datetime, timezone

    from backend.app.domain.enums import AnalysisStatus, StepStatus
    from backend.app.infrastructure.audit.service import AuditService
    from backend.app.infrastructure.db.models import Artifact, AuditEvent, Report
    from backend.app.workflows.variant import _persist_terminal_provenance

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'terminal-provenance.db'}")
    Base.metadata.create_all(engine)
    store = ArtifactStore(tmp_path / "terminal-artifacts")
    organization_id, user_id, case_id, analysis_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )

    with Session(engine) as db:
        db.add(Organization(
            id=organization_id, name="Terminal Provenance Lab",
            external_identifier=str(organization_id),
        ))
        db.flush()
        db.add(User(
            id=user_id, organization_id=organization_id,
            external_subject=str(user_id), email=f"{user_id}@test.local",
            display_name="Provenance Reviewer", role="ADMIN", status="ACTIVE",
        ))
        db.flush()
        db.add(Case(
            id=case_id, organization_id=organization_id,
            case_identifier="PROV-TERMINAL-001", status="ACTIVE",
            clinical_context={}, language="en", created_by=user_id,
        ))
        db.flush()
        db.add(Analysis(
            id=analysis_id, case_id=case_id, parent_analysis_id=None,
            assay_id=None, analysis_type="VARIANT_INTERPRETATION",
            workflow_id="variant-v1", workflow_version="test",
            status=AnalysisStatus.REQUIRES_REVIEW, queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=datetime.now(timezone.utc),
            completed_at=None, created_by=user_id, analysis_version=1,
        ))
        db.flush()
        db.add(Report(
            id=uuid4(), case_id=case_id, analysis_id=analysis_id,
            report_version=1, language="en", report_type="CLINICAL_INTERPRETATION",
            status="FINAL", content_json={"report_status": "FINAL"},
        ))
        step = WorkflowStep(
            id=uuid4(), analysis_id=analysis_id, step_id="export_provenance",
            step_order=10, status=StepStatus.RUNNING, attempt=1,
            input_artifacts=[], output_artifacts=[], metadata_json={},
        )
        db.add(step)
        db.commit()

        analysis = db.get(Analysis, analysis_id)
        step = db.get(WorkflowStep, step.id)
        artifact = _persist_terminal_provenance(
            db, artifacts=store, analysis=analysis, provenance_step=step,
            audit=AuditService(db),
        )

        db.refresh(analysis)
        db.refresh(step)
        assert analysis.status == AnalysisStatus.SUCCEEDED
        assert analysis.completed_at is not None
        assert step.status == StepStatus.SUCCEEDED
        assert step.output_artifacts == [str(artifact.id)]
        assert step.metadata_json["provenance_artifact_id"] == str(artifact.id)
        assert db.get(Artifact, artifact.id) is not None
        event = db.query(AuditEvent).filter_by(
            event_type="PROVENANCE_EXPORT_COMPLETED",
            analysis_id=analysis_id,
        ).one()
        assert event.output_artifacts[0]["sha256"] == artifact.sha256
        assert event.payload["next_step"] == "analysis_complete"

        from backend.app.domain.local_uri import local_path_from_uri

        stored_path = local_path_from_uri(artifact.storage_uri)
        manifest = json.loads(stored_path.read_text(encoding="utf-8"))
        assert manifest["analysis_id"] == str(analysis_id)
        assert manifest["case_id"] == str(case_id)
        assert any(item["step_id"] == "export_provenance" for item in manifest["steps"])
