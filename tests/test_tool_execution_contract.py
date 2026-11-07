from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from backend.app.domain.tool_execution import (
    InputArtifact,
    LocalProcessToolExecutor,
    OutputArtifact,
    ScientificResourceBinding,
    ToolExecutionContractError,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolIdentity,
    current_platform_id,
    sha256_resource_path,
)


def _profile() -> ToolIdentity:
    executable = Path(sys.executable).resolve(strict=True)
    return ToolIdentity(
        tool_id="python-test-tool",
        version=sys.version.split()[0],
        profile_id="python-test-profile",
        executable=str(executable),
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        platform="linux-64",
        qualification_status="SOFTWARE_QUALIFIED",
        version_args=("--version",),
        version_output_contains=sys.version.split()[0],
    )


def test_local_executor_attests_tool_and_records_input_resource_output_provenance(tmp_path: Path) -> None:
    profile = _profile()
    source = tmp_path / "input.txt"
    source.write_text("governed input", encoding="utf-8")
    output = tmp_path / "result.txt"
    reference_resource = tmp_path / "reference.fa"
    reference_resource.write_text(">1\\nACGT\\n", encoding="utf-8")
    request = ToolExecutionRequest(
        execution_id="execution-001",
        organization_id="lab-001",
        workflow_id="germline-annotation-v1",
        operation="annotate",
        argv=(
            "-c",
            "from pathlib import Path; Path('result.txt').write_text('annotated', encoding='utf-8')",
        ),
        workspace=str(tmp_path),
        inputs=(InputArtifact("source", str(source), hashlib.sha256(source.read_bytes()).hexdigest()),),
        outputs=(OutputArtifact("annotation", str(output)),),
        resources=(ScientificResourceBinding(
            resource_id="reference-grch38",
            version="GRCh38",
            sha256=hashlib.sha256(reference_resource.read_bytes()).hexdigest(),
            assembly="GRCh38",
            path=str(reference_resource),
        ),),
    )

    result = LocalProcessToolExecutor().execute(profile, request)

    assert output.read_text(encoding="utf-8") == "annotated"
    assert result.provenance.tool_id == "python-test-tool"
    assert result.provenance.profile_id == "python-test-profile"
    assert result.provenance.organization_id == "lab-001"
    assert result.provenance.input_sha256 == ({"name": "source", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},)
    assert result.provenance.output_sha256 == ({"name": "annotation", "sha256": hashlib.sha256(b"annotated").hexdigest()},)
    assert result.provenance.resource_bindings[0]["assembly"] == "GRCh38"
    assert result.provenance.exit_code == 0
    assert result.provenance.platform == current_platform_id()
    assert result.provenance.runtime_image_digest is None


def test_executor_rejects_executable_digest_mismatch(tmp_path: Path) -> None:
    profile = _profile()
    profile = ToolIdentity(
        **{**profile.__dict__, "executable_sha256": "0" * 64}
    )
    request = ToolExecutionRequest(
        execution_id="execution-002",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=("--version",),
        workspace=str(tmp_path),
    )

    with pytest.raises(ToolExecutionContractError, match="SHA-256"):
        LocalProcessToolExecutor().execute(profile, request)


def test_request_rejects_input_digest_mismatch_before_execution(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("actual", encoding="utf-8")
    request = ToolExecutionRequest(
        execution_id="execution-003",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=("--version",),
        workspace=str(tmp_path),
        inputs=(InputArtifact("source", str(source), "f" * 64),),
    )

    with pytest.raises(ToolExecutionContractError, match="SHA-256 mismatch"):
        request.validate(_profile())


def test_request_rejects_output_outside_execution_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-result.txt"
    request = ToolExecutionRequest(
        execution_id="execution-004",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=("--version",),
        workspace=str(tmp_path),
        outputs=(OutputArtifact("result", str(outside)),),
    )

    with pytest.raises(ToolExecutionContractError, match="inside the execution workspace"):
        request.validate(_profile())


def test_nonzero_tool_exit_is_not_reported_as_success(tmp_path: Path) -> None:
    profile = _profile()
    request = ToolExecutionRequest(
        execution_id="execution-005",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=("-c", "raise SystemExit(7)"),
        workspace=str(tmp_path),
    )

    with pytest.raises(ToolExecutionError, match="exited with status 7") as exc:
        LocalProcessToolExecutor().execute(profile, request)
    assert exc.value.provenance is not None
    assert exc.value.provenance.exit_code == 7
    assert exc.value.provenance.stdout_sha256 == hashlib.sha256(b"").hexdigest()



def test_request_rejects_profile_operation_not_declared(tmp_path: Path) -> None:
    profile = _profile()
    profile = ToolIdentity(
        **{**profile.__dict__, "supported_operations": ("annotate",)}
    )
    request = ToolExecutionRequest(
        execution_id="execution-006",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="call",
        argv=("--version",),
        workspace=str(tmp_path),
    )

    with pytest.raises(ToolExecutionContractError, match="does not support operation"):
        request.validate(profile)


def test_request_rejects_protected_environment_overrides(tmp_path: Path) -> None:
    request = ToolExecutionRequest(
        execution_id="execution-007",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=("--version",),
        workspace=str(tmp_path),
        environment={"LD_PRELOAD": "/tmp/untrusted.so"},
    )

    with pytest.raises(ToolExecutionContractError, match="protected variable"):
        request.validate(_profile())



def test_executor_bounds_returned_logs_but_hashes_complete_output(tmp_path: Path) -> None:
    profile = _profile()
    payload = "x" * 5000
    request = ToolExecutionRequest(
        execution_id="execution-008",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=("-c", f"print({payload!r}, end='')"),
        workspace=str(tmp_path),
        max_output_bytes=1024,
    )

    result = LocalProcessToolExecutor().execute(profile, request)

    expected = payload.encode("utf-8")
    assert result.stdout.startswith("[... earlier process output truncated ...]\\n")
    assert len(result.stdout.encode("utf-8")) < 1100
    assert result.provenance.stdout_sha256 == hashlib.sha256(expected).hexdigest()
    assert result.provenance.stderr_sha256 == hashlib.sha256(b"").hexdigest()


def test_request_rejects_unbounded_or_too_small_output_capture_limit(tmp_path: Path) -> None:
    request = ToolExecutionRequest(
        execution_id="execution-009",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=("--version",),
        workspace=str(tmp_path),
        max_output_bytes=100_000_000,
    )

    with pytest.raises(ToolExecutionContractError, match="Captured process output limit"):
        request.validate(_profile())


def test_resource_binding_rejects_digest_that_does_not_match_actual_bytes(tmp_path: Path) -> None:
    resource = tmp_path / "reference.fa"
    resource.write_text(">1\\nACGT\\n", encoding="utf-8")
    binding = ScientificResourceBinding(
        resource_id="reference-grch38",
        version="GRCh38",
        sha256="0" * 64,
        assembly="GRCh38",
        path=str(resource),
    )
    with pytest.raises(ToolExecutionContractError, match="does not match its governed bytes"):
        binding.validate()


def test_directory_resource_digest_covers_complete_file_set(tmp_path: Path) -> None:
    resource = tmp_path / "vep-cache"
    resource.mkdir()
    (resource / "a.txt").write_text("alpha", encoding="utf-8")
    (resource / "nested").mkdir()
    (resource / "nested" / "b.txt").write_text("beta", encoding="utf-8")

    first_digest = sha256_resource_path(resource)
    binding = ScientificResourceBinding(
        resource_id="vep-cache",
        version="115",
        sha256=first_digest,
        assembly="GRCh38",
        path=str(resource),
    )
    binding.validate()

    (resource / "nested" / "b.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ToolExecutionContractError, match="does not match its governed bytes"):
        binding.validate()


def test_resource_directory_rejects_symlink_entries(tmp_path: Path) -> None:
    resource = tmp_path / "resource"
    resource.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    (resource / "linked.txt").symlink_to(target)

    with pytest.raises(ToolExecutionContractError, match="symlinks"):
        sha256_resource_path(resource)


def test_tool_profile_rejects_worker_platform_mismatch() -> None:
    profile = _profile()
    wrong_platform = "linux-aarch64" if current_platform_id() != "linux-aarch64" else "linux-64"
    mismatched = ToolIdentity(**{**profile.__dict__, "platform": wrong_platform})

    with pytest.raises(ToolExecutionContractError, match="does not match worker platform"):
        mismatched.validate()


def test_timeout_failure_retains_execution_provenance(tmp_path: Path) -> None:
    profile = _profile()
    request = ToolExecutionRequest(
        execution_id="execution-timeout",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=("-c", "import time; time.sleep(2)"),
        workspace=str(tmp_path),
        timeout_seconds=1,
    )

    with pytest.raises(ToolExecutionError, match="exceeded its 1s timeout") as exc:
        LocalProcessToolExecutor().execute(profile, request)

    assert exc.value.retryable is True
    assert exc.value.provenance is not None
    assert exc.value.provenance.exit_code in {-9, 137}


def test_approved_profile_environment_is_used_and_fingerprinted(tmp_path: Path) -> None:
    profile = _profile()
    profile = ToolIdentity(**{
        **profile.__dict__,
        "runtime_environment": {"SIRALOOM_EXECUTOR_TEST": "approved"},
    })
    output = tmp_path / "environment.txt"
    request = ToolExecutionRequest(
        execution_id="execution-profile-environment",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=(
            "-c",
            "import os; from pathlib import Path; Path('environment.txt').write_text(os.environ['SIRALOOM_EXECUTOR_TEST'], encoding='utf-8')",
        ),
        workspace=str(tmp_path),
        outputs=(OutputArtifact("environment", str(output)),),
    )

    result = LocalProcessToolExecutor().execute(profile, request)

    assert output.read_text(encoding="utf-8") == "approved"
    assert len(result.provenance.environment_sha256) == 64


def test_request_cannot_override_profile_pinned_environment(tmp_path: Path) -> None:
    profile = _profile()
    profile = ToolIdentity(**{
        **profile.__dict__,
        "runtime_environment": {"PERL5LIB": "/opt/vep/modules"},
    })
    request = ToolExecutionRequest(
        execution_id="execution-profile-environment-override",
        organization_id="lab-001",
        workflow_id="workflow-v1",
        operation="validate",
        argv=("--version",),
        workspace=str(tmp_path),
        environment={"PERL5LIB": "/tmp/untrusted"},
    )

    with pytest.raises(ToolExecutionContractError, match="cannot override approved tool-profile"):
        request.validate(profile)
