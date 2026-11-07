"""Versioned, tool-neutral contracts for scientific executable invocations.

This module is deliberately independent of BCFtools, VEP, Celery and resource
provider implementations. Tool-specific adapters construct requests; an
executor enforces the common runtime and provenance boundary.
"""
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol


class ToolExecutionContractError(ValueError):
    """A scientific tool profile or execution request violates its contract."""


class ToolExecutionError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, provenance: "ToolExecutionProvenance | None" = None):
        super().__init__(message)
        self.retryable = retryable
        self.provenance = provenance


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ToolIdentity:
    tool_id: str
    version: str
    profile_id: str
    executable: str
    executable_sha256: str
    platform: str
    qualification_status: str
    version_args: tuple[str, ...] = ("--version",)
    version_output_contains: str = ""
    supported_operations: tuple[str, ...] = ("validate", "normalize", "annotate", "align", "call", "index", "convert", "benchmark")

    def validate(self) -> None:
        required = {
            "tool_id": self.tool_id,
            "version": self.version,
            "profile_id": self.profile_id,
            "executable": self.executable,
            "platform": self.platform,
        }
        missing = [key for key, value in required.items() if not str(value).strip()]
        if missing:
            raise ToolExecutionContractError("Tool identity is missing: " + ", ".join(missing))
        if not Path(self.executable).is_absolute():
            raise ToolExecutionContractError("Tool executable must be an absolute path.")
        if len(self.executable_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.executable_sha256.lower()):
            raise ToolExecutionContractError("Tool executable SHA-256 must be a 64-character hex digest.")
        if self.qualification_status != "SOFTWARE_QUALIFIED":
            raise ToolExecutionContractError("Only software-qualified tool profiles may execute.")
        if not self.version_args:
            raise ToolExecutionContractError("Tool version attestation arguments are required.")
        if not self.version_output_contains:
            raise ToolExecutionContractError("Expected version attestation text is required.")
        if not self.supported_operations or any(not item.strip() for item in self.supported_operations):
            raise ToolExecutionContractError("Tool profile must declare supported operations.")


@dataclass(frozen=True)
class ScientificResourceBinding:
    resource_id: str
    version: str
    sha256: str
    assembly: str | None = None

    def validate(self) -> None:
        if not self.resource_id.strip() or not self.version.strip():
            raise ToolExecutionContractError("Scientific resource identity and version are required.")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256.lower()):
            raise ToolExecutionContractError("Scientific resource SHA-256 must be a 64-character hex digest.")


@dataclass(frozen=True)
class InputArtifact:
    name: str
    path: str
    sha256: str


@dataclass(frozen=True)
class OutputArtifact:
    name: str
    path: str


@dataclass(frozen=True)
class ToolExecutionRequest:
    execution_id: str
    organization_id: str
    workflow_id: str
    operation: str
    argv: tuple[str, ...]
    workspace: str
    inputs: tuple[InputArtifact, ...] = ()
    outputs: tuple[OutputArtifact, ...] = ()
    resources: tuple[ScientificResourceBinding, ...] = ()
    timeout_seconds: int = 1800
    environment: Mapping[str, str] = field(default_factory=dict)

    def validate(self, profile: ToolIdentity) -> None:
        if not all((self.execution_id.strip(), self.organization_id.strip(), self.workflow_id.strip(), self.operation.strip())):
            raise ToolExecutionContractError("Execution, organization, workflow and operation identities are required.")
        if self.operation not in profile.supported_operations:
            raise ToolExecutionContractError(f"Tool profile {profile.profile_id!r} does not support operation {self.operation!r}.")
        if not self.argv or any("\x00" in str(arg) for arg in self.argv):
            raise ToolExecutionContractError("Execution argv must be non-empty and contain no NUL bytes.")
        if not 1 <= int(self.timeout_seconds) <= 86400:
            raise ToolExecutionContractError("Execution timeout must be between 1 and 86400 seconds.")
        workspace = Path(self.workspace)
        if not workspace.is_absolute() or not workspace.is_dir() or workspace.is_symlink():
            raise ToolExecutionContractError("Execution workspace must be an existing absolute non-symlink directory.")
        input_names: set[str] = set()
        for item in self.inputs:
            if not item.name or item.name in input_names:
                raise ToolExecutionContractError("Input artifact names must be present and unique.")
            input_names.add(item.name)
            path = Path(item.path)
            if not path.is_absolute() or not path.is_file() or path.is_symlink():
                raise ToolExecutionContractError(f"Input artifact {item.name!r} must be an existing regular file.")
            if sha256_file(path) != item.sha256:
                raise ToolExecutionContractError(f"Input artifact {item.name!r} SHA-256 mismatch.")
        output_names: set[str] = set()
        output_paths: set[Path] = set()
        root = workspace.resolve(strict=True)
        for item in self.outputs:
            if not item.name or item.name in output_names:
                raise ToolExecutionContractError("Output artifact names must be present and unique.")
            output_names.add(item.name)
            path = Path(item.path)
            if not path.is_absolute():
                raise ToolExecutionContractError(f"Output artifact {item.name!r} path must be absolute.")
            if path.is_symlink():
                raise ToolExecutionContractError(f"Output artifact {item.name!r} cannot be a symlink.")
            parent = path.parent.resolve(strict=True)
            if not parent.is_relative_to(root):
                raise ToolExecutionContractError(f"Output artifact {item.name!r} must be inside the execution workspace.")
            if path in output_paths:
                raise ToolExecutionContractError("Output artifact paths must be unique.")
            output_paths.add(path)
        for resource in self.resources:
            resource.validate()
        if any(not str(key).replace("_", "").isalnum() for key in self.environment):
            raise ToolExecutionContractError("Environment variable names must be simple identifiers.")
        protected_environment = {
            "PATH", "HOME", "IFS", "PYTHONPATH", "PYTHONHOME",
            "LD_PRELOAD", "LD_LIBRARY_PATH", "BASH_ENV", "ENV",
        }
        overridden = sorted(
            str(key) for key in self.environment
            if str(key).upper() in protected_environment
            or str(key).upper().startswith("LD_")
        )
        if overridden:
            raise ToolExecutionContractError(
                "Execution request cannot override protected variable(s): "
                + ", ".join(overridden)
            )
        if any("\x00" in str(value) for value in self.environment.values()):
            raise ToolExecutionContractError("Environment values must not contain NUL bytes.")


@dataclass(frozen=True)
class ToolExecutionProvenance:
    execution_id: str
    organization_id: str
    workflow_id: str
    operation: str
    tool_id: str
    tool_version: str
    profile_id: str
    executable_sha256: str
    resource_bindings: tuple[dict[str, str | None], ...]
    input_sha256: tuple[dict[str, str], ...]
    output_sha256: tuple[dict[str, str], ...]
    argv: tuple[str, ...]
    exit_code: int
    started_at: str
    completed_at: str
    duration_seconds: float
    stdout_sha256: str
    stderr_sha256: str


@dataclass(frozen=True)
class ToolExecutionResult:
    provenance: ToolExecutionProvenance
    stdout: str
    stderr: str


class ToolExecutor(Protocol):
    def execute(self, profile: ToolIdentity, request: ToolExecutionRequest) -> ToolExecutionResult:
        """Execute one governed request and return immutable provenance."""


class LocalProcessToolExecutor:
    """Execute a pinned local binary without a shell, with bounded lifetime."""

    def execute(self, profile: ToolIdentity, request: ToolExecutionRequest) -> ToolExecutionResult:
        profile.validate()
        request.validate(profile)
        configured_executable = Path(profile.executable)
        if configured_executable.is_symlink():
            raise ToolExecutionContractError("Configured tool executable cannot be a symlink.")
        executable = configured_executable.resolve(strict=True)
        if not executable.is_file():
            raise ToolExecutionContractError("Configured tool executable is not a regular file.")
        executable_digest = sha256_file(executable)
        if executable_digest != profile.executable_sha256.lower():
            raise ToolExecutionContractError("Tool executable SHA-256 does not match the approved profile.")

        version_check = subprocess.run(
            [str(executable), *profile.version_args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
        version_text = (version_check.stdout + "\n" + version_check.stderr).strip()
        if version_check.returncode != 0 or profile.version_output_contains not in version_text:
            raise ToolExecutionContractError("Runtime executable version does not match the approved tool profile.")

        workspace = Path(request.workspace).resolve(strict=True)
        env = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
        env.update({str(key): str(value) for key, value in request.environment.items()})
        command = [str(executable), *request.argv]
        started = datetime.now(timezone.utc)
        monotonic_start = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=request.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise ToolExecutionError(
                f"{profile.tool_id} execution exceeded its {request.timeout_seconds}s timeout.",
                retryable=True,
            ) from exc
        completed = datetime.now(timezone.utc)
        duration = time.monotonic() - monotonic_start
        if process.returncode != 0:
            raise ToolExecutionError(
                f"{profile.tool_id} exited with status {process.returncode}: {(stderr or stdout)[-2000:]}",
                retryable=process.returncode in {137, 143},
            )

        output_digests: list[dict[str, str]] = []
        for item in request.outputs:
            path = Path(item.path)
            if not path.is_file() or path.is_symlink():
                raise ToolExecutionError(f"Expected output artifact {item.name!r} was not produced.")
            output_digests.append({"name": item.name, "sha256": sha256_file(path)})
        provenance = ToolExecutionProvenance(
            execution_id=request.execution_id,
            organization_id=request.organization_id,
            workflow_id=request.workflow_id,
            operation=request.operation,
            tool_id=profile.tool_id,
            tool_version=profile.version,
            profile_id=profile.profile_id,
            executable_sha256=executable_digest,
            resource_bindings=tuple({
                "resource_id": item.resource_id,
                "version": item.version,
                "sha256": item.sha256,
                "assembly": item.assembly,
            } for item in request.resources),
            input_sha256=tuple({"name": item.name, "sha256": item.sha256} for item in request.inputs),
            output_sha256=tuple(output_digests),
            argv=tuple(command),
            exit_code=process.returncode,
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            duration_seconds=duration,
            stdout_sha256=hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        )
        return ToolExecutionResult(provenance=provenance, stdout=stdout, stderr=stderr)
