"""Production VCF worker integration with PostgreSQL and pinned BCFtools."""

import gzip
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.workflow_decision import WorkflowAction, WorkflowDecision
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    AuditEvent,
    Case,
    Organization,
    OrganizationStorageProfile,
    Resource,
    User,
    WorkflowStep,
)


@pytest.mark.integration
def test_postgres_worker_persists_gvcf_routing_and_real_bcftools_output(
    monkeypatch, tmp_path: Path,
):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL workflow integration requires DATABASE_URL")
    executable = shutil.which("bcftools")
    if executable is None:
        pytest.skip("Pinned BCFtools 1.19 is required for this workflow integration")
    version = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, check=True,
    ).stdout.splitlines()[0]
    assert version == "bcftools 1.19"

    import importlib

    workflow = importlib.import_module("backend.app.workflows.variant")
    db_module = importlib.import_module("backend.app.infrastructure.db.session")
    engine = create_engine(database_url, pool_pre_ping=True)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)
    artifact_root = tmp_path / "gvcf-worker-artifacts"
    store = ArtifactStore(artifact_root)
    organization_id, user_id, case_id, analysis_id, resource_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    sequence = "A" * 100
    fasta = tmp_path / "reference.fa"
    fasta.write_text(f">1\n{sequence}\n", encoding="utf-8", newline="\n")
    (tmp_path / "reference.fa.fai").write_text(
        f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence) + 1}\n",
        encoding="utf-8",
    )
    source = tmp_path / "sample.g.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=100>\n"
        '##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n'
        '##INFO=<ID=DP,Number=1,Type=Integer,Description="Depth">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Phred likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t1\t.\tA\t<NON_REF>\t.\tPASS\tEND=10;DP=30\tGT:AD:PL\t0/0:30,0:0,40,400\n"
        "1\t11\trsG\tA\tC,<NON_REF>\t50\tPASS\tDP=24\tGT:AD:PL\t0/1:15,9,0:100,50,60,40,0,30\n",
        encoding="utf-8",
    )

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"GVCF Worker Integration {organization_id}",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@gvcf.integration.test",
                display_name="GVCF Worker Integration",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"GVCF-{analysis_id}",
                status="ACTIVE",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            db.add(OrganizationStorageProfile(
                id=uuid4(),
                organization_id=organization_id,
                name="integration-artifacts",
                version=1,
                backend_type="LOCAL_FILESYSTEM",
                storage_key="PRIMARY_ARTIFACTS",
                configuration_json={"target_id": "gvcf-integration"},
                status="ACTIVE",
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
                workflow_version="integration",
                status=AnalysisStatus.QUEUED,
                queue_task_id=f"gvcf-worker-{analysis_id}",
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            )
            db.add(analysis)
            db.flush()
            source_artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=source,
                filename=source.name,
                artifact_type="SOURCE_VCF",
                media_type="text/plain",
                genome_build="GRCh38",
                validation_status="VALID",
            )
            source_artifact_id = source_artifact.id
            source_artifact_sha256 = source_artifact.sha256
            source_artifact_storage_uri = source_artifact.storage_uri
            analysis.configuration = {
                "input_artifact_id": str(source_artifact_id),
                "reference_resource_id": str(resource_id),
            }
            db.add(Resource(
                id=resource_id,
                organization_id=organization_id,
                name="GVCF worker test reference",
                provider="SIRALOOM_TEST",
                resource_type="REFERENCE_PACKAGE",
                version="fixture-1",
                genome_build="GRCh38",
                access_method="API",
                license_text="test fixture",
                checksum="a" * 64,
                location="https://fixture.invalid/reference",
                status="ACTIVE",
                population_definition=None,
                metadata_json={},
            ))
            db.commit()

        monkeypatch.setattr(db_module, "SessionLocal", local_session)
        monkeypatch.setattr(
            workflow.settings,
            "artifact_storage_targets_json",
            json.dumps({
                "gvcf-integration": {
                    "backend_type": "LOCAL_FILESYSTEM",
                    "root": str(artifact_root),
                    "organization_id": str(organization_id),
                },
            }),
        )
        monkeypatch.setattr(
            workflow, "artifact_store_for_organization", lambda *_args, **_kwargs: store,
        )
        decision = WorkflowDecision(
            WorkflowAction.CONTINUE,
            "TEST_REFERENCE_SELECTED",
            "Fixture reference selected",
        )
        monkeypatch.setattr(
            workflow,
            "resolve_resource_with_fallback",
            lambda db, **_kwargs: SimpleNamespace(
                resource=db.get(Resource, resource_id),
                used_fallback=False,
                requested_resource_id=resource_id,
                fallback_resource_id=None,
                decision=decision,
            ),
        )
        monkeypatch.setattr(workflow, "load_reference_package", lambda *_args, **_kwargs: {
            "resource_id": str(resource_id),
            "version": "fixture-1",
            "package_checksum": "a" * 64,
            "fasta_path": str(fasta),
            "fasta_sha256": "b" * 64,
            "fai_sha256": "c" * 64,
            "contigs_sha256": "d" * 64,
            "contig_policy": "EXACT",
            "contigs": [{"name": "1", "length": len(sequence)}],
        })
        monkeypatch.setattr(
            workflow,
            "resolve_resource_execution",
            lambda *_args, **_kwargs: SimpleNamespace(
                contract=SimpleNamespace(access_method="API"),
                snapshot={"test": True},
                contract_hash="e" * 64,
            ),
        )
        monkeypatch.setattr(
            workflow, "start_resource_execution", lambda *_args, **_kwargs: SimpleNamespace(),
        )
        monkeypatch.setattr(workflow, "complete_resource_execution", lambda *_args, **_kwargs: None)

        workflow.run_variant_analysis(analysis_id)

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            normalization = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "normalize",
            ))
            normalized = db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "NORMALIZED_VCF",
            ))
            block = db.scalar(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "GVCF_REFERENCE_BLOCKS",
            ))
            completion = db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "NORMALIZATION_COMPLETED",
            ))
            assert normalization is not None and normalization.status == StepStatus.SUCCEEDED
            assert normalization.metadata_json["routing"]["gvcf_reference_blocks"] == 1
            assert normalization.metadata_json["routing"]["sequence_records"] == 1
            assert normalized is not None and store.exists(normalized.storage_uri)
            assert normalized.metadata_json["normalization_tool_version"] == "bcftools 1.19"
            assert "bcftools view --no-version -A" in normalized.metadata_json["normalization_command"]
            normalized_bytes = store.read_bytes(normalized.storage_uri)
            assert __import__("hashlib").sha256(normalized_bytes).hexdigest() == normalized.sha256
            records = [
                line.split("\t") for line in gzip.decompress(normalized_bytes).decode("utf-8").splitlines()
                if line and not line.startswith("#")
            ]
            assert len(records) == 1
            assert records[0][4] == "C"
            assert records[0][8] == "GT:AD:PL"
            assert records[0][9] == "0/1:15,9:100,50,60"
            assert block is not None and store.exists(block.storage_uri)
            assert block.metadata_json["record_count"] == 1
            assert block.metadata_json["source_artifact_id"] == str(source_artifact_id)
            assert block.metadata_json["source_sha256"] == source_artifact_sha256
            assert block.metadata_json["reference_validation_status"] == "PASS"
            assert block.metadata_json["reference_package_id"] == str(resource_id)
            assert block.metadata_json["reference_package_version"] == "fixture-1"
            assert block.metadata_json["reference_fasta_sha256"] == "b" * 64
            assert "END=10" in store.read_bytes(block.storage_uri).decode("utf-8")
            assert completion is not None
            audit_output_ids = {item["artifact_id"] for item in completion.output_artifacts}
            assert {str(normalized.id), str(block.id)}.issubset(audit_output_ids)
            assert audit_output_ids.issubset(set(normalization.output_artifacts))
            assert analysis is not None
            assert store.read_bytes(source_artifact_storage_uri) == source.read_bytes()
    finally:
        engine.dispose()
