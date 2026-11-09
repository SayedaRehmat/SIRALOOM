"""Exercise governed G2P/ClinGen evidence assembly and crash replay in the real workflow."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.adapters.clingen.gene_disease_validity import ClinGenGeneDiseaseValidityProvider
from backend.app.adapters.gene_disease.g2p import G2PProvider
from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.resource_execution import ResolvedResourceExecution
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis, AnalysisPartition, Annotation, Artifact, AuditEvent, Case,
    Evidence, Organization, Resource, ResourceExecutionRecord,
    ResourceQualification, User, Variant, WorkflowStep,
)
from backend.app.partition_scheduler import configure_partition


@pytest.mark.integration
def test_actual_gene_disease_evidence_workflow_replays_after_worker_loss(
    monkeypatch, tmp_path
):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL workflow integration test requires DATABASE_URL")

    import importlib
    queue = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    workflow = importlib.import_module("backend.app.workflows.variant")

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    LocalSession = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    store = ArtifactStore(tmp_path / "gene-disease-artifacts")

    organization_id, user_id, case_id, analysis_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    variant_specs = [
        ("GENE1", "1", 101, "A", "G"),
        ("GENE2", "1", 202, "C", "T"),
    ]
    variant_ids = [
        stable_variant_uuid(canonical_key("GRCh38", chrom, pos, ref, alt))
        for _gene, chrom, pos, ref, alt in variant_specs
    ]
    g2p_path = tmp_path / "g2p.csv"
    g2p_path.write_text(
        "G2P ID,Gene symbol,Disease name,Disease MONDO,Allelic requirement,"
        "Molecular mechanism,Confidence,Publication,Publication phenotypes,"
        "Cross cutting modifier,Publication variant types,"
        "Evidence based variant consequence,Publication molecular mechanism evidence\n"
        "G2P001,GENE1,Example one,MONDO:0000001,biallelic_autosomal,"
        "loss of function,definitive,PMID:1,HP:0001250,,,,\n"
        "G2P002,GENE2,Example two,,biallelic_autosomal,"
        "loss of function,definitive,PMID:2,HP:0001263,,,,\n",
        encoding="utf-8",
    )
    clingen_path = tmp_path / "clingen.csv"
    clingen_path.write_text(
        "CLINGEN GENE VALIDITY CURATIONS\n"
        "FILE CREATED: 2026-11-08\n"
        "GENE SYMBOL,GENE ID (HGNC),DISEASE LABEL,DISEASE ID (MONDO),SOP,"
        "CLASSIFICATION,ONLINE REPORT,CLASSIFICATION DATE,GCEP,MOI\n"
        "GENE1,HGNC:1,Example one,MONDO_0000001,SOP9,Definitive,"
        "https://search.clinicalgenome.org/kb/gene-validity/example1,"
        "2026-11-08,Expert Panel,Autosomal recessive inheritance\n"
        "GENE2,HGNC:2,Example two,MONDO_0000002,SOP9,Strong,"
        "https://search.clinicalgenome.org/kb/gene-validity/example2,"
        "2026-11-08,Expert Panel,Autosomal recessive inheritance\n",
        encoding="utf-8",
    )
    g2p_sha = hashlib.sha256(g2p_path.read_bytes()).hexdigest()
    clingen_sha = hashlib.sha256(clingen_path.read_bytes()).hexdigest()
    g2p_resource_id, clingen_resource_id = uuid4(), uuid4()
    g2p_qualification_id, clingen_qualification_id = uuid4(), uuid4()
    release = "2026-11-08"

    g2p_contract = ResourceExecutionContract(
        provider_id=G2PProvider.provider_id,
        provider_version=G2PProvider.provider_version,
        access_method="LOCAL", endpoint=None, location=str(g2p_path),
        dataset=release, toolchain={"release": release, "sha256": g2p_sha},
    )
    clingen_contract = ResourceExecutionContract(
        provider_id=ClinGenGeneDiseaseValidityProvider.provider_id,
        provider_version=ClinGenGeneDiseaseValidityProvider.provider_version,
        access_method="LOCAL", endpoint=None, location=str(clingen_path),
        dataset="ClinGen-GDV",
        toolchain={"release": release, "sha256": clingen_sha},
    )
    g2p_execution = ResolvedResourceExecution(
        resource_id=g2p_resource_id, resource_version=release,
        qualification_id=g2p_qualification_id,
        qualification_version="integration-qualified-v1",
        contract=g2p_contract, contract_hash="a" * 64,
    )
    clingen_execution = ResolvedResourceExecution(
        resource_id=clingen_resource_id, resource_version=release,
        qualification_id=clingen_qualification_id,
        qualification_version="integration-qualified-v1",
        contract=clingen_contract, contract_hash="b" * 64,
    )

    crashed = {"value": False}
    stop_after_evidence = {"value": False}
    real_save_checkpoint = workflow._save_batch_checkpoint
    real_step = workflow._step

    try:
        source_vcf = tmp_path / "source.vcf"
        normalized_vcf = tmp_path / "normalized.vcf"
        vcf_text = (
            "##fileformat=VCFv4.2\n##contig=<ID=1,length=1000000>\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "1\t101\t.\tA\tG\t.\tPASS\t.\n"
            "1\t202\t.\tC\tT\t.\tPASS\t.\n"
        )
        source_vcf.write_text(vcf_text, encoding="utf-8")
        normalized_vcf.write_text(vcf_text, encoding="utf-8")

        with LocalSession() as db:
            db.add(Organization(
                id=organization_id, name="C1 Gene-Disease Workflow Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="C1 Workflow Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"C1-GD-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            source_artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=source_vcf, filename="source.vcf",
                artifact_type="SOURCE_VCF", media_type="text/plain",
                genome_build="GRCh38", metadata={},
            )
            normalized_artifact = store.put_file(
                db=db, case_id=case_id, analysis_id=analysis_id,
                source_path=normalized_vcf, filename="normalized.vcf",
                artifact_type="NORMALIZED_VCF", media_type="text/plain",
                genome_build="GRCh38", metadata={},
            )
            db.flush()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="integration",
                status=AnalysisStatus.QUEUED, queue_task_id="c1-gene-disease-replay",
                reference_build="GRCh38",
                configuration={
                    "input_artifact_id": str(source_artifact.id),
                    "evidence_batch_size": 250,
                },
                started_at=None, completed_at=None, created_by=user_id,
                analysis_version=1,
            ))
            db.flush()
            db.add_all([
                Variant(
                    id=variant_id, genome_build="GRCh38", chromosome=chrom,
                    position=position, reference=ref, alternate=alt,
                    normalization_status="NORMALIZED",
                    canonical_key=canonical_key("GRCh38", chrom, position, ref, alt),
                    identifiers={},
                )
                for variant_id, (_gene, chrom, position, ref, alt)
                in zip(variant_ids, variant_specs)
            ])
            resources = [
                Resource(
                    id=g2p_resource_id, organization_id=organization_id,
                    name="Pinned G2P integration export",
                    provider=G2PProvider.provider_id, resource_type="GENE_DISEASE",
                    version=release, genome_build=None, access_method="LOCAL",
                    license_text="Integration fixture", checksum=g2p_sha,
                    location=str(g2p_path), status="ACTIVE",
                    population_definition=None, metadata_json={},
                ),
                Resource(
                    id=clingen_resource_id, organization_id=organization_id,
                    name="Pinned ClinGen GDV integration export",
                    provider=ClinGenGeneDiseaseValidityProvider.provider_id,
                    resource_type="GENE_DISEASE", version=release,
                    genome_build=None, access_method="LOCAL",
                    license_text="Integration fixture", checksum=clingen_sha,
                    location=str(clingen_path), status="ACTIVE",
                    population_definition=None, metadata_json={},
                ),
            ]
            db.add_all(resources)
            db.flush()
            db.add_all([
                ResourceQualification(
                    id=g2p_qualification_id, resource_id=g2p_resource_id,
                    qualification_version="integration-qualified-v1",
                    status="QUALIFIED", checks_json={"execution_contract": g2p_contract.as_dict()},
                    qualified_by=user_id, qualified_at=datetime.now(timezone.utc),
                ),
                ResourceQualification(
                    id=clingen_qualification_id, resource_id=clingen_resource_id,
                    qualification_version="integration-qualified-v1",
                    status="QUALIFIED", checks_json={"execution_contract": clingen_contract.as_dict()},
                    qualified_by=user_id, qualified_at=datetime.now(timezone.utc),
                ),
            ])
            db.add_all([
                Annotation(
                    id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                    provider_name="VEP", provider_version="115",
                    resource_id=None, resource_name="Pinned VEP fixture",
                    resource_version="115", request_fingerprint="c" * 64,
                    response_sha256="d" * 64, request_metadata={},
                    retry_count=0,
                    payload={"normalized": {
                        "gene": {"symbol": gene},
                        "consequence": "missense_variant",
                        "hgvs": {"c": f"c.{position}A>G"},
                    }},
                )
                for variant_id, (gene, _chrom, position, _ref, _alt)
                in zip(variant_ids, variant_specs)
            ])
            steps = [
                ("validate_input", 1, StepStatus.SUCCEEDED, {"validation_profile": {}}, [str(source_artifact.id)]),
                ("normalize", 2, StepStatus.SUCCEEDED, {"partition_count": 1}, [str(normalized_artifact.id)]),
                ("annotate", 3, StepStatus.SUCCEEDED, {}, []),
                ("population", 4, StepStatus.SUCCEEDED, {}, []),
                ("build_evidence", 5, StepStatus.PENDING, {}, []),
                ("acmg_assessment", 6, StepStatus.PENDING, {}, []),
                ("review", 7, StepStatus.PENDING, {}, []),
                ("reportability", 8, StepStatus.PENDING, {}, []),
                ("report", 9, StepStatus.PENDING, {}, []),
                ("export_provenance", 10, StepStatus.PENDING, {}, []),
            ]
            for step_id, order, status, metadata, outputs in steps:
                db.add(WorkflowStep(
                    id=uuid4(), analysis_id=analysis_id, step_id=step_id,
                    step_order=order, status=status, attempt=0,
                    input_artifacts=[], output_artifacts=outputs,
                    metadata_json=metadata,
                ))
            partition = AnalysisPartition(
                id=uuid4(), analysis_id=analysis_id, step_id="normalize",
                partition_key="0:2", ordinal=0, record_start=0, record_end=2,
                variant_count=2, status="SUCCEEDED",
                metadata_json={"variant_ids": [str(value) for value in variant_ids]},
                resource_class="STANDARD", cpu_request=1.0, memory_mb=1024,
                attempt=1, lease_owner=None, lease_token=None, lease_expires_at=None,
            )
            configure_partition(partition, "STANDARD")
            partition.status = "SUCCEEDED"
            db.add(partition)
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", LocalSession)
        monkeypatch.setattr(db_module, "engine", engine)
        monkeypatch.setattr(workflow, "artifact_store_for_organization", lambda *_a, **_k: store)
        monkeypatch.setattr(workflow, "artifact_store_for_uri", lambda *_a, **_k: store)

        candidates = [
            SimpleNamespace(resource=resources[0]),
            SimpleNamespace(resource=resources[1]),
        ]
        executions = {
            g2p_resource_id: g2p_execution,
            clingen_resource_id: clingen_execution,
        }

        def fake_plan(*_args, **kwargs):
            requirements = kwargs.get("requirements", ())
            wanted = {
                requirement.capability for requirement in requirements
            }
            return SimpleNamespace(
                profile_type="TRIAL_PUBLIC", profile_version="integration",
                unavailable_optional=[],
                for_capability=lambda capability: candidates if capability in wanted and capability == workflow.ResourceCapability.GENE_DISEASE else [],
            )

        monkeypatch.setattr(workflow, "build_resource_execution_plan", fake_plan)
        monkeypatch.setattr(
            workflow, "resolve_resource_execution",
            lambda _db, *, resource, **_kwargs: executions[resource.id],
        )

        def crash_after_durable_evidence_commit(
            db, step, start, end, *, status, attempt=None, metadata=None, commit=True
        ):
            if step.step_id == "build_evidence" and status == "SUCCEEDED" and not crashed["value"]:
                # The production workflow committed Evidence rows immediately
                # before this checkpoint call. Simulate abrupt worker death here.
                crashed["value"] = True
                raise SystemExit(75)
            return real_save_checkpoint(
                db, step, start, end, status=status, attempt=attempt,
                metadata=metadata, commit=commit,
            )

        def stop_before_acmg(db, received_analysis_id, step_id):
            if step_id == "acmg_assessment" and stop_after_evidence["value"]:
                raise SystemExit(74)
            return real_step(db, received_analysis_id, step_id)

        monkeypatch.setattr(workflow, "_save_batch_checkpoint", crash_after_durable_evidence_commit)
        monkeypatch.setattr(workflow, "_step", stop_before_acmg)

        queue.run_analysis_task.push_request(
            id="c1-gene-disease-replay", retries=0,
            delivery_info={"redelivered": False},
        )
        try:
            with pytest.raises(SystemExit, match="75"):
                queue.run_analysis_task.run(str(analysis_id))
        finally:
            queue.run_analysis_task.pop_request()

        with LocalSession() as db:
            first_attempt = list(db.scalars(select(Evidence).where(
                Evidence.analysis_id == analysis_id,
                Evidence.payload["interpretive_use"].as_string()
                == "GENE_DISEASE_RECONCILIATION_CONTEXT_ONLY",
            )))
            assert len(first_attempt) == 4
            first_ids = {row.evidence_fingerprint for row in first_attempt}
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "build_evidence",
            ))
            assert step.metadata_json["batches"]["0:2"]["status"] == "RUNNING"

        # Redeliver through the real Celery task wrapper. The durable provider
        # query executions and evidence rows are reused; only the missing batch
        # success checkpoint is written.
        stop_after_evidence["value"] = True
        monkeypatch.setattr(workflow, "_save_batch_checkpoint", real_save_checkpoint)
        queue.run_analysis_task.push_request(
            id="c1-gene-disease-replay", retries=0,
            delivery_info={"redelivered": True},
        )
        try:
            with pytest.raises(SystemExit, match="74"):
                queue.run_analysis_task.run(str(analysis_id))
        finally:
            queue.run_analysis_task.pop_request()

        with LocalSession() as db:
            replayed = list(db.scalars(select(Evidence).where(
                Evidence.analysis_id == analysis_id,
                Evidence.payload["interpretive_use"].as_string()
                == "GENE_DISEASE_RECONCILIATION_CONTEXT_ONLY",
            )))
            assert len(replayed) == 4
            assert {row.evidence_fingerprint for row in replayed} == first_ids
            by_variant = {
                variant_id: [
                    row.payload for row in replayed if row.variant_id == variant_id
                ]
                for variant_id in variant_ids
            }
            gene1 = by_variant[variant_ids[0]]
            gene2 = by_variant[variant_ids[1]]
            assert {row["status"] for row in gene1} == {"G2P_ONLY", "CLINGEN_ONLY"}
            assert {row["status"] for row in gene2} == {
                "UNMATCHABLE_MISSING_MONDO", "CLINGEN_ONLY"
            }
            missing_mondo = next(
                row for row in gene2
                if row["status"] == "UNMATCHABLE_MISSING_MONDO"
            )
            assert missing_mondo["g2p_assertions"][0]["source_record_id"] == "G2P:G2P002"
            assert missing_mondo["g2p_assertions"][0]["mondo_id"] is None
            assert all(row["clinical_conclusion"] is False for row in replayed)
            assert all(row["requires_human_review"] for row in replayed)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "build_evidence",
            ))
            assert step.metadata_json["batches"]["0:2"]["status"] == "SUCCEEDED"
            assert step.status in {StepStatus.SUCCEEDED, StepStatus.REQUIRES_REVIEW}
            executions = list(db.scalars(select(ResourceExecutionRecord).where(
                ResourceExecutionRecord.analysis_id == analysis_id,
                ResourceExecutionRecord.step_id == "build_evidence",
            )))
            assert {
                row.metadata_json.get("execution_kind") for row in executions
            } >= {
                "G2P_GENE_DISEASE_MODEL_QUERY",
                "CLINGEN_GDV_GENE_DISEASE_MODEL_QUERY",
            }
            assert all(row.status in {"SUCCESS", "NO_DATA"} for row in executions)
    finally:
        # Test-specific rows are removed in FK-safe order. Audit events are
        # removed with this isolated integration analysis as in other PG tests.
        with LocalSession() as db:
            db.query(Evidence).filter(Evidence.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(Annotation).filter(Annotation.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(ResourceExecutionRecord).filter(ResourceExecutionRecord.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(WorkflowStep).filter(WorkflowStep.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(AnalysisPartition).filter(AnalysisPartition.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(Artifact).filter(Artifact.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(AuditEvent).filter(AuditEvent.analysis_id == analysis_id).delete(synchronize_session=False)
            db.query(Analysis).filter(Analysis.id == analysis_id).delete(synchronize_session=False)
            db.query(ResourceQualification).filter(ResourceQualification.id.in_([g2p_qualification_id, clingen_qualification_id])).delete(synchronize_session=False)
            db.query(Resource).filter(Resource.id.in_([g2p_resource_id, clingen_resource_id])).delete(synchronize_session=False)
            db.query(Variant).filter(Variant.id.in_(variant_ids)).delete(synchronize_session=False)
            db.query(Case).filter(Case.id == case_id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            db.query(Organization).filter(Organization.id == organization_id).delete(synchronize_session=False)
            db.commit()
        engine.dispose()
