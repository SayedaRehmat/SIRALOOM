"""Fail-closed Docker/Podman executor for pinned Linux OCI tool images.

The adapter deliberately accepts an already-qualified environment profile. It
never pulls mutable tags, never uses a shell for host-side execution, and emits
the same ToolExecutionResult/ToolExecutionProvenance contract as local runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from typing import Callable
from uuid import uuid4

from backend.app.domain.execution_environments import (
    ExecutionEnvironmentProfile,
    ExecutionEnvironmentError,
)
from backend.app.domain.tool_execution import (
    ToolExecutionContractError,
    ToolExecutionError,
    ToolExecutionProvenance,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolIdentity,
    _contains_symlink_component,
    sha256_file,
)


@dataclass(frozen=True)
class ContainerResourceLimits:
    """Per-execution cgroup limits; values are explicit, never inferred."""

    cpu_cores: float
    memory_bytes: int
    pids_limit: int
    container_user: str

    def validate(self, environment: ExecutionEnvironmentProfile) -> None:
        if (
            isinstance(self.cpu_cores, bool)
            or not isinstance(self.cpu_cores, (int, float))
            or not math.isfinite(self.cpu_cores)
            or not math.isfinite(environment.capacity.cpu_cores)
            or self.cpu_cores <= 0
            or self.cpu_cores > environment.capacity.cpu_cores
        ):
            raise ToolExecutionContractError("Container CPU limit is absent or exceeds qualified environment capacity.")
        if isinstance(self.memory_bytes, bool) or not isinstance(self.memory_bytes, int) or self.memory_bytes <= 0 or self.memory_bytes > environment.capacity.memory_bytes:
            raise ToolExecutionContractError("Container memory limit is absent or exceeds qualified environment capacity.")
        if isinstance(self.pids_limit, bool) or not isinstance(self.pids_limit, int) or self.pids_limit < 1 or self.pids_limit > 65536:
            raise ToolExecutionContractError("Container process limit must be between 1 and 65536.")
        if not isinstance(self.container_user, str) or not re.fullmatch(r"[0-9]+:[0-9]+", self.container_user):
            raise ToolExecutionContractError("Container user must be an explicit numeric uid:gid pair.")


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class LinuxContainerToolExecutor:
    """Run one tool in a verified, resource-bounded Docker or Podman container."""

    def __init__(
        self,
        environment: ExecutionEnvironmentProfile,
        limits: ContainerResourceLimits,
        *,
        runner: CommandRunner = subprocess.run,
        runtime_path: str | None = None,
    ) -> None:
        self.environment = environment
        self.limits = limits
        self.runner = runner
        self.runtime_path = runtime_path

    def _runtime(self) -> str:
        env = self.environment
        env.validate()
        if env.executor_kind != "CONTAINER" or env.operating_system.casefold() != "linux":
            raise ExecutionEnvironmentError("Linux container executor requires a Linux CONTAINER environment.")
        if env.runtime_kind not in {"DOCKER", "PODMAN"}:
            raise ExecutionEnvironmentError("Only Docker and Podman are supported by this executor.")
        if env.scheduler not in {"NONE", "DOCKER_COMPOSE"}:
            raise ExecutionEnvironmentError("This adapter cannot execute scheduler-managed environments.")
        if env.network_policy != "OFFLINE":
            raise ExecutionEnvironmentError("Container execution currently requires OFFLINE network policy.")
        self.limits.validate(env)
        candidate = self.runtime_path or shutil.which(env.runtime_kind.casefold())
        if not candidate:
            raise ToolExecutionContractError(f"Required {env.runtime_kind} runtime is unavailable.")
        path = Path(candidate)
        if not path.is_absolute() or _contains_symlink_component(path) or not path.is_file():
            raise ToolExecutionContractError("Container runtime path must be an existing absolute non-symlink executable.")
        return str(path.resolve(strict=True))

    def _run_checked(self, command: list[str], *, timeout: int = 30) -> str:
        try:
            result = self.runner(
                command, capture_output=True, text=True, timeout=timeout,
                check=False, env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolExecutionError("Container runtime verification command failed.", retryable=True) from exc
        if result.returncode != 0:
            raise ToolExecutionContractError("Container runtime verification failed: " + (result.stderr or "")[-1000:])
        return (result.stdout or "").strip()

    @staticmethod
    def _safe_mount_name(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", value)
        if not safe or safe in {".", ".."}:
            raise ToolExecutionContractError("Input/resource mount identity is invalid.")
        return safe

    @staticmethod
    def _validate_workspace_contents(workspace: Path) -> None:
        """Prevent symlink/special-file and hard-link aliases from escaping isolation."""
        try:
            for child in workspace.rglob("*"):
                metadata = child.lstat()
                mode = metadata.st_mode
                if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise ToolExecutionContractError(
                        "Container workspace may contain only regular files and directories; symlinks and special files are forbidden."
                    )
                if stat.S_ISREG(mode) and metadata.st_nlink != 1:
                    raise ToolExecutionContractError(
                        "Container workspace cannot contain hard-linked files."
                    )
        except OSError as exc:
            raise ToolExecutionContractError("Container workspace could not be safely inspected.") from exc

    def _verify_runtime_and_image(self, runtime: str) -> str:
        if self.environment.runtime_kind == "DOCKER":
            # Docker CLI presence is not enough: require a reachable daemon and
            # attest the server version that will actually create the container.
            version = self._run_checked([runtime, "version", "--format", "{{.Server.Version}}"])
        else:
            version = self._run_checked([runtime, "--version"])
        if self.environment.runtime_version not in version:
            raise ToolExecutionContractError("Installed container runtime version does not match the qualified environment.")
        cgroup_version = self._run_checked(
            [runtime, "info", "--format", "{{.CgroupVersion}}" if self.environment.runtime_kind == "DOCKER" else "{{.Host.CgroupsVersion}}"]
        )
        if cgroup_version not in {"1", "2", "v1", "v2"}:
            raise ToolExecutionContractError(
                "Container runtime does not expose a verifiable Linux cgroup v1/v2 controller for resource enforcement."
            )
        image_ref = self.environment.runtime_image_reference
        digest = self.environment.runtime_image_digest
        if not image_ref or not digest or not image_ref.endswith("@" + digest):
            raise ToolExecutionContractError("Qualified environment lacks an immutable OCI image reference.")
        inspected = self._run_checked([
            runtime, "image", "inspect", "--format", "{{json .RepoDigests}}", image_ref
        ])
        try:
            repo_digests = json.loads(inspected)
        except json.JSONDecodeError as exc:
            raise ToolExecutionContractError("Container runtime returned an unverifiable image digest response.") from exc
        if not isinstance(repo_digests, list) or image_ref not in repo_digests:
            raise ToolExecutionContractError("Locally available OCI image does not resolve to the exact approved repository digest.")
        return image_ref

    def execute(self, profile: ToolIdentity, request: ToolExecutionRequest) -> ToolExecutionResult:
        profile.validate()
        request.validate(profile)
        self.environment.assert_tool_compatible(profile)
        runtime = self._runtime()
        image_ref = self._verify_runtime_and_image(runtime)

        workspace = Path(request.workspace).resolve(strict=True)
        self._validate_workspace_contents(workspace)
        executable = profile.executable
        if not executable.startswith("/") or "\x00" in executable:
            raise ToolExecutionContractError("Container tool executable must be an absolute in-image path.")

        mounts: list[str] = [
            "--mount", f"type=bind,src={workspace},dst=/workspace",
        ]
        argv = list(request.argv)
        input_mount_names: set[str] = set()
        for item in request.inputs:
            host = Path(item.path).resolve(strict=True)
            if host.is_relative_to(workspace):
                raise ToolExecutionContractError(
                    "Inputs inside the writable workspace cannot be guaranteed read-only; stage them outside the workspace."
                )
            name = self._safe_mount_name(item.name)
            if name in input_mount_names:
                raise ToolExecutionContractError("Input names collide after safe mount-name normalization.")
            input_mount_names.add(name)
            target = f"/inputs/{name}"
            mounts.extend(["--mount", f"type=bind,src={host},dst={target},readonly"])
            argv = [arg.replace(item.path, target) for arg in argv]
        resource_mount_names: set[str] = set()
        for item in request.resources:
            host = Path(item.path or "").resolve(strict=True)
            if host == workspace or host.is_relative_to(workspace):
                raise ToolExecutionContractError(
                    "Scientific resources inside the writable workspace cannot be guaranteed read-only."
                )
            name = self._safe_mount_name(item.resource_id)
            if name in resource_mount_names:
                raise ToolExecutionContractError("Resource IDs collide after safe mount-name normalization.")
            resource_mount_names.add(name)
            target = f"/resources/{name}"
            mounts.extend(["--mount", f"type=bind,src={host},dst={target},readonly"])
            argv = [arg.replace(item.path or "", target) for arg in argv]
        argv = [arg.replace(str(workspace), "/workspace") for arg in argv]

        base = [
            runtime, "run", "--rm", "--pull=never",
            "--network=none", "--read-only",
            "--cpus", str(self.limits.cpu_cores),
            "--memory", str(self.limits.memory_bytes),
            "--memory-swap", str(self.limits.memory_bytes),
            "--pids-limit", str(self.limits.pids_limit),
            "--user", self.limits.container_user,
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=1g",
            "--tmpfs", "/inputs:rw,noexec,nosuid,nodev,size=64m",
            "--tmpfs", "/resources:rw,noexec,nosuid,nodev,size=64m",
            "--workdir", "/workspace",
            *mounts,
        ]
        env = {
            "PATH": os.pathsep.join(profile.runtime_path),
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "LANG": "C",
            "LC_ALL": "C",
        }
        env.update({str(k): str(v) for k, v in profile.runtime_environment.items()})
        env.update({str(k): str(v) for k, v in request.environment.items()})
        for key, value in sorted(env.items()):
            base.extend(["--env", f"{key}={value}"])

        # Verify executable bytes and the declared version inside the exact
        # immutable image before invoking the requested scientific operation.
        digest_result = self._run_checked([
            runtime, "run", "--rm", "--pull=never", "--network=none", "--read-only",
            image_ref, "sha256sum", executable,
        ])
        observed_digest = digest_result.split()[0] if digest_result.split() else ""
        if observed_digest != profile.executable_sha256.lower():
            raise ToolExecutionContractError("In-image executable SHA-256 does not match the qualified tool profile.")
        version_result = self._run_checked([
            runtime, "run", "--rm", "--pull=never", "--network=none", "--read-only",
            image_ref, executable, *profile.version_args,
        ])
        if profile.version_output_contains not in version_result:
            raise ToolExecutionContractError("In-image tool version does not match the qualified tool profile.")

        container_name = "siraloom-" + uuid4().hex
        command = [*base, "--name", container_name, image_ref, executable, *argv]
        started = datetime.now(timezone.utc)
        monotonic_start = time.monotonic()
        timed_out = False
        cleanup_error: str | None = None
        runtime_kill_error: str | None = None
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(command, stdout=stdout_file, stderr=stderr_file, env={
                    "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"
                }, start_new_session=True)
            except OSError as exc:
                raise ToolExecutionError("Container execution could not be started.", retryable=False) from exc
            try:
                process.wait(timeout=request.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    self.runner(
                        [runtime, "kill", container_name],
                        capture_output=True, text=True, timeout=15, check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    # A failed runtime kill is not silently accepted. The
                    # force-remove and subsequent ps verification below get a
                    # chance to recover; otherwise the failure is persisted.
                    runtime_kill_error = f"runtime kill failed: {type(exc).__name__}"
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        cleanup_error = "container client process did not terminate after SIGKILL"
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=5)
            finally:
                try:
                    self.runner(
                        [runtime, "rm", "--force", container_name],
                        capture_output=True, text=True, timeout=15, check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    cleanup_error = cleanup_error or f"runtime force-remove failed: {type(exc).__name__}"
                try:
                    remaining = self.runner(
                        [runtime, "ps", "--all", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
                        capture_output=True, text=True, timeout=15, check=False,
                    )
                    if remaining.returncode != 0:
                        cleanup_error = cleanup_error or ("runtime could not verify container removal" + (f" ({runtime_kill_error})" if runtime_kill_error else ""))
                    elif container_name in (remaining.stdout or "").splitlines():
                        cleanup_error = cleanup_error or ("container remains after force-remove" + (f" ({runtime_kill_error})" if runtime_kill_error else ""))
                except (OSError, subprocess.TimeoutExpired) as exc:
                    cleanup_error = cleanup_error or f"container removal could not be verified: {type(exc).__name__}"

            def capture(handle: object) -> tuple[str, str]:
                handle.seek(0)
                digest = hashlib.sha256()
                tail = bytearray()
                total = 0
                while True:
                    chunk = handle.read(65536)
                    if not chunk:
                        break
                    digest.update(chunk)
                    total += len(chunk)
                    tail.extend(chunk)
                    if len(tail) > request.max_output_bytes:
                        del tail[:-request.max_output_bytes]
                rendered = tail.decode("utf-8", errors="replace")
                if total > request.max_output_bytes:
                    rendered = "[... earlier process output truncated ...]\n" + rendered
                return rendered, digest.hexdigest()

            stdout, stdout_digest = capture(stdout_file)
            stderr, stderr_digest = capture(stderr_file)

        completed = datetime.now(timezone.utc)
        duration = time.monotonic() - monotonic_start
        output_digests = []
        missing = []
        for item in request.outputs:
            path = Path(item.path)
            if not path.is_file() or _contains_symlink_component(path):
                missing.append(item.name)
            else:
                output_digests.append({"name": item.name, "sha256": sha256_file(path)})
        provenance = ToolExecutionProvenance(
            execution_id=request.execution_id,
            organization_id=request.organization_id,
            workflow_id=request.workflow_id,
            operation=request.operation,
            tool_id=profile.tool_id,
            tool_version=profile.version,
            profile_id=profile.profile_id,
            executable_sha256=profile.executable_sha256.lower(),
            resource_bindings=tuple({
                "resource_id": item.resource_id, "version": item.version,
                "sha256": item.sha256, "assembly": item.assembly,
            } for item in request.resources),
            input_sha256=tuple({"name": item.name, "sha256": item.sha256.lower()} for item in request.inputs),
            output_sha256=tuple(output_digests),
            argv=tuple(command),
            exit_code=process.returncode,
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            duration_seconds=duration,
            stdout_sha256=stdout_digest,
            stderr_sha256=stderr_digest,
            platform=profile.platform,
            runtime_image_digest=self.environment.runtime_image_digest,
            environment_sha256=hashlib.sha256(
                json.dumps(sorted(env.items()), separators=(",", ":")).encode()
            ).hexdigest(),
        )
        if cleanup_error:
            raise ToolExecutionError(
                "Container cleanup could not be verified: " + cleanup_error,
                retryable=True, provenance=provenance,
            )
        if timed_out:
            raise ToolExecutionError(
                f"{profile.tool_id} container exceeded its {request.timeout_seconds}s timeout and was terminated.",
                retryable=True, provenance=provenance,
            )
        if process.returncode != 0:
            raise ToolExecutionError(
                f"{profile.tool_id} container exited with status {process.returncode}: {(stderr or stdout)[-2000:]}",
                retryable=process.returncode in {137, 143, -9, -15}, provenance=provenance,
            )
        if missing:
            raise ToolExecutionError("Expected container output(s) were not produced: " + ", ".join(missing), provenance=provenance)
        return ToolExecutionResult(provenance=provenance, stdout=stdout, stderr=stderr)



class EnvironmentAwareToolExecutor:
    """Select the existing local executor or the Linux OCI adapter by profile.

    Unsupported schedulers and remote-agent dispatch are rejected explicitly;
    they must not silently fall back to local execution.
    """

    def __init__(
        self,
        environment: ExecutionEnvironmentProfile,
        *,
        container_limits: ContainerResourceLimits | None = None,
        runtime_path: str | None = None,
    ) -> None:
        self.environment = environment
        self.container_limits = container_limits
        self.runtime_path = runtime_path

    def execute(self, profile: ToolIdentity, request: ToolExecutionRequest) -> ToolExecutionResult:
        self.environment.assert_tool_compatible(profile)
        if self.environment.executor_kind == "LOCAL_PROCESS":
            from backend.app.domain.tool_execution import LocalProcessToolExecutor
            if self.environment.runtime_kind != "HOST":
                raise ExecutionEnvironmentError("Local-process execution requires a HOST runtime profile.")
            return LocalProcessToolExecutor().execute(profile, request)
        if self.environment.executor_kind == "CONTAINER":
            if self.container_limits is None:
                raise ToolExecutionContractError("Container execution requires explicit per-job CPU, memory and PID limits.")
            return LinuxContainerToolExecutor(
                self.environment, self.container_limits, runtime_path=self.runtime_path
            ).execute(profile, request)
        raise ExecutionEnvironmentError(
            f"Executor kind {self.environment.executor_kind!r} is not implemented; refusing local fallback."
        )
