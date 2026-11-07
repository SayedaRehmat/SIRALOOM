from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import os
import shutil
import subprocess
from uuid import uuid4
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.execution_environments import ExecutionCapacity, ExecutionEnvironmentProfile
from backend.app.domain.execution_persistence import (
    ExecutionPersistenceError,
    execution_request_fingerprint,
    claim_tool_execution,
    complete_tool_execution,
    fail_tool_execution,
    register_environment_profile,
    register_tool_execution,
)
from backend.app.domain.persistent_tool_executor import PersistentToolExecutionService
from backend.app.domain.tool_execution import (
    InputArtifact,
    OutputArtifact,
    ToolExecutionProvenance,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolIdentity,
    LocalProcessToolExecutor,
    current_platform_id,
    sha256_file,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, Organization, User


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
        session.rollback()
    engine.dispose()


def _lab(db: Session):
    organization = Organization(id=uuid4(), name="Persistence Test Lab")
    db.add(organization)
    db.flush()
    user = User(
        id=uuid4(),
        organization_id=organization.id,
        display_name="Test Operator",
        role="lab_admin",
        status="ACTIVE",
    )
    db.add(user)
    db.flush()
    case = Case(
        id=uuid4(),
        organization_id=organization.id,
        case_identifier=f"CASE-{uuid4().hex[:8]}",
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
    return organization, user, case, analysis


def _profile(organization_id):
    return ExecutionEnvironmentProfile(
        environment_id="lab-execution-node-01",
        profile_version="1",
        owner_scope="LABORATORY",
        organization_id=organization_id,
        executor_kind="LOCAL_PROCESS",
        platform="linux-64",
        operating_system="linux",
        architecture="x86_64",
        kernel_release="6.8.0",
        runtime_kind="HOST",
        runtime_version="host-managed",
        runtime_image_digest=None,
        scheduler="DOCKER_COMPOSE",
        capacity=ExecutionCapacity(
            cpu_cores=8,
            memory_bytes=32 * 1024**3,
            scratch_bytes=100 * 1024**3,
            max_concurrency=4,
        ),
        workspace_root="/var/lib/siraloom/workspaces",
        storage_profile_ids=("lab-artifacts-v1",),
        supported_tool_profile_ids=("bcftools-1.25-htslib-1.25-linux-amd64",),
        network_policy="OFFLINE",
        tool_executable_sha256=(("bcftools-1.25-htslib-1.25-linux-amd64", "a" * 64),),
        qualification_status="ENVIRONMENT_QUALIFIED",
    )


def _tool():
    return ToolIdentity(
        tool_id="bcftools",
        version="1.25",
        profile_id="bcftools-1.25-htslib-1.25-linux-amd64",
        executable="/usr/bin/bcftools",
        executable_sha256="a" * 64,
        platform="linux-64",
        qualification_status="SOFTWARE_QUALIFIED",
        version_args=("--version",),
        version_output_contains="bcftools 1.25",
    )


def _register(db, organization, analysis):
    environment = register_environment_profile(
        db,
        _profile(organization.id),
        organization_id=organization.id,
    )
    tool = _tool()
    snapshot = {
        "execution_id": "execution-001",
        "organization_id": str(organization.id),
        "workflow_id": analysis.workflow_id,
        "operation": "normalize",
        "argv": ["bcftools", "norm", "--threads", "2"],
    }
    record = register_tool_execution(
        db,
        organization_id=organization.id,
        analysis_id=analysis.id,
        execution_id="execution-001",
        idempotency_key="idem-001",
        request_fingerprint=execution_request_fingerprint(
            organization_id=organization.id,
            analysis_id=analysis.id,
            execution_id="execution-001",
            environment_registration_id=environment.id,
            tool=tool,
            operation="normalize",
            request_snapshot=snapshot,
            input_manifest=[{"name": "input.vcf.gz", "sha256": "b" * 64}],
        ),
        environment_registration_id=environment.id,
        tool=tool,
        operation="normalize",
        request_snapshot=snapshot,
        input_manifest=[{"name": "input.vcf.gz", "sha256": "b" * 64}],
    )
    db.flush()
    return environment, tool, snapshot, record


def test_environment_registration_is_idempotent_and_version_content_is_immutable(db):
    organization, _user, _case, _analysis = _lab(db)
    profile = _profile(organization.id)

    first = register_environment_profile(db, profile, organization_id=organization.id)
    repeated = register_environment_profile(db, profile, organization_id=organization.id)

    assert first.id == repeated.id
    changed = replace(profile, capacity=replace(profile.capacity, cpu_cores=16))
    with pytest.raises(ExecutionPersistenceError, match="different profile bytes"):
        register_environment_profile(db, changed, organization_id=organization.id)


def test_environment_registration_rejects_cross_tenant_owner_binding(db):
    organization_a, _user_a, _case_a, _analysis_a = _lab(db)
    organization_b, _user_b, _case_b, _analysis_b = _lab(db)

    with pytest.raises(ExecutionPersistenceError, match="owning organization"):
        register_environment_profile(
            db,
            _profile(organization_a.id),
            organization_id=organization_b.id,
        )


def test_case_scoped_execution_can_be_registered_before_analysis_exists(db):
    organization, _user, case, _analysis = _lab(db)
    environment = register_environment_profile(
        db, _profile(organization.id), organization_id=organization.id
    )
    tool = _tool()
    request_snapshot = {
        "execution_id": "intake-validation-001",
        "operation": "validate",
        "argv": ["bcftools", "view", "--header-only"],
    }
    input_manifest = [{"name": "uploaded.vcf.gz", "sha256": "b" * 64}]
    fingerprint = execution_request_fingerprint(
        organization_id=organization.id,
        analysis_id=None,
        case_id=case.id,
        execution_id="intake-validation-001",
        environment_registration_id=environment.id,
        tool=tool,
        operation="validate",
        request_snapshot=request_snapshot,
        input_manifest=input_manifest,
    )

    record = register_tool_execution(
        db,
        organization_id=organization.id,
        case_id=case.id,
        analysis_id=None,
        execution_id="intake-validation-001",
        idempotency_key="intake-idem-001",
        request_fingerprint=fingerprint,
        environment_registration_id=environment.id,
        tool=tool,
        operation="validate",
        request_snapshot=request_snapshot,
        input_manifest=input_manifest,
    )

    assert record.case_id == case.id
    assert record.analysis_id is None
    assert record.status == "PENDING"


def test_execution_registration_is_tenant_scoped_and_idempotent(db):
    organization, _user, _case, analysis = _lab(db)
    _environment, _tool_identity, snapshot, record = _register(db, organization, analysis)

    replay = register_tool_execution(
        db,
        organization_id=organization.id,
        analysis_id=analysis.id,
        execution_id="execution-001",
        idempotency_key="idem-001",
        request_fingerprint=execution_request_fingerprint(
            organization_id=organization.id,
            analysis_id=analysis.id,
            execution_id="execution-001",
            environment_registration_id=record.environment_registration_id,
            tool=_tool(),
            operation="normalize",
            request_snapshot=snapshot,
            input_manifest=[{"name": "input.vcf.gz", "sha256": "b" * 64}],
        ),
        environment_registration_id=record.environment_registration_id,
        tool=_tool(),
        operation="normalize",
        request_snapshot=snapshot,
        input_manifest=[{"name": "input.vcf.gz", "sha256": "b" * 64}],
    )
    assert replay.id == record.id

    changed_snapshot = {**snapshot, "argv": ["bcftools", "norm", "--threads", "4"]}
    changed_fingerprint = execution_request_fingerprint(
        organization_id=organization.id,
        analysis_id=analysis.id,
        execution_id="execution-001",
        environment_registration_id=record.environment_registration_id,
        tool=_tool(),
        operation="normalize",
        request_snapshot=changed_snapshot,
        input_manifest=[{"name": "input.vcf.gz", "sha256": "b" * 64}],
    )
    with pytest.raises(ExecutionPersistenceError, match="different execution request"):
        register_tool_execution(
            db,
            organization_id=organization.id,
            analysis_id=analysis.id,
            execution_id="execution-001",
            idempotency_key="idem-001",
            request_fingerprint=changed_fingerprint,
            environment_registration_id=record.environment_registration_id,
            tool=_tool(),
            operation="normalize",
            request_snapshot=changed_snapshot,
            input_manifest=[{"name": "input.vcf.gz", "sha256": "b" * 64}],
        )


def test_execution_cannot_be_registered_for_another_tenants_analysis(db):
    organization_a, _user_a, _case_a, _analysis_a = _lab(db)
    organization_b, _user_b, _case_b, analysis_b = _lab(db)
    environment = register_environment_profile(
        db, _profile(organization_a.id), organization_id=organization_a.id
    )

    with pytest.raises(ExecutionPersistenceError, match="does not belong"):
        register_tool_execution(
            db,
            organization_id=organization_a.id,
            analysis_id=analysis_b.id,
            execution_id="cross-tenant",
            idempotency_key="cross-tenant-idem",
            request_fingerprint="d" * 64,
            environment_registration_id=environment.id,
            tool=_tool(),
            operation="normalize",
            request_snapshot={"execution_id": "cross-tenant"},
            input_manifest=[],
        )


def test_execution_claim_reclaims_expired_lease_and_fences_stale_worker(db):
    organization, _user, _case, analysis = _lab(db)
    _environment, _tool_identity, _snapshot, record = _register(db, organization, analysis)
    now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)

    first_token = claim_tool_execution(
        db,
        organization_id=organization.id,
        execution_record_id=record.id,
        worker_id="worker-a",
        lease_seconds=30,
        now=now,
    )
    with pytest.raises(ExecutionPersistenceError, match="already leased"):
        claim_tool_execution(
            db,
            organization_id=organization.id,
            execution_record_id=record.id,
            worker_id="worker-b",
            lease_seconds=30,
            now=now + timedelta(seconds=10),
        )

    second_token = claim_tool_execution(
        db,
        organization_id=organization.id,
        execution_record_id=record.id,
        worker_id="worker-b",
        lease_seconds=30,
        now=now + timedelta(seconds=31),
    )
    assert second_token != first_token
    with pytest.raises(ExecutionPersistenceError, match="stale"):
        fail_tool_execution(
            db,
            organization_id=organization.id,
            execution_record_id=record.id,
            lease_token=first_token,
            error_code="WORKER_LOST",
            error_message="Old worker attempted to update after lease expiry.",
            retryable=True,
            now=now + timedelta(seconds=32),
        )


def test_success_requires_persisted_analysis_output_and_matching_hashes(db):
    organization, user, case, analysis = _lab(db)
    _environment, _tool_identity, _snapshot, record = _register(db, organization, analysis)
    token = claim_tool_execution(
        db,
        organization_id=organization.id,
        execution_record_id=record.id,
        worker_id="worker-a",
    )

    output_bytes = b"normalized-vcf-content"
    output_hash = hashlib.sha256(output_bytes).hexdigest()
    artifact = Artifact(
        id=uuid4(),
        analysis_id=analysis.id,
        case_id=case.id,
        artifact_type="NORMALIZED_VCF",
        filename="normalized.vcf.gz",
        media_type="application/gzip",
        size_bytes=len(output_bytes),
        sha256=output_hash,
        storage_uri="file:///durable/artifacts/normalized.vcf.gz",
    )
    db.add(artifact)
    db.flush()

    provenance = {
        "execution_id": record.execution_id,
        "organization_id": str(organization.id),
        "workflow_id": analysis.workflow_id,
        "operation": "normalize",
        "tool_id": "bcftools",
        "tool_version": "1.25",
        "profile_id": "bcftools-1.25-htslib-1.25-linux-amd64",
        "executable_sha256": "a" * 64,
        "platform": "linux-64",
        "runtime_image_digest": None,
        "environment_sha256": "d" * 64,
        "input_sha256": [{"name": "input.vcf.gz", "sha256": "b" * 64}],
        "exit_code": 0,
        "stdout_sha256": "e" * 64,
        "stderr_sha256": "f" * 64,
        "output_sha256": [{"name": "normalized.vcf.gz", "sha256": output_hash}],
        "argv": ["bcftools", "norm", "--token", "must-not-be-persisted"],
    }
    manifest = [{
        "name": "normalized.vcf.gz",
        "artifact_id": str(artifact.id),
        "sha256": output_hash,
    }]

    result = complete_tool_execution(
        db,
        organization_id=organization.id,
        execution_record_id=record.id,
        lease_token=token,
        provenance=provenance,
        output_manifest=manifest,
    )

    assert result.status == "SUCCEEDED"
    assert result.provenance["output_sha256"][0]["sha256"] == output_hash
    assert result.provenance["argv"][-1] == "[REDACTED]"
    assert result.lease_token is None


def test_success_rejects_output_artifact_from_another_analysis(db):
    organization, _user, _case, analysis = _lab(db)
    _environment, _tool_identity, _snapshot, record = _register(db, organization, analysis)
    token = claim_tool_execution(
        db,
        organization_id=organization.id,
        execution_record_id=record.id,
        worker_id="worker-a",
    )
    provenance = {
        "execution_id": record.execution_id,
        "organization_id": str(organization.id),
        "workflow_id": analysis.workflow_id,
        "operation": "normalize",
        "tool_id": "bcftools",
        "tool_version": "1.25",
        "profile_id": "bcftools-1.25-htslib-1.25-linux-amd64",
        "executable_sha256": "a" * 64,
        "platform": "linux-64",
        "runtime_image_digest": None,
        "environment_sha256": "d" * 64,
        "input_sha256": [{"name": "input.vcf.gz", "sha256": "b" * 64}],
        "exit_code": 0,
        "stdout_sha256": "e" * 64,
        "stderr_sha256": "f" * 64,
        "output_sha256": [],
    }

    with pytest.raises(ExecutionPersistenceError, match="not durably registered"):
        complete_tool_execution(
            db,
            organization_id=organization.id,
            execution_record_id=record.id,
            lease_token=token,
            provenance=provenance,
            output_manifest=[{
                "name": "missing",
                "artifact_id": str(uuid4()),
                "sha256": "c" * 64,
            }],
        )


def test_persistent_executor_records_real_process_result_and_published_output(db, tmp_path):
    organization, user, case, analysis = _lab(db)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = tmp_path / "fake-bcftools"
    executable.write_text("#!/bin/sh\\necho 'bcftools 1.25'\\n", encoding="utf-8")
    executable.chmod(0o755)
    input_path = workspace / "input.vcf"
    input_path.write_text("##fileformat=VCFv4.2\\n", encoding="utf-8")
    output_path = workspace / "normalized.vcf.gz"

    executable_digest = sha256_file(executable)
    profile = ToolIdentity(
        tool_id="bcftools",
        version="1.25",
        profile_id="bcftools-1.25-htslib-1.25-linux-amd64",
        executable=str(executable),
        executable_sha256=executable_digest,
        platform=current_platform_id(),
        qualification_status="SOFTWARE_QUALIFIED",
        version_args=("--version",),
        version_output_contains="bcftools 1.25",
        supported_operations=("normalize",),
        runtime_path=(str(tmp_path),),
    )
    environment_profile = replace(
        _profile(organization.id),
        tool_executable_sha256=((profile.profile_id, executable_digest),),
        workspace_root=str(workspace),
    )
    environment = register_environment_profile(
        db, environment_profile, organization_id=organization.id
    )
    db.commit()

    class FakeExecutor:
        def execute(self, supplied_profile, request):
            output_path.write_bytes(b"normalized VCF bytes")
            output_digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
            provenance = ToolExecutionProvenance(
                execution_id=request.execution_id,
                organization_id=request.organization_id,
                workflow_id=request.workflow_id,
                operation=request.operation,
                tool_id=supplied_profile.tool_id,
                tool_version=supplied_profile.version,
                profile_id=supplied_profile.profile_id,
                executable_sha256=supplied_profile.executable_sha256,
                resource_bindings=(),
                input_sha256=({"name": "input.vcf", "sha256": sha256_file(input_path)},),
                output_sha256=({"name": "normalized.vcf.gz", "sha256": output_digest},),
                argv=(supplied_profile.executable, *request.argv),
                exit_code=0,
                started_at=datetime.now(timezone.utc).isoformat(),
                completed_at=datetime.now(timezone.utc).isoformat(),
                duration_seconds=0.01,
                stdout_sha256="e" * 64,
                stderr_sha256="f" * 64,
                platform=supplied_profile.platform,
                runtime_image_digest=supplied_profile.runtime_image_digest,
                environment_sha256="d" * 64,
            )
            return ToolExecutionResult(provenance=provenance, stdout="", stderr="")

    def publish(request, result, execution_record_id):
        artifact = Artifact(
            id=uuid4(),
            analysis_id=analysis.id,
            case_id=case.id,
            artifact_type="NORMALIZED_VCF",
            filename="normalized.vcf.gz",
            media_type="application/gzip",
            size_bytes=output_path.stat().st_size,
            sha256=sha256_file(output_path),
            storage_uri="file:///durable/normalized.vcf.gz",
        )
        db.add(artifact)
        db.flush()
        return {"normalized.vcf.gz": artifact.id}

    service = PersistentToolExecutionService(
        db,
        organization_id=organization.id,
        analysis_id=analysis.id,
        environment_registration_id=environment.id,
        worker_id="worker-test",
        executor=FakeExecutor(),
    )
    request = ToolExecutionRequest(
        execution_id="normalization-execution-001",
        organization_id=str(organization.id),
        workflow_id="normalize",
        operation="normalize",
        argv=("norm", "-f", str(input_path), "-o", str(output_path)),
        workspace=str(workspace),
        inputs=(InputArtifact("input.vcf", str(input_path), sha256_file(input_path)),),
        outputs=(OutputArtifact("normalized.vcf.gz", str(output_path)),),
    )

    result = service.execute(profile, request, artifact_publisher=publish)

    assert result.record_id in service.execution_record_ids
    persisted = db.get(__import__("backend.app.infrastructure.db.models", fromlist=["ToolExecutionRecord"]).ToolExecutionRecord, result.record_id)
    assert persisted.status == "SUCCEEDED"
    assert persisted.output_manifest[0]["artifact_id"]
    assert persisted.provenance["tool_id"] == "bcftools"


def test_persistent_executor_runs_real_bcftools_normalization_and_index_lifecycle(db, tmp_path):
    from backend.app.config import settings
    from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools
    from backend.app.infrastructure.db.models import ToolExecutionRecord

    conda_prefix = Path(os.getenv("CONDA_PREFIX", ""))
    conda_bcftools = conda_prefix / "bin" / "bcftools"
    executable_text = (
        shutil.which(settings.bcftools_executable)
        or shutil.which("bcftools")
        or (str(conda_bcftools) if conda_bcftools.is_file() else None)
    )
    if not executable_text:
        message = (
            "Pinned BCFtools is not discoverable; "
            f"PATH={os.getenv('PATH', '')!r}, CONDA_PREFIX={os.getenv('CONDA_PREFIX')!r}."
        )
        if os.getenv("GITHUB_ACTIONS") == "true":
            pytest.fail(message)
        pytest.skip(message)
    executable = Path(executable_text).resolve()
    version = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    version_output = version.stdout + version.stderr
    if (
        version.returncode != 0
        or f"bcftools {settings.bcftools_version}" not in version_output
        or f"Using htslib {settings.htslib_version}" not in version_output
    ):
        message = (
            "Real BCFtools qualification requires the configured pinned pair; "
            f"expected bcftools={settings.bcftools_version}, htslib={settings.htslib_version}, "
            f"observed output={version_output!r}."
        )
        if os.getenv("GITHUB_ACTIONS") == "true":
            pytest.fail(message)
        pytest.skip(message)

    organization, _user, case, analysis = _lab(db)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    input_path = workspace / "input.vcf"
    input_path.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=1,length=1000>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t100\t.\tA\tG,T\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    reference_path = workspace / "reference.fa"
    reference_path.write_text(">1\n" + ("A" * 1000) + "\n", encoding="ascii")
    Path(str(reference_path) + ".fai").write_text("1\t1000\t3\t1000\t1001\n", encoding="ascii")
    output_path = workspace / "normalized.vcf.gz"

    executable_digest = sha256_file(executable)
    environment_profile = replace(
        _profile(organization.id),
        workspace_root=str(workspace),
        supported_tool_profile_ids=(settings.bcftools_profile_id,),
        tool_executable_sha256=((settings.bcftools_profile_id, executable_digest),),
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
        worker_id="real-bcftools-normalization-qualification",
        executor=LocalProcessToolExecutor(),
    )

    result = normalize_vcf_with_bcftools(
        input_path,
        output_path,
        reference_fasta=reference_path,
        persistent_execution=service,
        workflow_id="normalize",
        expected_bcftools_version=settings.bcftools_version,
        timeout_seconds=120,
        bcftools_executable=str(executable),
    )

    assert output_path.is_file() and output_path.stat().st_size > 0
    index_path = Path(str(output_path) + ".csi")
    assert index_path.is_file() and index_path.stat().st_size > 0
    assert result["index_validation"]["method"] == "INDEXED_QUERY_SHA256_VS_SEQUENTIAL_BGZF_SCAN"
    assert len(result["tool_execution_record_ids"]) >= 7

    vcf_artifact = Artifact(
        id=uuid4(),
        analysis_id=analysis.id,
        case_id=case.id,
        artifact_type="NORMALIZED_VCF",
        filename=output_path.name,
        media_type="application/gzip",
        size_bytes=output_path.stat().st_size,
        sha256=sha256_file(output_path),
        storage_uri=f"file:///qualified-artifacts/{analysis.id}/{output_path.name}",
        metadata_json={"tool_execution_record_ids": result["tool_execution_record_ids"]},
    )
    index_artifact = Artifact(
        id=uuid4(),
        analysis_id=analysis.id,
        case_id=case.id,
        artifact_type="VCF_INDEX",
        filename=index_path.name,
        media_type="application/octet-stream",
        size_bytes=index_path.stat().st_size,
        sha256=sha256_file(index_path),
        storage_uri=f"file:///qualified-artifacts/{analysis.id}/{index_path.name}",
        metadata_json={"tool_execution_record_ids": result["tool_execution_record_ids"]},
    )
    db.add_all([vcf_artifact, index_artifact])
    db.commit()

    records = db.query(ToolExecutionRecord).filter(
        ToolExecutionRecord.analysis_id == analysis.id
    ).all()
    assert len(records) == len(result["tool_execution_record_ids"])
    assert all(record.status == "SUCCEEDED" for record in records)
    assert any(record.operation == "index" for record in records)
    assert any(record.operation == "sort" for record in records)
    assert all(
        artifact.metadata_json["tool_execution_record_ids"] == result["tool_execution_record_ids"]
        for artifact in (vcf_artifact, index_artifact)
    )
