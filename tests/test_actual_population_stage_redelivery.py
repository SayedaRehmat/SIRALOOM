"""Prove population provider calls are not repeated after durable observation commit."""
from datetime import datetime, timezone
import gzip
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.adapters.population.gnomad import PopulationObservationData
from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Annotation,
    Case,
    Evidence,
    Organization,
    PopulationObservation,
    Resource,
    ResourceExecutionRecord,
    User,
    Variant,
    WorkflowStep,
)


def test_population_stage_reentry_skips_provider_after_durable_success(monkeypatch, tmp_path):
    import importlib

    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'population-redelivery.db'}")
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False)
    store = ArtifactStore(tmp_path / "artifacts")
    organization_id, user_id, case_id, analysis_id, resource_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    clinvar_resource_id = uuid4()
    variant_key = canonical_key("GRCh38", "1", 555, "T", "C")
    variant_id = stable_variant_uuid(variant_key)
    provider_calls = {"count": 0}
    clinvar_calls = {"count": 0}

    try:
        source = tmp_path / "source.vcf"
        source.write_text(
            "##fileformat=VCFv4.2\n"
            "##contig=<ID=1,length=1000000>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "1\t555\t.\tT\tC\t.\tPASS\t.\n",
            encoding="utf-8",
        )
        normalized = tmp_path / "normalized.vcf.gz"
        normalized.write_bytes(gzip.compress(source.read_bytes()))

        with LocalSession() as db:
            db.add(Organization(
                id=organization_id,
                name="Population Replay Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Population Replay Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"POP-REPLAY-{case_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            source_artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=source,
                filename="source.vcf",
                artifact_type="SOURCE_VCF",
                media_type="text/plain",
                genome_build="GRCh38",
                metadata={},
            )
            normalized_artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=normalized,
                filename="normalized.vcf.gz",
                artifact_type="NORMALIZED_VCF",
                media_type="application/gzip",
                genome_build="GRCh38",
                metadata={},
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
                status=AnalysisStatus.RUNNING,
                queue_task_id="population-replay-test",
                reference_build="GRCh38",
                configuration={
                    "input_artifact_id": str(source_artifact.id),
                    "clinvar_resource_id": str(clinvar_resource_id),
                },
                started_at=datetime.now(timezone.utc),
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.flush()
            db.add(Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=555,
                reference="T",
                alternate="C",
                normalization_status="NORMALIZED",
                canonical_key=variant_key,
                identifiers={},
            ))
            resource = Resource(
                id=resource_id,
                organization_id=organization_id,
                name="Fixture population resource",
                provider="fixture-population",
                resource_type="POPULATION",
                version="release-v1",
                genome_build="GRCh38",
                access_method="API",
                license_text=None,
                checksum="a" * 64,
                location="https://fixture.invalid/population",
                status="ACTIVE",
                population_definition=None,
                metadata_json={},
            )
            db.add(resource)
            db.add(Resource(
                id=clinvar_resource_id,
                organization_id=organization_id,
                name="Fixture ClinVar resource",
                provider="NCBI ClinVar",
                resource_type="EVIDENCE",
                version="clinvar-v1",
                genome_build="GRCh38",
                access_method="API",
                license_text=None,
                checksum="f" * 64,
                location="https://fixture.invalid/clinvar",
                status="ACTIVE",
                population_definition=None,
                metadata_json={},
            ))
            db.add(Annotation(
                id=uuid4(),
                variant_id=variant_id,
                analysis_id=analysis_id,
                provider_name="fixture-annotation",
                provider_version="v1",
                resource_id=None,
                resource_name="fixture-annotation",
                resource_version="v1",
                request_fingerprint="request",
                response_sha256="b" * 64,
                request_metadata={},
                payload={"normalized": {}},
            ))
            for order, step_id in enumerate((
                "validate_input", "normalize", "annotate", "population",
                "build_evidence", "acmg_assessment", "review", "reportability",
                "report", "export_provenance",
            ), start=1):
                status = (
                    StepStatus.PENDING
                    if step_id in {"population", "build_evidence", "acmg_assessment"}
                    else StepStatus.SUCCEEDED
                )
                outputs = (
                    [str(source_artifact.id)] if step_id == "validate_input"
                    else [str(normalized_artifact.id)] if step_id == "normalize"
                    else []
                )
                db.add(WorkflowStep(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    step_id=step_id,
                    step_order=order,
                    status=status,
                    attempt=0,
                    input_artifacts=[],
                    output_artifacts=outputs,
                    metadata_json={"seeded_checkpoint": True} if status == StepStatus.SUCCEEDED else {},
                ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(
            workflow,
            "artifact_store_for_organization",
            lambda *_args, **_kwargs: store,
        )

        contract = SimpleNamespace(
            provider_id="fixture-population",
            provider_version="v1",
            access_method="API",
            endpoint="https://fixture.invalid/population",
            location="https://fixture.invalid/population",
            dataset="fixture-v1",
            as_dict=lambda: {
                "provider_id": "fixture-population",
                "provider_version": "v1",
                "access_method": "API",
                "endpoint": "https://fixture.invalid/population",
                "location": "https://fixture.invalid/population",
                "dataset": "fixture-v1",
            },
        )
        execution = SimpleNamespace(
            resource_id=resource_id,
            resource_version="release-v1",
            qualification_id=uuid4(),
            qualification_version="qualification-v1",
            contract=contract,
            contract_hash="c" * 64,
        )
        clinvar_contract = SimpleNamespace(
            provider_id="NCBI ClinVar",
            provider_version="v1",
            access_method="API",
            endpoint="https://fixture.invalid/clinvar",
            location="https://fixture.invalid/clinvar",
            dataset="clinvar-v1",
            as_dict=lambda: {
                "provider_id": "NCBI ClinVar",
                "provider_version": "v1",
                "access_method": "API",
                "endpoint": "https://fixture.invalid/clinvar",
                "location": "https://fixture.invalid/clinvar",
                "dataset": "clinvar-v1",
            },
        )
        clinvar_execution = SimpleNamespace(
            resource_id=clinvar_resource_id,
            resource_version="clinvar-v1",
            qualification_id=uuid4(),
            qualification_version="qualification-v1",
            contract=clinvar_contract,
            contract_hash="d" * 64,
            snapshot={"resource_id": str(clinvar_resource_id), "resource_version": "clinvar-v1"},
        )

        class FakeProvider:
            provider_id = "fixture-population"

            def query_variant(self, _variant):
                provider_calls["count"] += 1
                return [PopulationObservationData(
                    population_level="GLOBAL",
                    population_code="GLOBAL",
                    population_label="Global",
                    allele_count=1,
                    allele_number=100,
                    allele_frequency=0.01,
                    homozygote_count=0,
                    request_fingerprint="d" * 64,
                    response_sha256="e" * 64,
                    request_metadata={"fixture": True},
                )]

        class FakeClinVarProvider:
            def query_variant(self, **_kwargs):
                clinvar_calls["count"] += 1
                return []

        provider = FakeProvider()
        candidate = SimpleNamespace(resource=resource, execution=execution)
        monkeypatch.setattr(
            workflow,
            "build_resource_execution_plan",
            lambda *_args, **_kwargs: SimpleNamespace(
                profile_type="TRIAL_PUBLIC",
                profile_version="test",
                unavailable_optional=[],
                for_capability=lambda _capability: [candidate],
            ),
        )
        monkeypatch.setattr(
            workflow,
            "resolve_resource_execution",
            lambda _db, *, resource: (
                clinvar_execution if resource.id == clinvar_resource_id else execution
            ),
        )
        monkeypatch.setattr(
            workflow.ClinVarVCVProvider,
            "from_execution_contract",
            lambda **_kwargs: FakeClinVarProvider(),
        )
        monkeypatch.setattr(
            workflow,
            "register_builtin_providers",
            lambda: SimpleNamespace(
                resolve=lambda **_kwargs: SimpleNamespace(factory=lambda _contract: provider)
            ),
        )

        real_mark_step = workflow.mark_step
        worker_loss = {"injected": False}

        def crash_after_provider_commit(db, step, status, **kwargs):
            if (
                step.step_id == "population"
                and status == StepStatus.SUCCEEDED
                and not worker_loss["injected"]
            ):
                worker_loss["injected"] = True
                raise SystemExit(73)
            return real_mark_step(db, step, status, **kwargs)

        monkeypatch.setattr(workflow, "mark_step", crash_after_provider_commit)
        with pytest.raises(SystemExit, match="73"):
            workflow.run_variant_analysis(analysis_id)

        with LocalSession() as db:
            executions = db.scalars(select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.step_id == "population",
            )).all()
            observations = db.scalars(select(PopulationObservation).where(
                PopulationObservation.analysis_id == analysis_id,
            )).all()
            assert len(executions) == 1
            assert executions[0].status == "SUCCEEDED"
            assert len(observations) == 1
            assert provider_calls["count"] == 1

        # Simulate worker loss after evidence and resource-execution rows commit,
        # but before the evidence batch checkpoint is marked complete.
        real_save_batch_checkpoint = workflow._save_batch_checkpoint
        evidence_worker_loss = {"injected": False}

        def crash_before_evidence_checkpoint(db, step, start, end, **kwargs):
            if (
                step.step_id == "build_evidence"
                and kwargs.get("status") == "SUCCEEDED"
                and not evidence_worker_loss["injected"]
            ):
                evidence_worker_loss["injected"] = True
                raise SystemExit(75)
            return real_save_batch_checkpoint(db, step, start, end, **kwargs)

        monkeypatch.setattr(workflow, "_save_batch_checkpoint", crash_before_evidence_checkpoint)
        real_step = workflow._step

        def stop_after_population(db, received_analysis_id, step_id):
            if step_id == "acmg_assessment":
                raise SystemExit(74)
            return real_step(db, received_analysis_id, step_id)

        monkeypatch.setattr(workflow, "_step", stop_after_population)
        try:
            workflow.run_variant_analysis(analysis_id)
        except SystemExit as exc:
            assert str(exc.code) == "75"
        else:
            with LocalSession() as db:
                current = db.get(Analysis, analysis_id)
                evidence_step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == "build_evidence",
                ))
            pytest.fail(
                "Evidence checkpoint hook was not reached; "
                f"analysis={current.status if current else None}, "
                f"step={evidence_step.status if evidence_step else None}, "
                f"error={evidence_step.error_code if evidence_step else None}, "
                f"message={evidence_step.error_message if evidence_step else None}, "
                f"clinvar_calls={clinvar_calls['count']}"
            )

        # Evidence stage must have run and committed its records before the
        # checkpoint hook is reached. The checkpoint remains RUNNING.
        with LocalSession() as db:
            evidence_rows = db.scalars(select(Evidence).where(
                Evidence.analysis_id == analysis_id,
            )).all()
            evidence_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "build_evidence",
            ))
            assert evidence_rows
            assert evidence_step.metadata_json["batches"]["0:1"]["status"] == "RUNNING"
            assert clinvar_calls["count"] == 1
        assert evidence_worker_loss["injected"]

        # On redelivery, the pending checkpoint causes evidence reconstruction;
        # row fingerprints prevent duplicates and persisted resource executions
        # are reused for any external evidence query.
        monkeypatch.setattr(workflow, "_step", lambda db, received_analysis_id, step_id: (
            (_ for _ in ()).throw(SystemExit(76))
            if step_id == "acmg_assessment"
            else real_step(db, received_analysis_id, step_id)
        ))
        with pytest.raises(SystemExit, match="76"):
            workflow.run_variant_analysis(analysis_id)

        with LocalSession() as db:
            population_step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "population",
            ))
            assert population_step.status == StepStatus.SUCCEEDED
            assert db.scalar(select(func.count(ResourceExecutionRecord.id)).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.step_id == "population",
            )) == 1
            assert db.scalar(select(func.count(PopulationObservation.id)).where(
                PopulationObservation.analysis_id == analysis_id,
            )) == 1
            clinvar_execution_rows = db.scalars(select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.step_id == "build_evidence",
                ResourceExecutionRecord.resource_id == clinvar_resource_id,
            )).all()
            assert len(clinvar_execution_rows) == 1
            assert clinvar_execution_rows[0].status == "NO_DATA"
            assert provider_calls["count"] == 1
            assert clinvar_calls["count"] == 1
    finally:
        engine.dispose()
