from __future__ import annotations

from uuid import uuid4
import hashlib
import json
import math
from pathlib import Path
import subprocess

import backend.app.domain.container_tool_execution as container_module

import pytest

from backend.app.domain.container_tool_execution import (
    ContainerResourceLimits,
    EnvironmentAwareToolExecutor,
    LinuxContainerToolExecutor,
)
from backend.app.domain.execution_environments import ExecutionCapacity, ExecutionEnvironmentError, ExecutionEnvironmentProfile
from backend.app.domain.tool_execution import (
    InputArtifact,
    OutputArtifact,
    ScientificResourceBinding,
    ToolExecutionContractError,
    ToolExecutionRequest,
    ToolIdentity,
)


def _environment(*, runtime_kind: str = "DOCKER", executor_kind: str = "CONTAINER"):
    digest = "sha256:" + "a" * 64
    return ExecutionEnvironmentProfile(
        environment_id="linux-container-test",
        profile_version="1",
        owner_scope="LABORATORY",
        organization_id=uuid4(),
        executor_kind=executor_kind,
        platform="linux-64",
        operating_system="linux",
        architecture="x86_64",
        kernel_release="6.8.0",
        runtime_kind=runtime_kind,
        runtime_version="27.0",
        runtime_image_digest=digest,
        scheduler="NONE",
        capacity=ExecutionCapacity(8, 16 * 1024**3, 50 * 1024**3, 2),
        workspace_root="/var/lib/siraloom/workspaces",
        storage_profile_ids=("local-verified",),
        supported_tool_profile_ids=("bcftools-pinned",),
        network_policy="OFFLINE",
        runtime_image_reference="registry.example.org/siraloom/bcftools@" + digest,
        tool_executable_sha256=(("bcftools-pinned", "b" * 64),),
        qualification_status="ENVIRONMENT_QUALIFIED",
    )


def _tool():
    return ToolIdentity(
        tool_id="bcftools",
        version="1.25",
        profile_id="bcftools-pinned",
        executable="/usr/bin/bcftools",
        executable_sha256="b" * 64,
        platform="linux-64",
        qualification_status="SOFTWARE_QUALIFIED",
        version_args=("--version",),
        version_output_contains="bcftools 1.25",
        runtime_image_digest="sha256:" + "a" * 64,
    )


def test_container_adapter_requires_explicit_job_resource_limits():
    executor = EnvironmentAwareToolExecutor(_environment())
    with pytest.raises(ToolExecutionContractError, match="explicit per-job"):
        executor.execute(_tool(), None)


def test_container_limits_cannot_exceed_environment_capacity():
    environment = _environment()
    limits = ContainerResourceLimits(
        cpu_cores=9,
        memory_bytes=1024**3,
        pids_limit=256,
        container_user="1000:1000",
    )
    with pytest.raises(ToolExecutionContractError, match="CPU limit"):
        limits.validate(environment)


def test_container_runtime_must_be_installed_and_explicit():
    environment = _environment()
    limits = ContainerResourceLimits(2, 4 * 1024**3, 256, "1000:1000")
    executor = LinuxContainerToolExecutor(
        environment,
        limits,
        runtime_path="/definitely/missing/docker",
    )
    with pytest.raises(ToolExecutionContractError, match="runtime path"):
        executor._runtime()


def test_environment_aware_executor_never_falls_back_for_remote_agent():
    environment = _environment(runtime_kind="DOCKER", executor_kind="REMOTE_AGENT")
    executor = EnvironmentAwareToolExecutor(environment)
    with pytest.raises(ExecutionEnvironmentError, match="not implemented"):
        executor.execute(_tool(), None)



def test_container_tool_path_is_not_resolved_against_host_filesystem():
    tool = ToolIdentity(
        **{
            **_tool().__dict__,
            "runtime_path": ("/opt/siraloom/bin",),
        }
    )
    tool.validate()



def test_container_limits_reject_nan_cpu_value():
    environment = _environment()
    limits = ContainerResourceLimits(
        cpu_cores=math.nan,
        memory_bytes=1024**3,
        pids_limit=256,
        container_user="1000:1000",
    )
    with pytest.raises(ToolExecutionContractError, match="CPU limit"):
        limits.validate(environment)



def test_docker_executor_builds_isolated_command_and_returns_common_provenance(tmp_path, monkeypatch):
    environment = _environment()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    input_path = tmp_path / "sample.vcf"
    input_path.write_text("##fileformat=VCFv4.2\n", encoding="utf-8")
    resource_path = tmp_path / "reference.fa"
    resource_path.write_text(">1\nACGT\n", encoding="utf-8")
    output_path = workspace / "result.txt"
    input_sha = hashlib.sha256(input_path.read_bytes()).hexdigest()
    resource_sha = hashlib.sha256(resource_path.read_bytes()).hexdigest()

    runtime = tmp_path / "docker"
    runtime.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runtime.chmod(0o755)
    image_ref = environment.runtime_image_reference
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["version", "--format"]:
            stdout = "27.0"
        elif command[1:3] == ["info", "--format"]:
            stdout = "2"
        elif command[1:3] == ["image", "inspect"]:
            stdout = json.dumps([image_ref])
        elif "sha256sum" in command:
            stdout = ("b" * 64) + " /usr/bin/bcftools"
        elif command[-1:] == ["--version"]:
            stdout = "bcftools 1.25"
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    executed_commands = []

    class FakeProcess:
        pid = 12345
        returncode = 0

        def __init__(self, command, *, stdout, stderr, **kwargs):
            self.command = command
            executed_commands.append(command)
            self.stdout = stdout
            self.stderr = stderr
            output_path.write_text("validated\n", encoding="utf-8")
            stdout.write(b"container stdout\n")
            stderr.write(b"")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(container_module.subprocess, "Popen", FakeProcess)
    request = ToolExecutionRequest(
        execution_id="container-test-1",
        organization_id=str(environment.organization_id),
        workflow_id="germline-intake",
        operation="validate",
        argv=("--input", str(input_path), "--reference", str(resource_path), "--output", str(output_path)),
        workspace=str(workspace),
        inputs=(InputArtifact("sample-vcf", str(input_path), input_sha),),
        outputs=(OutputArtifact("validated", str(output_path)),),
        resources=(ScientificResourceBinding("reference-fasta", "GRCh38-v1", resource_sha, path=str(resource_path)),),
        timeout_seconds=60,
        max_output_bytes=1024,
    )
    executor = LinuxContainerToolExecutor(
        environment,
        ContainerResourceLimits(2, 4 * 1024**3, 256, "1000:1000"),
        runner=runner,
        runtime_path=str(runtime),
    )

    result = executor.execute(_tool(), request)

    assert result.provenance.runtime_image_digest == environment.runtime_image_digest
    assert result.provenance.exit_code == 0
    assert result.provenance.output_sha256[0]["name"] == "validated"
    assert result.stdout == "container stdout\\n"
    assert len(executed_commands) == 1
    command = executed_commands[0]
    assert "--pull=never" in command
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cpus" in command and "--memory" in command and "--memory-swap" in command
    assert "--pids-limit" in command and "--user" in command
    mounts = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "--mount"]
    assert any("dst=/workspace" in mount and "readonly" not in mount for mount in mounts)
    assert any("dst=/inputs/sample-vcf" in mount and "readonly" in mount for mount in mounts)
    assert any("dst=/resources/reference-fasta" in mount and "readonly" in mount for mount in mounts)
    assert any(call[1:3] == ["image", "inspect"] for call in calls)
