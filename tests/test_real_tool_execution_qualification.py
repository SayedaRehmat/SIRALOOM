from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.adapters.annotation.vep import VEPProvider
from backend.app.domain.execution_environments import ExecutionCapacity, ExecutionEnvironmentProfile
from backend.app.domain.persistent_tool_executor import PersistentToolExecutionService
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.tool_execution import LocalProcessToolExecutor, sha256_file, current_platform_id
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    Case,
    Organization,
    ToolExecutionRecord,
    User,
)
from backend.app.domain.execution_persistence import register_environment_profile


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
        session.rollback()
    engine.dispose()


def _lab(db: Session):
    organization = Organization(id=uuid4(), name="VEP Qualification Lab")
    db.add(organization)
    db.flush()
    user = User(
        id=uuid4(),
        organization_id=organization.id,
        display_name="Qualification Operator",
        role="lab_admin",
        status="ACTIVE",
    )
    db.add(user)
    db.flush()
    case = Case(
        id=uuid4(),
        organization_id=organization.id,
        case_identifier=f"VEP-QUAL-{uuid4().hex[:8]}",
        status="DRAFT",
        clinical_context={},
        language="en",
        created_by=user.id,
    )
    db.add(case)
    db.flush()
    analysis = Analysis(
        id=uuid4(),
        case_id=case.id,
        analysis_type="GERMLINE",
        workflow_id="germline-standard",
        workflow_version="1",
        status="QUEUED",
        reference_build="GRCh38",
        created_by=user.id,
    )
    db.add(analysis)
    db.flush()
    return organization, case, analysis


@pytest.mark.skipif(
    os.getenv("SIRALOOM_RUN_REAL_VEP_QUALIFICATION") != "1",
    reason="Set SIRALOOM_RUN_REAL_VEP_QUALIFICATION=1 in a provisioned VEP qualification environment.",
)
def test_real_vep_binary_and_cache_run_through_durable_executor(db, tmp_path):
    required = (
        "SIRALOOM_VEP_BINARY",
        "SIRALOOM_VEP_CACHE_DIR",
        "SIRALOOM_VEP_CACHE_MANIFEST",
        "SIRALOOM_VEP_VERSION",
        "SIRALOOM_VEP_PROFILE_ID",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.fail("Real VEP qualification was enabled but required variables are missing: " + ", ".join(missing))

    binary = Path(os.environ["SIRALOOM_VEP_BINARY"]).resolve(strict=True)
    cache_dir = Path(os.environ["SIRALOOM_VEP_CACHE_DIR"]).resolve(strict=True)
    manifest_path = Path(os.environ["SIRALOOM_VEP_CACHE_MANIFEST"]).resolve(strict=True)
    expected_version = os.environ["SIRALOOM_VEP_VERSION"]
    profile_id = os.environ["SIRALOOM_VEP_PROFILE_ID"]
    assembly = os.getenv("SIRALOOM_VEP_ASSEMBLY", "GRCh38")
    fasta_text = os.getenv("SIRALOOM_VEP_FASTA")
    fasta = Path(fasta_text).resolve(strict=True) if fasta_text else None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cache_artifact_sha256 = str(manifest["source_artifact_sha256"])
    manifest_sha256 = sha256_file(manifest_path)
    binary_sha256 = sha256_file(binary)

    if current_platform_id() != "linux-64":
        pytest.skip("This qualification profile currently targets Linux AMD64.")

    organization, case, analysis = _lab(db)
    workspace_root = tmp_path / "lab-workspaces"
    workspace_root.mkdir()
    environment_profile = ExecutionEnvironmentProfile(
        environment_id=f"vep-qualification-{uuid4().hex[:12]}",
        profile_version="1",
        owner_scope="LABORATORY",
        organization_id=organization.id,
        executor_kind="LOCAL_PROCESS",
        platform="linux-64",
        operating_system="linux",
        architecture="x86_64",
        kernel_release=platform.release(),
        runtime_kind="HOST",
        runtime_version="host-managed",
        runtime_image_digest=None,
        scheduler="DOCKER_COMPOSE",
        capacity=ExecutionCapacity(
            cpu_cores=4,
            memory_bytes=16 * 1024**3,
            scratch_bytes=50 * 1024**3,
            max_concurrency=1,
        ),
        workspace_root=str(workspace_root),
        storage_profile_ids=("vep-qualification-artifacts-v1",),
        supported_tool_profile_ids=(profile_id,),
        tool_executable_sha256=((profile_id, binary_sha256),),
        network_policy="OFFLINE",
        qualification_status="ENVIRONMENT_QUALIFIED",
    )
    environment = register_environment_profile(
        db, environment_profile, organization_id=organization.id
    )
    db.commit()

    service = PersistentToolExecutionService(
        db,
        organization_id=organization.id,
        analysis_id=analysis.id,
        environment_registration_id=environment.id,
        worker_id="real-vep-qualification-worker",
        executor=LocalProcessToolExecutor(),
    )

    toolchain = {
        "vep_binary": str(binary),
        "vep_binary_sha256": binary_sha256,
        "vep_version": expected_version,
        "execution_profile_id": profile_id,
        "cache_dir": str(cache_dir),
        "cache_version": str(manifest["cache_version"]),
        "assembly": assembly,
        "cache_manifest": str(manifest_path),
        "cache_manifest_sha256": manifest_sha256,
        "cache_artifact_sha256": cache_artifact_sha256,
    }
    if fasta:
        toolchain["fasta"] = str(fasta)

    contract = ResourceExecutionContract(
        provider_id="VEP",
        provider_version=expected_version,
        access_method="LOCAL",
        endpoint=None,
        location=str(cache_dir),
        dataset="ensembl-vep-offline-cache",
        execution_scope="ORGANIZATION_MANAGED",
        toolchain=toolchain,
    )
    provider = VEPProvider.from_execution_contract(contract)
    provider.persistent_execution_service = service
    provider.persistent_execution_required = True

    def publish_output(request, result, execution_record_id):
        output = Path(request.outputs[0].path)
        artifact = Artifact(
            id=uuid4(),
            analysis_id=analysis.id,
            case_id=case.id,
            artifact_type="VEP_RAW_ANNOTATION",
            filename=output.name,
            media_type="application/json",
            size_bytes=output.stat().st_size,
            sha256=sha256_file(output),
            storage_uri=f"file:///vep-qualification/{analysis.id}/{output.name}",
        )
        db.add(artifact)
        db.flush()
        return {request.outputs[0].name: artifact.id}

    provider.persistent_artifact_publisher = publish_output

    variant_text = os.getenv("SIRALOOM_VEP_QUALIFICATION_VARIANT", "1:100000:A:G")
    chromosome, position, reference, alternate = variant_text.split(":")
    variant = CanonicalVariant(
        genome_build=assembly,
        chromosome=chromosome,
        position=int(position),
        reference=reference,
        alternate=alternate,
    )
    observations = provider.annotate(
        [variant],
        {"genome": "hg38" if assembly == "GRCh38" else "hg19"},
    )

    assert observations
    records = db.query(ToolExecutionRecord).filter(
        ToolExecutionRecord.analysis_id == analysis.id
    ).all()
    assert len(records) >= 3  # VEP version, offline cache preflight, annotation
    assert all(record.status == "SUCCEEDED" for record in records)
    annotation_records = [
        record for record in records
        if record.operation == "annotate"
    ]
    assert annotation_records
    assert annotation_records[-1].output_manifest
    assert annotation_records[-1].output_manifest[0].get("artifact_id")
