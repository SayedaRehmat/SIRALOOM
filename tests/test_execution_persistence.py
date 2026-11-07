from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

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
from backend.app.domain.tool_execution import ToolIdentity
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
