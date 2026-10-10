from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.app.adapters.annotation.genebe import GeneBeProvider
from backend.app.adapters.population.gnomad import GnomADGraphQLProvider
from backend.app.domain.resource_execution import ResourceExecutionError, resolve_resource_execution
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, Annotation, Resource, ResourceQualification


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Analysis.__table__,
            Resource.__table__,
            ResourceQualification.__table__,
            Annotation.__table__,
        ],
    )
    return engine, Session(engine)


def _resource(db, *, provider="GeneBe", access_method="API", endpoint="https://qualified.example/api", dataset=None):
    resource = Resource(
        id=uuid4(),
        organization_id=None,
        name=provider,
        provider=provider,
        resource_type="ANNOTATION" if provider == "GeneBe" else "POPULATION",
        version="v1",
        genome_build="GRCh38",
        access_method=access_method,
        license_text=None,
        checksum="a" * 64,
        location=None,
        status="ACTIVE",
        population_definition=None,
        metadata_json={},
    )
    db.add(resource)
    db.flush()
    qualification = ResourceQualification(
        id=uuid4(),
        resource_id=resource.id,
        qualification_version="qualification-v1",
        status="QUALIFIED",
        checks_json={
            "passed": True,
            "execution_contract": {
                "provider_id": provider,
                "provider_version": "api-public-v1" if provider == "GeneBe" else "graphql",
                "access_method": access_method,
                "endpoint": endpoint,
                "location": None,
                "dataset": dataset,
            },
        },
        qualified_by=None,
    )
    db.add(qualification)
    db.commit()
    return resource


def test_resolver_returns_exact_qualified_contract_and_stable_hash():
    engine, db = _db()
    try:
        resource = _resource(db, endpoint="https://qualified.example/api")
        resolved = resolve_resource_execution(db, resource=resource)
        assert resolved.contract.endpoint == "https://qualified.example/api"
        assert resolved.contract.provider_version == "api-public-v1"
        assert len(resolved.contract_hash) == 64
        assert resolved.snapshot["resource_id"] == str(resource.id)
    finally:
        db.close()
        engine.dispose()


def test_resolver_fails_closed_when_qualified_contract_disagrees_with_registry():
    engine, db = _db()
    try:
        resource = _resource(db)
        qualification = db.query(ResourceQualification).filter_by(resource_id=resource.id).one()
        qualification.checks_json["execution_contract"]["provider_id"] = "OTHER"
        flag_modified(qualification, "checks_json")
        db.commit()
        with pytest.raises(ResourceExecutionError, match="invalid"):
            resolve_resource_execution(db, resource=resource)
    finally:
        db.close()
        engine.dispose()


def test_genebe_adapter_uses_only_contract_endpoint():
    contract = ResourceExecutionContract(
        provider_id="GeneBe",
        provider_version="api-public-v1",
        access_method="API",
        endpoint="https://qualified.example/gene-be",
        location=None,
        dataset=None,
    )
    provider = GeneBeProvider.from_execution_contract(contract)
    assert provider.endpoint == "https://qualified.example/gene-be"
    with pytest.raises(Exception):
        GeneBeProvider.from_execution_contract(
            ResourceExecutionContract(
                provider_id="GeneBe",
                provider_version="wrong",
                access_method="API",
                endpoint="https://qualified.example/gene-be",
                location=None,
                dataset=None,
            )
        )


def test_gnomad_adapter_uses_only_contract_endpoint_and_dataset():
    contract = ResourceExecutionContract(
        provider_id="gnomAD",
        provider_version="graphql",
        access_method="API",
        endpoint="https://qualified.example/gnomad",
        location=None,
        dataset="gnomad_r4",
    )
    provider = GnomADGraphQLProvider.from_execution_contract(contract)
    assert provider.endpoint == "https://qualified.example/gnomad"
    assert provider.dataset_id == "gnomad_r4"


def test_resolver_fails_closed_when_local_execution_location_disagrees_with_registry():
    engine, db = _db()
    try:
        resource = Resource(
            id=uuid4(),
            organization_id=None,
            name="GRCh38 reference",
            provider="ReferenceProvider",
            resource_type="REFERENCE_PACKAGE",
            version="reference-v1",
            genome_build="GRCh38",
            access_method="LOCAL",
            license_text=None,
            checksum="b" * 64,
            location="/qualified/reference.fa",
            status="ACTIVE",
            population_definition=None,
            metadata_json={},
        )
        db.add(resource)
        db.flush()
        db.add(
            ResourceQualification(
                id=uuid4(),
                resource_id=resource.id,
                qualification_version="qualification-v1",
                status="QUALIFIED",
                checks_json={
                    "passed": True,
                    "execution_contract": {
                        "provider_id": "ReferenceProvider",
                        "provider_version": "reference-v1",
                        "access_method": "LOCAL",
                        "endpoint": None,
                        "location": "/other/reference.fa",
                        "dataset": None,
                    },
                },
                qualified_by=None,
            )
        )
        db.commit()

        with pytest.raises(ResourceExecutionError, match="location"):
            resolve_resource_execution(db, resource=resource)
    finally:
        db.close()
        engine.dispose()


def test_local_gnomad_adapter_requires_qualified_local_contract():
    from backend.app.adapters.population.gnomad import LocalGnomADTabixProvider, GnomADProviderError

    contract = ResourceExecutionContract(
        provider_id="gnomad-local-tabix",
        provider_version="vcf-tabix",
        access_method="LOCAL",
        endpoint=None,
        location="/qualified/gnomad.vcf.gz",
        dataset=None,
        execution_scope="ORGANIZATION_MANAGED",
    )
    provider = LocalGnomADTabixProvider.from_execution_contract(contract)
    assert provider.vcf_path == "/qualified/gnomad.vcf.gz"
    assert provider.execution_scope == "ORGANIZATION_MANAGED"

    with pytest.raises(GnomADProviderError, match="LOCAL"):
        LocalGnomADTabixProvider.from_execution_contract(
            ResourceExecutionContract(
                provider_id="gnomad-local-tabix",
                provider_version="vcf-tabix",
                access_method="API",
                endpoint="https://example.org/gnomad",
                location=None,
                dataset=None,
                execution_scope="ORGANIZATION_MANAGED",
            )
        )


def test_replayed_annotation_observation_cannot_duplicate_or_change_resource_identity():
    """A retry after provider success must not create a second observation for the same governed release."""
    engine, db = _db()
    try:
        resource = _resource(db)
        analysis_id = uuid4()
        variant_id = uuid4()
        identity = {
            "analysis_id": analysis_id,
            "variant_id": variant_id,
            "provider_name": "GeneBe",
            "provider_version": "api-public-v1",
            "resource_id": resource.id,
            "resource_name": resource.name,
            "resource_version": resource.version,
            "request_fingerprint": "request-fingerprint-v1",
            "response_sha256": "a" * 64,
            "request_metadata": {"provider": "GeneBe", "provider_version": "api-public-v1"},
            "payload": {"raw": {"impact": "MODERATE"}, "normalized": {"impact": "MODERATE"}},
        }
        db.add(Annotation(id=uuid4(), **identity))
        db.commit()

        # Simulate the replay trying to persist the same canonical observation
        # after the first provider call succeeded. The database uniqueness
        # contract is the final guard against duplicate rows under retry/races.
        db.add(Annotation(id=uuid4(), **identity))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        rows = db.scalars(
            select(Annotation).where(
                Annotation.analysis_id == analysis_id,
                Annotation.variant_id == variant_id,
                Annotation.resource_id == resource.id,
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].resource_id == resource.id
        assert rows[0].resource_version == resource.version
        assert rows[0].request_fingerprint == "request-fingerprint-v1"
        assert rows[0].response_sha256 == "a" * 64
    finally:
        db.close()
        engine.dispose()


def test_annotation_response_checkpoint_replays_exact_payload_after_worker_loss(tmp_path):
    """A crash after response checkpointing but before row persistence must not call the provider again."""
    from backend.app.infrastructure.artifacts.store import ArtifactStore
    from backend.app.infrastructure.db.models import Artifact, Case, Organization, User, WorkflowStep
    from backend.app.workflows.variant import (
        _load_annotation_response_checkpoint,
        _persist_annotation_response_checkpoint,
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, User.__table__, Case.__table__, Analysis.__table__,
            Resource.__table__, ResourceQualification.__table__, Artifact.__table__,
            WorkflowStep.__table__,
        ],
    )
    store = ArtifactStore(tmp_path / "artifact-store")
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Replay Safety Lab", external_identifier=None))
        db.add(User(
            id=user_id, organization_id=organization_id, external_subject=None,
            email="replay@test.local", display_name="Replay test", role="ADMIN", status="ACTIVE",
        ))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="REPLAY-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        ))
        analysis = Analysis(
            id=analysis_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="RUNNING", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=None, created_by=user_id, analysis_version=1,
        )
        db.add(analysis)
        resource = _resource(db)
        step = WorkflowStep(
            id=uuid4(), analysis_id=analysis_id, step_id="annotate", step_order=3,
            status="RUNNING", attempt=1, input_artifacts=[], output_artifacts=[],
            metadata_json={"batches": {"0:1": {"status": "RUNNING", "attempt": 1}}},
        )
        db.add(step)
        db.commit()

        provider_calls = {"count": 0}

        def fake_provider_response():
            provider_calls["count"] += 1
            return [{
                "chr": "1", "pos": 555, "ref": "T", "alt": "C",
                "impact": "MODERATE",
                "_siraloom_annotation_provenance": {
                    "provider": "GeneBe",
                    "provider_version": "api-public-v1",
                    "request_fingerprint": "request-fingerprint-1",
                    "response_sha256": "a" * 64,
                    "observed_at": "2026-10-10T00:00:00+00:00",
                    "retry_count": 0,
                },
            }]

        first_payload = fake_provider_response()
        _persist_annotation_response_checkpoint(
            db, store, analysis=analysis, step=step, start=0, end=1,
            payloads=first_payload, resource=resource,
            provider_id="GeneBe", provider_version="api-public-v1",
        )

        # Simulate worker death here: response artifact + checkpoint are committed,
        # but no Annotation rows have been written yet.
        db.expire(step)
        temporary_paths = []
        replayed_payload = _load_annotation_response_checkpoint(
            db, step=step, start=0, end=1, analysis=analysis, resource=resource,
            provider_id="GeneBe", provider_version="api-public-v1",
            temporary_paths=temporary_paths,
        )
        if replayed_payload is None:
            replayed_payload = fake_provider_response()

        assert provider_calls["count"] == 1
        assert replayed_payload == first_payload
        checkpoint = step.metadata_json["batches"]["0:1"]
        assert checkpoint["status"] == "RESPONSE_PERSISTED"
        assert checkpoint["resource_id"] == str(resource.id)
        assert checkpoint["resource_version"] == resource.version
        assert checkpoint["request_fingerprint"] == "request-fingerprint-1"
        assert checkpoint["response_sha256"] == "a" * 64
        assert checkpoint["response_artifact_id"]
        assert db.query(Artifact).filter_by(artifact_type="ANNOTATION_PROVIDER_RESPONSE").count() == 1
    engine.dispose()


def test_annotation_response_checkpoint_fails_closed_on_resource_release_drift(tmp_path):
    from backend.app.infrastructure.artifacts.store import ArtifactStore
    from backend.app.infrastructure.db.models import Artifact, Case, Organization, User, WorkflowStep
    from backend.app.workflows.variant import (
        _load_annotation_response_checkpoint,
        _persist_annotation_response_checkpoint,
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, User.__table__, Case.__table__, Analysis.__table__,
            Resource.__table__, ResourceQualification.__table__, Artifact.__table__,
            WorkflowStep.__table__,
        ],
    )
    store = ArtifactStore(tmp_path / "artifact-store")
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Identity Lab", external_identifier=None))
        db.add(User(
            id=user_id, organization_id=organization_id, external_subject=None,
            email="identity@test.local", display_name="Identity test", role="ADMIN", status="ACTIVE",
        ))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="IDENTITY-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        ))
        analysis = Analysis(
            id=analysis_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="RUNNING", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=None, created_by=user_id, analysis_version=1,
        )
        db.add(analysis)
        resource = _resource(db)
        other_resource = _resource(db)
        step = WorkflowStep(
            id=uuid4(), analysis_id=analysis_id, step_id="annotate", step_order=3,
            status="RUNNING", attempt=1, input_artifacts=[], output_artifacts=[],
            metadata_json={"batches": {"0:1": {"status": "RUNNING", "attempt": 1}}},
        )
        db.add(step)
        db.commit()
        payload = [{
            "chr": "1", "pos": 555, "ref": "T", "alt": "C",
            "_siraloom_annotation_provenance": {
                "provider": "GeneBe", "provider_version": "api-public-v1",
                "request_fingerprint": "request-fingerprint-1", "response_sha256": "a" * 64,
            },
        }]
        _persist_annotation_response_checkpoint(
            db, store, analysis=analysis, step=step, start=0, end=1,
            payloads=payload, resource=resource,
            provider_id="GeneBe", provider_version="api-public-v1",
        )
        with pytest.raises(RuntimeError, match="identity"):
            _load_annotation_response_checkpoint(
                db, step=step, start=0, end=1, analysis=analysis, resource=other_resource,
                provider_id="GeneBe", provider_version="api-public-v1",
                temporary_paths=[],
            )
    engine.dispose()


def test_local_annotation_provider_gets_stable_request_fingerprint():
    from types import SimpleNamespace
    from backend.app.workflows.variant import _ensure_annotation_request_fingerprint

    analysis = SimpleNamespace(
        id=uuid4(),
        reference_build="GRCh38",
    )
    resource = SimpleNamespace(
        id=uuid4(),
        version="release-1",
        checksum="f" * 64,
    )
    payloads = [{
        "chr": "1", "pos": 555, "ref": "T", "alt": "C",
        "_siraloom_annotation_provenance": {
            "provider": "VEP",
            "provider_version": "vep-115",
            "response_sha256": "a" * 64,
        },
    }]
    first = _ensure_annotation_request_fingerprint(
        payloads, analysis=analysis, start=0, end=1, resource=resource,
        provider_id="VEP", provider_version="vep-115",
    )
    second_payloads = [{
        **payloads[0],
        "_siraloom_annotation_provenance": {
            "provider": "VEP", "provider_version": "vep-115",
            "response_sha256": "a" * 64,
        },
    }]
    second = _ensure_annotation_request_fingerprint(
        second_payloads, analysis=analysis, start=0, end=1, resource=resource,
        provider_id="VEP", provider_version="vep-115",
    )
    assert first == second
    assert len(first) == 64
    assert payloads[0]["_siraloom_annotation_provenance"]["request_fingerprint"] == first


def test_annotation_stage_continuation_recovers_rows_partition_and_evidence_lineage(tmp_path):
    """Recover after row commit but before batch completion without duplicate annotations."""
    from types import SimpleNamespace

    from sqlalchemy import func

    from backend.app.domain.enums import AnalysisStatus, StepStatus
    from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid
    from backend.app.evidence.engine import EvidenceContext, EvidenceEngine
    from backend.app.infrastructure.artifacts.store import ArtifactStore
    from backend.app.infrastructure.db.models import (
        AnalysisPartition, Artifact, Case, Evidence, Organization, User, Variant, WorkflowStep,
    )
    from backend.app.partition_scheduler import PartitionScheduler, configure_partition
    from backend.app.workflows.variant import (
        _load_annotation_response_checkpoint,
        _persist_annotation_batch_rows,
        _persist_annotation_response_checkpoint,
        _save_batch_checkpoint,
        recover_interrupted_execution,
    )

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'annotation-stage-recovery.db'}")
    Base.metadata.create_all(engine)
    store = ArtifactStore(tmp_path / "artifact-store")
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    parent_id, analysis_id = uuid4(), uuid4()
    variant_key = canonical_key("GRCh38", "1", 555, "T", "C")
    variant_id = stable_variant_uuid(variant_key)
    try:
        with Session(engine) as db:
            db.add(Organization(id=organization_id, name="Continuation Lab", external_identifier=None))
            db.add(User(
                id=user_id, organization_id=organization_id, external_subject=None,
                email="continuation@test.local", display_name="Continuation test",
                role="ADMIN", status="ACTIVE",
            ))
            db.add(Case(
                id=case_id, organization_id=organization_id, case_identifier="CONT-001",
                status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
            ))
            db.add(Analysis(
                id=parent_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
                analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
                workflow_version="2.1", status=AnalysisStatus.SUCCEEDED, queue_task_id=None,
                reference_build="GRCh38", configuration={}, started_at=None,
                completed_at=None, created_by=user_id, analysis_version=1,
            ))
            child = Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=parent_id, assay_id=None,
                analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
                workflow_version="2.1", status=AnalysisStatus.RUNNING, queue_task_id=None,
                reference_build="GRCh38", configuration={}, started_at=None,
                completed_at=None, created_by=user_id, analysis_version=2,
            )
            db.add(child)
            db.add(Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1", position=555,
                reference="T", alternate="C", normalization_status="NORMALIZED",
                canonical_key=variant_key, identifiers={"canonical_key_sha256": "fixture"},
            ))
            resource = _resource(db)
            step = WorkflowStep(
                id=uuid4(), analysis_id=analysis_id, step_id="annotate", step_order=3,
                status=StepStatus.RUNNING, attempt=1, input_artifacts=[], output_artifacts=[],
                metadata_json={"batches": {"0:1": {"status": "RUNNING", "attempt": 1}}},
            )
            partition = AnalysisPartition(
                id=uuid4(), analysis_id=analysis_id, step_id="annotate",
                partition_key="0:1", ordinal=0, record_start=0, record_end=1,
                variant_count=1, status="READY", metadata_json={"variant_ids": [str(variant_id)]},
            )
            configure_partition(partition, "STANDARD")
            db.add_all([step, partition])
            db.commit()

            scheduler = PartitionScheduler(db, cpu_capacity=1, memory_mb=1024, lease_seconds=60)
            claimed = scheduler.claim_next(analysis_id, "annotate", "worker-before-crash")
            assert claimed is not None
            lease_token = claimed.lease_token
            provider = SimpleNamespace(provider_id="GeneBe", provider_version="api-public-v1")
            payload = {
                "chr": "1", "pos": 555, "ref": "T", "alt": "C",
                "gene_symbol": "TEST1", "effect": "missense_variant",
                "frequency_reference_population": 0.00001,
                "computational_score_selected": 0.91,
                "_siraloom_annotation_provenance": {
                    "provider": "GeneBe", "provider_version": "api-public-v1",
                    "request_fingerprint": "d" * 64, "response_sha256": "e" * 64,
                    "observed_at": "2026-10-10T00:00:00+00:00", "retry_count": 0,
                },
            }
            _persist_annotation_response_checkpoint(
                db, store, analysis=child, step=step, start=0, end=1,
                payloads=[dict(payload)], resource=resource,
                provider_id=provider.provider_id, provider_version=provider.provider_version,
            )
            # First durable side effect after the checkpoint: rows commit, then
            # simulate abrupt worker death before the batch checkpoint/partition succeed.
            new_count, returned_rows = _persist_annotation_batch_rows(
                db, analysis=child, provider=provider, annotation_resource=resource,
                variant_ids={variant_key: variant_id}, existing_rows=[],
                payloads=[dict(payload)], batch_key="0:1",
            )
            assert (new_count, returned_rows) == (1, 1)
            assert db.scalar(select(func.count(Annotation.id)).where(Annotation.analysis_id == analysis_id)) == 1
            db.close()

        # New session represents Celery redelivery after worker loss.
        with Session(engine) as db:
            assert recover_interrupted_execution(db, analysis_id) is True
            child = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id, WorkflowStep.step_id == "annotate"
            ))
            resource = db.get(Resource, resource.id)
            assert child.parent_analysis_id == parent_id
            assert step.status == StepStatus.RETRYING

            replay_payloads = _load_annotation_response_checkpoint(
                db, step=step, start=0, end=1, analysis=child, resource=resource,
                provider_id="GeneBe", provider_version="api-public-v1", temporary_paths=[],
            )
            assert replay_payloads[0]["_siraloom_annotation_provenance"]["request_fingerprint"] == "d" * 64
            existing_rows = db.scalars(select(Annotation).where(
                Annotation.analysis_id == analysis_id,
                Annotation.provider_name == "GeneBe",
                Annotation.resource_id == resource.id,
                Annotation.resource_version == resource.version,
                Annotation.variant_id == variant_id,
            )).all()
            new_count, returned_rows = _persist_annotation_batch_rows(
                db, analysis=child, provider=SimpleNamespace(
                    provider_id="GeneBe", provider_version="api-public-v1"
                ), annotation_resource=resource,
                variant_ids={variant_key: variant_id}, existing_rows=existing_rows,
                payloads=replay_payloads, batch_key="0:1",
            )
            assert (new_count, returned_rows) == (0, 1)
            assert db.scalar(select(func.count(Annotation.id)).where(
                Annotation.analysis_id == analysis_id
            )) == 1

            retry_claim = PartitionScheduler(
                db, cpu_capacity=1, memory_mb=1024, lease_seconds=60
            ).claim_next(analysis_id, "annotate", "worker-after-redelivery")
            assert retry_claim is not None
            _save_batch_checkpoint(
                db, step, 0, 1, status="SUCCEEDED", attempt=2,
                metadata={
                    "provider": "GeneBe", "new_annotation_rows": 0, "returned_rows": 1,
                    "resource_id": str(resource.id), "resource_version": resource.version,
                }, commit=False,
            )
            PartitionScheduler(db, cpu_capacity=1, memory_mb=1024, lease_seconds=60).succeed(
                retry_claim.id, "worker-after-redelivery", retry_claim.lease_token,
                metadata={"provider": "GeneBe", "variant_count": 1},
            )
            db.commit()
            db.refresh(partition)
            assert db.get(AnalysisPartition, retry_claim.id).status == "SUCCEEDED"
            assert step.metadata_json["batches"]["0:1"]["status"] == "SUCCEEDED"

            annotation = db.scalars(select(Annotation).where(
                Annotation.analysis_id == analysis_id
            )).one()
            assert annotation.resource_id == resource.id
            assert annotation.resource_version == resource.version
            assert annotation.request_fingerprint == "d" * 64
            assert annotation.response_sha256 == "e" * 64

            # Exercise the real evidence extraction engine on the persisted
            # normalized observation; this creates evidence facts, not a final classification.
            records = EvidenceEngine().build_from_annotation(
                variant_id=annotation.variant_id,
                annotation=annotation.payload["normalized"],
                provider_name=annotation.provider_name,
                provider_version=annotation.provider_version,
                resource_name=annotation.resource_name,
                resource_version=annotation.resource_version,
                context=EvidenceContext(analysis_id=analysis_id),
            )
            assert records
            assert all(record.variant_id == annotation.variant_id for record in records)
            assert any(
                record.source_name == annotation.resource_name
                and record.source_version == annotation.resource_version
                for record in records
            )
            assert db.get(Analysis, analysis_id).parent_analysis_id == parent_id
    finally:
        engine.dispose()
