from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from uuid import uuid4

from backend.app.config import settings
from backend.app.domain.execution_environments import (
    ExecutionCapacity,
    ExecutionEnvironmentProfile,
    ExecutionJobLimits,
)
from backend.app.domain.tool_execution import current_platform_id
from backend.app.infrastructure.db.models import ExecutionEnvironmentRegistration


def assign_qualified_container_environment(db, case, *, created_by):
    """Attach a test-only, digest-pinned OCI profile to an integration case.

    CI builds and pushes the exact backend/BCFtools image to its ephemeral local
    registry. This fixture verifies the image's executable bytes and creates
    the immutable registration snapshot consumed by the production resolver.
    It does not represent a customer laboratory qualification workflow.
    """
    image_reference = os.environ.get("SIRALOOM_QUALIFICATION_IMAGE", "")
    if "@sha256:" not in image_reference:
        raise RuntimeError("PostgreSQL execution tests require a digest-pinned SIRALOOM_QUALIFICATION_IMAGE.")
    runtime_name = os.environ.get("SIRALOOM_QUALIFICATION_RUNTIME", "DOCKER").upper()
    runtime = shutil.which(runtime_name.casefold())
    if not runtime:
        raise RuntimeError(f"Qualified OCI test runtime {runtime_name} is unavailable.")
    if runtime_name != "DOCKER":
        raise RuntimeError("This CI fixture currently supports only Docker.")
    runtime_version = subprocess.run(
        [runtime, "version", "--format", "{{.Server.Version}}"],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip()
    image_digest = image_reference.rsplit("@", 1)[1]
    executable = settings.bcftools_executable
    if not executable.startswith("/"):
        raise RuntimeError("BCFTOOLS_EXECUTABLE must be the absolute in-image path.")
    digest_result = subprocess.run(
        [runtime, "run", "--rm", "--pull=never", "--network=none",
         image_reference, "sha256sum", executable],
        capture_output=True, text=True, check=True, timeout=30,
    )
    executable_digest = digest_result.stdout.split()[0]
    profile_id = settings.bcftools_profile_id
    profile = ExecutionEnvironmentProfile(
        environment_id=f"ci-docker-{uuid4().hex}",
        profile_version="ci-1",
        owner_scope="LABORATORY",
        organization_id=case.organization_id,
        executor_kind="CONTAINER",
        platform=current_platform_id(),
        operating_system="linux",
        architecture=platform.machine(),
        kernel_release=platform.release(),
        runtime_kind="DOCKER",
        runtime_version=runtime_version,
        runtime_image_digest=image_digest,
        runtime_image_reference=image_reference,
        scheduler="NONE",
        capacity=ExecutionCapacity(
            cpu_cores=4,
            memory_bytes=8 * 1024**3,
            scratch_bytes=20 * 1024**3,
            max_concurrency=2,
        ),
        job_limits=ExecutionJobLimits(
            cpu_cores=1,
            memory_bytes=2 * 1024**3,
            pids_limit=256,
            container_user="10001:10001",
        ),
        workspace_root="/tmp/siraloom-ci-execution",
        storage_profile_ids=("ci-local-artifact-store",),
        supported_tool_profile_ids=(profile_id,),
        tool_executable_sha256=((profile_id, executable_digest),),
        network_policy="OFFLINE",
        qualification_status="ENVIRONMENT_QUALIFIED",
    )
    snapshot = profile.snapshot()
    fingerprint = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    registration = ExecutionEnvironmentRegistration(
        id=uuid4(),
        organization_id=case.organization_id,
        owner_scope=profile.owner_scope,
        environment_id=profile.environment_id,
        profile_version=profile.profile_version,
        profile_fingerprint=fingerprint,
        profile_json=snapshot,
        qualification_status="ENVIRONMENT_QUALIFIED",
        created_by=created_by,
    )
    db.add(registration)
    db.flush()
    case.execution_environment_registration_id = registration.id
    db.flush()
    return registration
