from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from uuid import uuid4

import pytest

from backend.app.domain.container_tool_execution import ContainerResourceLimits, LinuxContainerToolExecutor
from backend.app.domain.execution_environments import ExecutionCapacity, ExecutionEnvironmentProfile
from backend.app.domain.tool_execution import (
    InputArtifact, OutputArtifact, ScientificResourceBinding, ToolExecutionError,
    ToolExecutionRequest, ToolIdentity, current_platform_id, sha256_file,
)


RUNTIME = os.environ.get("SIRALOOM_QUALIFICATION_RUNTIME", "").upper()
IMAGE_REFERENCE = os.environ.get("SIRALOOM_QUALIFICATION_IMAGE", "")
pytestmark = pytest.mark.skipif(
    not RUNTIME or not IMAGE_REFERENCE,
    reason="Requires a real Linux OCI runtime and an image pinned by repository digest.",
)


def _checked(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    if result.returncode:
        raise AssertionError(f"Qualification setup command failed: {command!r}: {result.stderr}")
    return result.stdout.strip()


def _build_context(tmp_path: Path):
    runtime = shutil.which(RUNTIME.casefold())
    assert runtime and Path(runtime).is_absolute()
    if RUNTIME == "DOCKER":
        version = _checked([runtime, "version", "--format", "{{.Server.Version}}"])
    elif RUNTIME == "PODMAN":
        version = _checked([runtime, "--version"])
    else:
        raise AssertionError(f"Unsupported qualification runtime {RUNTIME!r}")
    digest = IMAGE_REFERENCE.rsplit("@", 1)[-1]
    assert digest.startswith("sha256:") and len(digest) == 71
    organization_id = uuid4()
    environment = ExecutionEnvironmentProfile(
        environment_id=f"linux-{RUNTIME.casefold()}-qualification",
        profile_version="ci-1",
        owner_scope="LABORATORY",
        organization_id=organization_id,
        executor_kind="CONTAINER",
        platform=current_platform_id(),
        operating_system="linux",
        architecture=platform.machine(),
        kernel_release=platform.release(),
        runtime_kind=RUNTIME,
        runtime_version=version,
        runtime_image_digest=digest,
        scheduler="NONE",
        capacity=ExecutionCapacity(2, 6 * 1024**3, 20 * 1024**3, 1),
        workspace_root=str(tmp_path),
        storage_profile_ids=("ci-local-verified",),
        supported_tool_profile_ids=("bcftools-1.25-ci", "python-3.12-ci"),
        network_policy="OFFLINE",
        runtime_image_reference=IMAGE_REFERENCE,
        qualification_status="ENVIRONMENT_QUALIFIED",
    )
    limits = ContainerResourceLimits(
        cpu_cores=1, memory_bytes=512 * 1024**2, pids_limit=64,
        container_user=f"{os.getuid()}:{os.getgid()}",
    )
    executor = LinuxContainerToolExecutor(environment, limits, runtime_path=runtime)

    def executable_digest(path: str) -> str:
        output = _checked([
            runtime, "run", "--rm", "--pull=never", "--network=none",
            IMAGE_REFERENCE, "sha256sum", path,
        ])
        return output.split()[0]

    bcftools_digest = executable_digest("/opt/conda/bin/bcftools")
    python_digest = executable_digest("/usr/local/bin/python")
    environment = ExecutionEnvironmentProfile(
        **{
            **environment.__dict__,
            "tool_executable_sha256": (
                ("bcftools-1.25-ci", bcftools_digest),
                ("python-3.12-ci", python_digest),
            ),
        }
    )
    executor.environment = environment
    bcftools = ToolIdentity(
        tool_id="bcftools", version="1.25", profile_id="bcftools-1.25-ci",
        executable="/opt/conda/bin/bcftools", executable_sha256=bcftools_digest,
        platform=current_platform_id(), qualification_status="SOFTWARE_QUALIFIED",
        version_args=("--version",), version_output_contains="bcftools 1.25",
        supported_operations=("validate", "normalize", "convert"),
        runtime_image_digest=digest,
        runtime_path=("/opt/conda/bin", "/usr/local/bin", "/usr/bin", "/bin"),
    )
    python_tool = ToolIdentity(
        tool_id="python-runtime-probe", version="3.12", profile_id="python-3.12-ci",
        executable="/usr/local/bin/python", executable_sha256=python_digest,
        platform=current_platform_id(), qualification_status="SOFTWARE_QUALIFIED",
        version_args=("--version",), version_output_contains="Python 3.12",
        supported_operations=("validate", "probe", "timeout"),
        runtime_image_digest=digest,
        runtime_path=("/usr/local/bin", "/usr/bin", "/bin"),
    )
    return executor, environment, bcftools, python_tool


def _request(environment, workspace, argv, *, operation="validate", inputs=(), outputs=(), resources=(), timeout=60):
    return ToolExecutionRequest(
        execution_id=f"oci-qualification-{uuid4().hex}",
        organization_id=str(environment.organization_id),
        workflow_id="container-runtime-qualification",
        operation=operation, argv=tuple(argv), workspace=str(workspace),
        inputs=tuple(inputs), outputs=tuple(outputs), resources=tuple(resources),
        timeout_seconds=timeout, max_output_bytes=4096,
    )


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace.chmod(0o700)
    return workspace


def _container_name(provenance) -> str:
    command = list(provenance.argv)
    return command[command.index("--name") + 1]


def _assert_container_removed(executor, name: str) -> None:
    runtime = executor._runtime()
    result = subprocess.run(
        [runtime, "ps", "--all", "--filter", f"name={name}", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert name not in result.stdout.splitlines()


def test_real_bcftools_execution_and_output_provenance(tmp_path):
    executor, environment, bcftools, _ = _build_context(tmp_path)
    workspace = _workspace(tmp_path)
    source = tmp_path / "sample.vcf"
    source.write_text(
        "##fileformat=VCFv4.2\n##contig=<ID=chr1,length=1000>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t10\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    output = workspace / "normalized.vcf"
    request = _request(
        environment, workspace, ("view", "-Ov", "-o", str(output), str(source)),
        operation="convert",
        inputs=(InputArtifact("sample-vcf", str(source), sha256_file(source)),),
        outputs=(OutputArtifact("bcftools-output", str(output)),),
    )
    result = executor.execute(bcftools, request)
    assert result.provenance.exit_code == 0
    assert result.provenance.runtime_image_digest == environment.runtime_image_digest
    assert result.provenance.output_sha256 == (
        {"name": "bcftools-output", "sha256": sha256_file(output)},
    )
    assert "chr1\t10" in output.read_text(encoding="utf-8")
    assert result.provenance.duration_seconds > 0


def test_real_input_and_resource_mounts_are_read_only_but_workspace_is_writable(tmp_path):
    executor, environment, _, python_tool = _build_context(tmp_path)
    workspace = _workspace(tmp_path)
    input_path = tmp_path / "input.txt"
    input_path.write_text("immutable-input", encoding="utf-8")
    resource_path = tmp_path / "reference.fa"
    resource_path.write_text(">chr1\nACGT\n", encoding="utf-8")
    output = workspace / "mount-check.txt"
    script = """import pathlib, sys
states = []
for value in sys.argv[1:3]:
    try:
        pathlib.Path(value).write_text("MUTATED")
        states.append(False)
    except OSError:
        states.append(True)
pathlib.Path(sys.argv[3]).write_text("readonly" if all(states) else "writable")
"""
    request = _request(
        environment, workspace,
        ("-c", script, str(input_path), str(resource_path), str(output)),
        inputs=(InputArtifact("readonly-input", str(input_path), sha256_file(input_path)),),
        outputs=(OutputArtifact("mount-check", str(output)),),
        resources=(ScientificResourceBinding(
            "reference-fasta", "fixture-v1", sha256_file(resource_path), path=str(resource_path)
        ),),
    )
    result = executor.execute(python_tool, request)
    assert result.provenance.exit_code == 0
    assert output.read_text(encoding="utf-8") == "readonly"
    assert input_path.read_text(encoding="utf-8") == "immutable-input"
    assert resource_path.read_text(encoding="utf-8") == ">chr1\nACGT\n"


def test_real_cgroup_cpu_memory_and_pid_limits_are_applied(tmp_path):
    executor, environment, _, python_tool = _build_context(tmp_path)
    workspace = _workspace(tmp_path)
    output = workspace / "cgroup.json"
    script = """import json, pathlib, sys
root = pathlib.Path("/sys/fs/cgroup")
data = {key: (root / key).read_text().strip() for key in ("cpu.max", "memory.max", "pids.max")}
pathlib.Path(sys.argv[1]).write_text(json.dumps(data))
"""
    request = _request(
        environment, workspace, ("-c", script, str(output)),
        operation="probe", outputs=(OutputArtifact("cgroup-limits", str(output)),),
    )
    result = executor.execute(python_tool, request)
    observed = json.loads(output.read_text(encoding="utf-8"))
    quota, period = (int(value) for value in observed["cpu.max"].split())
    assert quota / period <= 1.0
    assert int(observed["memory.max"]) == executor.limits.memory_bytes
    assert int(observed["pids.max"]) == executor.limits.pids_limit
    assert result.provenance.exit_code == 0


def test_real_timeout_kills_and_removes_container(tmp_path):
    executor, environment, _, python_tool = _build_context(tmp_path)
    workspace = _workspace(tmp_path)
    request = _request(
        environment, workspace, ("-c", "import time; time.sleep(60)"),
        operation="timeout", timeout=2,
    )
    with pytest.raises(ToolExecutionError, match="timeout") as caught:
        executor.execute(python_tool, request)
    assert caught.value.provenance is not None
    _assert_container_removed(executor, _container_name(caught.value.provenance))


def test_real_tool_failure_returns_provenance_and_removes_container(tmp_path):
    executor, environment, bcftools, _ = _build_context(tmp_path)
    workspace = _workspace(tmp_path)
    request = _request(
        environment, workspace, ("--this-option-does-not-exist",),
        operation="validate",
    )
    with pytest.raises(ToolExecutionError) as caught:
        executor.execute(bcftools, request)
    assert caught.value.provenance is not None
    assert caught.value.provenance.exit_code != 0
    _assert_container_removed(executor, _container_name(caught.value.provenance))
