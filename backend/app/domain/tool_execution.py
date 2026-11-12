"""Versioned, tool-neutral contracts for scientific executable invocations.

This module is deliberately independent of BCFtools, VEP, Celery and resource
provider implementations. Tool-specific adapters construct requests; an
executor enforces the common runtime and provenance boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform as runtime_platform
import re
import signal
import stat
import subprocess
import tempfile
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


def _contains_symlink_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def sha256_resource_path(path: Path) -> str:
    """Hash a governed file or a directory's complete deterministic file set."""
    if not path.is_absolute() or _contains_symlink_component(path):
        raise ToolExecutionContractError(
            "Scientific resource path must be absolute and contain no symlink components."
        )
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise ToolExecutionContractError(
            "Scientific resource path must resolve to a regular file or directory."
        )

    entries: list[dict[str, object]] = []
    try:
        children = sorted(
            path.rglob("*"),
            key=lambda item: item.relative_to(path).as_posix(),
        )
        for child in children:
            if child.is_symlink():
                raise ToolExecutionContractError(
                    "Scientific resource directories must not contain symlinks."
                )
            mode = child.stat(follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ToolExecutionContractError(
                    "Scientific resource directories may contain only regular files and directories."
                )
            entries.append({
                "path": child.relative_to(path).as_posix(),
                "size_bytes": child.stat().st_size,
                "sha256": sha256_file(child),
            })
    except OSError as exc:
        raise ToolExecutionContractError(
            "Scientific resource could not be read for byte-level verification."
        ) from exc
    if not entries:
        raise ToolExecutionContractError("Scientific resource directory is empty.")
    canonical = json.dumps(
        entries,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def current_platform_id() -> str:
    """Return the conda/Docker platform identifier used by approved tool profiles."""
    system = runtime_platform.system().casefold()
    machine = runtime_platform.machine().casefold()
    if machine in {"x86_64", "amd64"}:
        architecture = "64"
    elif machine in {"aarch64", "arm64"}:
        architecture = "aarch64" if system == "linux" else "arm64"
    else:
        raise ToolExecutionContractError(
            f"Unsupported scientific worker architecture: {runtime_platform.machine()!r}."
        )
    if system == "linux":
        return f"linux-{architecture}"
    if system == "darwin":
        return f"osx-{architecture}"
    if system == "windows" and architecture == "64":
        return "win-64"
    raise ToolExecutionContractError(
        f"Unsupported scientific worker platform: {runtime_platform.system()!r}."
    )


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
    runtime_image_digest: str | None = None
    runtime_path: tuple[str, ...] = ("/usr/bin", "/bin")
    runtime_environment: Mapping[str, str] = field(default_factory=dict)

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
        actual_platform = current_platform_id()
        if self.platform != actual_platform:
            raise ToolExecutionContractError(
                f"Tool profile platform {self.platform!r} does not match worker platform {actual_platform!r}."
            )
        if self.runtime_image_digest is not None and not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.runtime_image_digest.lower()
        ):
            raise ToolExecutionContractError(
                "Runtime image digest must use the sha256:<64 lowercase hex> format."
            )
        if not self.runtime_path:
            raise ToolExecutionContractError("Approved runtime PATH must contain at least one directory.")
        for item in self.runtime_path:
            path = Path(item)
            if not path.is_absolute():
                raise ToolExecutionContractError(
                    f"Approved runtime PATH entry must be absolute: {item!r}."
                )
            # A container profile's PATH belongs to the image, not the host.
            # Local-process profiles still require every directory to exist on
            # the executing host.
            if self.runtime_image_digest is None and not path.is_dir():
                raise ToolExecutionContractError(
                    f"Approved host runtime PATH entry must be an existing directory: {item!r}."
                )
        protected_runtime_environment = {
            "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
            "IFS", "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH",
            "BASH_ENV", "ENV",
        }
        for key, value in self.runtime_environment.items():
            if (
                not str(key).replace("_", "").isalnum()
                or str(key).upper() in protected_runtime_environment
                or str(key).upper().startswith("LD_")
                or "\\x00" in str(value)
            ):
                raise ToolExecutionContractError(
                    f"Approved runtime environment contains an invalid or protected variable: {key!r}."
                )
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
    path: str | None = None
    sidecar_paths: tuple[str, ...] = ()
    stat_fingerprint: tuple[tuple[str, int, int, int, int, int], ...] = ()

    @classmethod
    def from_verified_files(
        cls,
        *,
        resource_id: str,
        version: str,
        path: str | Path,
        sidecar_paths: tuple[str | Path, ...] = (),
        assembly: str | None = None,
        verified_primary_sha256: str | None = None,
    ) -> "ScientificResourceBinding":
        """Create a reusable binding after primary bytes have been independently verified.

        The primary digest may come from the immutable source-release verifier.
        Sidecars are hashed here. Device/inode/size/mtime/ctime fingerprints are
        rechecked on every execution so a large indexed VCF is not rehashed for
        every single-locus query.
        """
        primary = Path(path).resolve(strict=True)
        paths = (primary, *(Path(item).resolve(strict=True) for item in sidecar_paths))
        for item in paths:
            if _contains_symlink_component(item) or not item.is_file():
                raise ToolExecutionContractError(
                    "Scientific resource files must be regular files without symlink components."
                )
        primary_digest = (verified_primary_sha256 or sha256_file(primary)).lower()
        if len(primary_digest) != 64 or any(c not in "0123456789abcdef" for c in primary_digest):
            raise ToolExecutionContractError("Verified primary resource SHA-256 is malformed.")
        entries = [{"name": primary.name, "sha256": primary_digest}]
        for item in paths[1:]:
            entries.append({"name": item.name, "sha256": sha256_file(item)})
        canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
        bundle_digest = hashlib.sha256(canonical).hexdigest()
        fingerprint = tuple(
            (
                str(item),
                item.stat().st_dev,
                item.stat().st_ino,
                item.stat().st_size,
                item.stat().st_mtime_ns,
                item.stat().st_ctime_ns,
            )
            for item in paths
        )
        return cls(
            resource_id=resource_id,
            version=version,
            sha256=bundle_digest,
            assembly=assembly,
            path=str(primary),
            sidecar_paths=tuple(str(item) for item in paths[1:]),
            stat_fingerprint=fingerprint,
        )

    def validate(self) -> None:
        if not self.resource_id.strip() or not self.version.strip():
            raise ToolExecutionContractError("Scientific resource identity and version are required.")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256.lower()):
            raise ToolExecutionContractError("Scientific resource SHA-256 must be a 64-character hex digest.")
        if not self.path:
            raise ToolExecutionContractError(
                "Scientific resource binding must identify the local bytes to verify."
            )
        paths = (Path(self.path), *(Path(item) for item in self.sidecar_paths))
        if self.stat_fingerprint:
            current = []
            for item in paths:
                resolved = item.resolve(strict=True)
                if _contains_symlink_component(item) or not resolved.is_file():
                    raise ToolExecutionContractError(
                        "Scientific resource files must remain regular files without symlink components."
                    )
                stat_result = resolved.stat()
                current.append((
                    str(resolved),
                    stat_result.st_dev,
                    stat_result.st_ino,
                    stat_result.st_size,
                    stat_result.st_mtime_ns,
                    stat_result.st_ctime_ns,
                ))
            if tuple(current) != self.stat_fingerprint:
                raise ToolExecutionContractError(
                    f"Scientific resource {self.resource_id!r} changed after its verified snapshot."
                )
            return

        primary = Path(self.path)
        if self.sidecar_paths:
            entries = [{"name": primary.name, "sha256": sha256_file(primary)}]
            entries.extend(
                {"name": item.name, "sha256": sha256_file(item)}
                for item in (Path(value) for value in self.sidecar_paths)
            )
            canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
            actual_digest = hashlib.sha256(canonical).hexdigest()
        else:
            actual_digest = sha256_resource_path(primary)
        if actual_digest != self.sha256.lower():
            raise ToolExecutionContractError(
                f"Scientific resource {self.resource_id!r} SHA-256 does not match its governed bytes."
            )


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
    max_output_bytes: int = 1_048_576
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
        if not 1024 <= int(self.max_output_bytes) <= 10_485_760:
            raise ToolExecutionContractError("Captured process output limit must be between 1024 bytes and 10 MiB.")
        workspace = Path(self.workspace)
        if not workspace.is_absolute() or not workspace.is_dir() or _contains_symlink_component(workspace):
            raise ToolExecutionContractError("Execution workspace must be an existing absolute non-symlink directory.")
        input_names: set[str] = set()
        for item in self.inputs:
            if not item.name or item.name in input_names:
                raise ToolExecutionContractError("Input artifact names must be present and unique.")
            input_names.add(item.name)
            path = Path(item.path)
            if not path.is_absolute() or not path.is_file() or _contains_symlink_component(path):
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
            if _contains_symlink_component(path):
                raise ToolExecutionContractError(f"Output artifact {item.name!r} cannot contain symlink components.")
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
            "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
            "IFS", "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD",
            "LD_LIBRARY_PATH", "BASH_ENV", "ENV",
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
        profile_overrides = sorted(
            str(key) for key in self.environment
            if str(key) in profile.runtime_environment
        )
        if profile_overrides:
            raise ToolExecutionContractError(
                "Execution request cannot override approved tool-profile variable(s): "
                + ", ".join(profile_overrides)
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
    platform: str
    runtime_image_digest: str | None
    environment_sha256: str


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
        if _contains_symlink_component(configured_executable):
            raise ToolExecutionContractError("Configured tool executable cannot contain symlink components.")
        executable = configured_executable.resolve(strict=True)
        if not executable.is_file():
            raise ToolExecutionContractError("Tool executable is not a regular file.")
        executable_digest = sha256_file(executable)
        if executable_digest != profile.executable_sha256.lower():
            raise ToolExecutionContractError("Tool executable SHA-256 does not match the approved profile.")

        workspace = Path(request.workspace).resolve(strict=True)
        runtime_path = tuple(dict.fromkeys(
            str(Path(item).resolve(strict=True)) for item in profile.runtime_path
        ))
        env = {
            "PATH": os.pathsep.join(runtime_path),
            "HOME": str(workspace),
            "TMPDIR": str(workspace),
            "TEMP": str(workspace),
            "TMP": str(workspace),
            "LANG": "C",
            "LC_ALL": "C",
        }
        env.update({str(key): str(value) for key, value in profile.runtime_environment.items()})
        env.update({str(key): str(value) for key, value in request.environment.items()})
        environment_sha256 = hashlib.sha256(
            json.dumps(sorted(env.items()), separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        try:
            version_check = subprocess.run(
                [str(executable), *profile.version_args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError(
                f"{profile.tool_id} version attestation timed out.",
                retryable=True,
            ) from exc
        except OSError as exc:
            raise ToolExecutionError(
                f"{profile.tool_id} version attestation could not start.",
                retryable=False,
            ) from exc
        version_text = (version_check.stdout + "\n" + version_check.stderr).strip()
        if version_check.returncode != 0 or profile.version_output_contains not in version_text:
            raise ToolExecutionContractError(
                "Runtime executable version does not match the approved tool profile."
            )

        command = [str(executable), *request.argv]
        started = datetime.now(timezone.utc)
        monotonic_start = time.monotonic()
        timed_out = False

        # Spool process output to disk rather than PIPEs: a noisy scientific
        # executable must not exhaust worker memory. Hash complete streams while
        # retaining only a bounded diagnostic tail.
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=workspace,
                    env=env,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    start_new_session=True,
                )
            except OSError as exc:
                raise ToolExecutionError(
                    f"{profile.tool_id} process could not be started: {exc}",
                    retryable=False,
                ) from exc
            try:
                process.communicate(timeout=request.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

            def capture(handle) -> tuple[str, str]:
                handle.seek(0)
                digest = hashlib.sha256()
                tail = bytearray()
                total = 0
                while True:
                    chunk = handle.read(64 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    total += len(chunk)
                    tail.extend(chunk)
                    if len(tail) > request.max_output_bytes:
                        del tail[:-request.max_output_bytes]
                rendered = tail.decode("utf-8", errors="replace")
                if total > request.max_output_bytes:
                    rendered = "[... earlier process output truncated ...]\\n" + rendered
                return rendered, digest.hexdigest()

            stdout, stdout_digest = capture(stdout_file)
            stderr, stderr_digest = capture(stderr_file)

        completed = datetime.now(timezone.utc)
        duration = time.monotonic() - monotonic_start
        output_digests: list[dict[str, str]] = []
        missing_outputs: list[str] = []
        for item in request.outputs:
            path = Path(item.path)
            if not path.is_file() or _contains_symlink_component(path):
                missing_outputs.append(item.name)
                continue
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
            stdout_sha256=stdout_digest,
            stderr_sha256=stderr_digest,
            platform=profile.platform,
            runtime_image_digest=profile.runtime_image_digest,
            environment_sha256=environment_sha256,
        )

        if timed_out:
            raise ToolExecutionError(
                f"{profile.tool_id} execution exceeded its {request.timeout_seconds}s timeout; process group terminated.",
                retryable=True,
                provenance=provenance,
            )
        if process.returncode != 0:
            raise ToolExecutionError(
                f"{profile.tool_id} exited with status {process.returncode}: {(stderr or stdout)[-2000:]}",
                retryable=process.returncode in {137, 143, -9, -15},
                provenance=provenance,
            )
        if missing_outputs:
            raise ToolExecutionError(
                "Expected output artifact(s) were not produced: " + ", ".join(missing_outputs),
                retryable=False,
                provenance=provenance,
            )
        return ToolExecutionResult(provenance=provenance, stdout=stdout, stderr=stderr)
