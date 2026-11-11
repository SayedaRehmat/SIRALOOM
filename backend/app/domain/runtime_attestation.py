"""Collect measured scientific runtime component identities on the executing worker.

Clinical execution requires both byte-level component hashes and an image identity
reported by the container orchestrator for this exact running container. Missing
or unverifiable evidence is a hard failure; environment variables are not accepted
as image-digest evidence.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from backend.app.config import settings
from backend.app.domain.toolchain_profiles import resolve_registered_toolchain_profile


class RuntimeAttestationError(RuntimeError):
    """Runtime identity could not be measured or trusted."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"sha256:([0-9a-f]{64})")
_CONTAINER_ID = re.compile(r"([0-9a-f]{64})")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeAttestationError(f"Cannot hash runtime component file {path}") from exc
    return digest.hexdigest()


def _sha256_tree(root: Path) -> str:
    if not root.is_dir():
        raise RuntimeAttestationError(f"Required runtime source directory is missing: {root}")
    digest = hashlib.sha256()
    files = sorted(
        path for path in root.rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )
    if not files:
        raise RuntimeAttestationError(f"No Python workflow source files found under {root}")
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def _bcftools_and_htslib() -> tuple[Path, str, str, Path]:
    executable_value = settings.bcftools_executable
    executable = Path(executable_value)
    if not executable.is_absolute():
        located = shutil.which(executable_value)
        if not located:
            raise RuntimeAttestationError("Configured BCFtools executable is not present on worker PATH")
        executable = Path(located)
    executable = executable.resolve(strict=True)
    if not executable.is_file():
        raise RuntimeAttestationError("Configured BCFtools executable is not a regular file")

    try:
        version_result = subprocess.run(
            [str(executable), "--version"],
            check=True, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeAttestationError("Cannot execute the configured BCFtools binary for attestation") from exc
    lines = (version_result.stdout or version_result.stderr).splitlines()
    if len(lines) < 2:
        raise RuntimeAttestationError("BCFtools did not report both BCFtools and HTSlib versions")
    bcftools_match = re.match(r"^bcftools\s+(\S+)", lines[0].strip())
    htslib_match = re.search(r"htslib\s+(\S+)", lines[1].strip(), re.IGNORECASE)
    if not bcftools_match or not htslib_match:
        raise RuntimeAttestationError("Cannot parse the BCFtools/HTSlib runtime versions")
    bcftools_version, htslib_version = bcftools_match.group(1), htslib_match.group(1)
    if bcftools_version != settings.bcftools_version or htslib_version != settings.htslib_version:
        raise RuntimeAttestationError(
            "Observed BCFtools/HTSlib versions differ from the configured qualified profile"
        )

    try:
        linked = subprocess.run(
            ["ldd", str(executable)], check=True, capture_output=True, text=True, timeout=15
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeAttestationError("Cannot resolve the HTSlib library linked to BCFtools") from exc
    candidates = []
    for line in linked.splitlines():
        if "libhts.so" not in line:
            continue
        match = re.search(r"=>\s+(/\S+)", line)
        if match:
            candidates.append(Path(match.group(1)))
    if len(candidates) != 1:
        raise RuntimeAttestationError(
            "Cannot establish one unambiguous dynamically linked HTSlib library for BCFtools"
        )
    htslib_path = candidates[0].resolve(strict=True)
    if not htslib_path.is_file():
        raise RuntimeAttestationError("Resolved HTSlib library is not a regular file")
    return executable, bcftools_version, htslib_version, htslib_path


def _current_container_id() -> str:
    try:
        lines = Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeAttestationError("Cannot identify the current worker container from cgroups") from exc
    matches = set()
    for line in lines:
        matches.update(_CONTAINER_ID.findall(line.lower()))
    if len(matches) != 1:
        raise RuntimeAttestationError("Current worker container ID is missing or ambiguous in cgroup metadata")
    return next(iter(matches))


def _kubernetes_image_identity() -> tuple[str, str]:
    """Read imageID from the Kubernetes API and bind it to this container's cgroup ID."""
    pod_name = os.environ.get("POD_NAME", "").strip()
    namespace = os.environ.get("POD_NAMESPACE", "").strip()
    container_name = os.environ.get("SIRALOOM_K8S_CONTAINER_NAME", "").strip()
    api_host = os.environ.get("KUBERNETES_SERVICE_HOST", "").strip()
    api_port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443").strip()
    if not all((pod_name, namespace, container_name, api_host)):
        raise RuntimeAttestationError(
            "Trusted container image identity is unavailable: configure Kubernetes pod identity "
            "and a worker-container name; do not substitute an environment-provided image digest"
        )
    token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    ca_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
    try:
        token = token_path.read_text(encoding="utf-8").strip()
        context = ssl.create_default_context(cafile=str(ca_path))
    except (OSError, ssl.SSLError) as exc:
        raise RuntimeAttestationError("Kubernetes service-account trust material is unavailable") from exc
    if not token:
        raise RuntimeAttestationError("Kubernetes service-account token is empty")

    # Quote path segments; never accept an API URL supplied by the deployment.
    from urllib.parse import quote
    url = (
        f"https://{api_host}:{api_port}/api/v1/namespaces/{quote(namespace, safe='')}"
        f"/pods/{quote(pod_name, safe='')}"
    )
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urlopen(request, context=context, timeout=5) as response:
            pod = json.loads(response.read(2 * 1024 * 1024))
    except (OSError, URLError, ValueError, TimeoutError) as exc:
        raise RuntimeAttestationError("Cannot obtain the current worker Pod status from Kubernetes") from exc

    container_id = _current_container_id()
    statuses = pod.get("status", {}).get("containerStatuses", [])
    matches = [
        item for item in statuses
        if item.get("name") == container_name
        and str(item.get("containerID", "")).lower().endswith(container_id)
        and item.get("state", {}).get("running") is not None
    ]
    if len(matches) != 1:
        raise RuntimeAttestationError(
            "Kubernetes Pod status does not identify exactly one running container matching this worker"
        )
    image_id = str(matches[0].get("imageID") or "")
    digest_match = _IMAGE_DIGEST.search(image_id)
    if not digest_match:
        raise RuntimeAttestationError("Kubernetes did not report an immutable sha256 imageID for this worker")
    digest = digest_match.group(1)
    return "sha256:" + digest, digest


def collect_runtime_component_manifest(*, workflow_version: str) -> list[dict[str, str]]:
    """Measure all mandatory components from the worker that will execute analysis."""
    root = Path(__file__).resolve().parents[3]
    executable, bcftools_version, htslib_version, htslib_path = _bcftools_and_htslib()
    profile = resolve_registered_toolchain_profile(settings.bcftools_profile_id)
    native_lock = root / str(profile["lock_file"])
    python_lock = root / "uv.lock"
    if not native_lock.is_file() or not python_lock.is_file():
        raise RuntimeAttestationError("One or more locked dependency manifests are missing")

    workflow_digest = _sha256_tree(root / "backend" / "app" / "workflows")
    image_version, image_digest = _kubernetes_image_identity()
    components = [
        {"name": "bcftools", "version": bcftools_version, "sha256": _sha256_file(executable)},
        {"name": "htslib", "version": htslib_version, "sha256": _sha256_file(htslib_path)},
        {"name": "native_toolchain_lock", "version": str(profile["id"]), "sha256": _sha256_file(native_lock)},
        {"name": "python_dependency_lock", "version": "uv.lock", "sha256": _sha256_file(python_lock)},
        {"name": "siraloom_variant_workflow", "version": workflow_version, "sha256": workflow_digest},
        {"name": "container_image", "version": image_version, "sha256": image_digest},
    ]
    return components


def runtime_manifest_sha256(components: list[dict[str, str]]) -> str:
    canonical = json.dumps(components, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()

def attest_clinical_analysis_runtime(
    db,
    analysis,
    *,
    redelivered: bool,
    retry: bool,
) -> tuple[bool, str | None]:
    """Attest, audit and persist the runtime gate before any clinical stage resumes."""
    from datetime import datetime, timezone

    from backend.app.domain.assay_validation import (
        AssayValidationError,
        assert_pipeline_components_match_runtime,
    )
    from backend.app.domain.enums import AnalysisStatus
    from backend.app.infrastructure.audit.service import AuditService

    configuration = dict(analysis.configuration or {})
    validation_snapshot = configuration.get("assay_validation_snapshot")
    try:
        observed_components = collect_runtime_component_manifest(
            workflow_version=str(analysis.workflow_version)
        )
        assert_pipeline_components_match_runtime(validation_snapshot, observed_components)
    except (RuntimeAttestationError, AssayValidationError) as exc:
        analysis.status = AnalysisStatus.BLOCKED
        analysis.completed_at = datetime.now(timezone.utc)
        configuration["runtime_attestation_block"] = str(exc)
        analysis.configuration = configuration
        db.add(analysis)
        AuditService(db).record(
            event_type="CLINICAL_RUNTIME_ATTESTATION_BLOCKED",
            case_id=analysis.case_id,
            analysis_id=analysis.id,
            actor_type="SYSTEM",
            actor_id="runtime-attestation-gate",
            subject_type="ANALYSIS",
            subject_id=str(analysis.id),
            operation="BLOCK",
            reason=str(exc),
            payload={"redelivered": redelivered, "retry": retry},
        )
        db.commit()
        return False, str(exc)

    AuditService(db).record(
        event_type="CLINICAL_RUNTIME_ATTESTED",
        case_id=analysis.case_id,
        analysis_id=analysis.id,
        actor_type="SYSTEM",
        actor_id="runtime-attestation-gate",
        subject_type="ANALYSIS",
        subject_id=str(analysis.id),
        operation="ATTEST",
        payload={
            "manifest_sha256": runtime_manifest_sha256(observed_components),
            "components": observed_components,
            "redelivered": redelivered,
            "retry": retry,
        },
    )
    db.commit()
    return True, None

def assert_analysis_runtime_attested(db, analysis) -> None:
    """Require a valid successful worker attestation before clinical sign-out/use."""
    from sqlalchemy import select

    from backend.app.domain.assay_validation import (
        AssayValidationError,
        assert_pipeline_components_match_runtime,
    )
    from backend.app.infrastructure.db.models import AuditEvent

    events = list(db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.analysis_id == analysis.id,
            AuditEvent.event_type.in_((
                "CLINICAL_RUNTIME_ATTESTED",
                "CLINICAL_RUNTIME_ATTESTATION_BLOCKED",
            )),
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(1)
    ))
    if not events:
        raise RuntimeAttestationError(
            "Clinical analysis has no persisted worker runtime attestation"
        )
    event = events[0]
    if event.event_type != "CLINICAL_RUNTIME_ATTESTED":
        raise RuntimeAttestationError(
            "The latest worker runtime attestation blocked clinical execution"
        )
    if not isinstance(event.event_hash, str) or not _SHA256.fullmatch(event.event_hash):
        raise RuntimeAttestationError("Runtime attestation audit event has no valid event-chain hash")
    payload = event.payload if isinstance(event.payload, dict) else {}
    components = payload.get("components")
    if not isinstance(components, list):
        raise RuntimeAttestationError("Runtime attestation audit event has no component manifest")
    if payload.get("manifest_sha256") != runtime_manifest_sha256(components):
        raise RuntimeAttestationError("Runtime attestation manifest digest does not match its recorded components")
    configuration = dict(analysis.configuration or {})
    snapshot = configuration.get("assay_validation_snapshot")
    try:
        assert_pipeline_components_match_runtime(snapshot, components)
    except AssayValidationError as exc:
        raise RuntimeAttestationError(
            "Persisted runtime attestation no longer matches the approved assay-validation snapshot"
        ) from exc
