"""Transactional persistence for laboratory environments and common tool executions.

The caller owns the SQLAlchemy transaction. These functions flush but never
commit, so the environment/execution state can be committed atomically with
workflow or artifact records by the orchestration layer.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.execution_environments import ExecutionEnvironmentProfile
from backend.app.domain.tool_execution import ToolIdentity
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    Case,
    ExecutionEnvironmentRegistration,
    ToolExecutionRecord,
)


class ExecutionPersistenceError(ValueError):
    """A persisted execution or environment violates ownership or lifecycle rules."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY_RE = re.compile(r"(secret|password|token|credential|api[_-]?key)", re.IGNORECASE)
_SECRET_ARG_RE = re.compile(r"(?i)(--?(?:token|password|secret|api[-_]?key)=)(.*)$")


def canonical_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash canonical JSON to obtain a stable request/profile fingerprint."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        rendered = {}
        for key, item in value.items():
            rendered[str(key)] = "[REDACTED]" if _SECRET_KEY_RE.search(str(key)) else _json_safe(item)
        return rendered
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ExecutionPersistenceError(f"Execution provenance contains unsupported value type: {type(value).__name__}")


def _safe_provenance(value: Any) -> dict[str, Any]:
    rendered = _json_safe(value)
    if not isinstance(rendered, dict):
        raise ExecutionPersistenceError("Execution provenance must be a mapping or dataclass.")
    argv = rendered.get("argv")
    if isinstance(argv, list):
        safe_argv = []
        redact_next = False
        for argument in argv:
            item = str(argument)
            if redact_next:
                safe_argv.append("[REDACTED]")
                redact_next = False
                continue
            match = _SECRET_ARG_RE.match(item)
            if match:
                safe_argv.append(match.group(1) + "[REDACTED]")
            else:
                safe_argv.append(item)
                if item.casefold() in {"--token", "--password", "--secret", "--api-key", "--api_key"}:
                    redact_next = True
        rendered["argv"] = safe_argv
    return rendered


def _require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        raise ExecutionPersistenceError(f"{label} must be a 64-character SHA-256 digest.")


def execution_request_fingerprint(
    *,
    organization_id: UUID,
    analysis_id: UUID,
    execution_id: str,
    environment_registration_id: UUID,
    tool: ToolIdentity,
    operation: str,
    request_snapshot: Mapping[str, Any],
    input_manifest: list[Mapping[str, Any]],
) -> str:
    """Derive the idempotency fingerprint from all immutable execution inputs."""
    return canonical_fingerprint({
        "organization_id": str(organization_id),
        "analysis_id": str(analysis_id),
        "execution_id": execution_id,
        "environment_registration_id": str(environment_registration_id),
        "tool": {
            "tool_id": tool.tool_id,
            "version": tool.version,
            "profile_id": tool.profile_id,
            "executable_sha256": tool.executable_sha256.lower(),
            "platform": tool.platform,
            "runtime_image_digest": tool.runtime_image_digest,
        },
        "operation": operation,
        "request_snapshot": _json_safe(request_snapshot),
        "input_manifest": _json_safe(input_manifest),
    })


def register_environment_profile(
    db: Session,
    profile: ExecutionEnvironmentProfile,
    *,
    organization_id: UUID | None,
    created_by: UUID | None = None,
) -> ExecutionEnvironmentRegistration:
    """Append one immutable profile version; repeated identical registration is idempotent."""
    profile.validate()
    if profile.owner_scope == "LABORATORY":
        if organization_id is None or profile.organization_id != organization_id:
            raise ExecutionPersistenceError("Laboratory environment must be registered by its owning organization.")
    elif organization_id is not None or profile.organization_id is not None:
        raise ExecutionPersistenceError("SIRALOOM-managed environment registration must not be tenant-bound.")

    snapshot = profile.snapshot()
    fingerprint = canonical_fingerprint(snapshot)
    query = select(ExecutionEnvironmentRegistration).where(
        ExecutionEnvironmentRegistration.environment_id == profile.environment_id,
        ExecutionEnvironmentRegistration.profile_version == profile.profile_version,
    )
    if organization_id is None:
        query = query.where(ExecutionEnvironmentRegistration.organization_id.is_(None))
    else:
        query = query.where(ExecutionEnvironmentRegistration.organization_id == organization_id)
    existing = db.scalar(query)
    if existing is not None:
        if existing.profile_fingerprint != fingerprint:
            raise ExecutionPersistenceError(
                "This environment ID/version is already registered with different profile bytes."
            )
        return existing

    row = ExecutionEnvironmentRegistration(
        id=uuid4(),
        organization_id=organization_id,
        owner_scope=profile.owner_scope,
        environment_id=profile.environment_id,
        profile_version=profile.profile_version,
        profile_fingerprint=fingerprint,
        profile_json=snapshot,
        qualification_status=profile.qualification_status,
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def register_tool_execution(
    db: Session,
    *,
    organization_id: UUID,
    analysis_id: UUID,
    execution_id: str,
    idempotency_key: str,
    request_fingerprint: str,
    environment_registration_id: UUID,
    tool: ToolIdentity,
    operation: str,
    request_snapshot: Mapping[str, Any],
    input_manifest: list[Mapping[str, Any]],
) -> ToolExecutionRecord:
    """Create a tenant-checked PENDING record, or return an identical idempotent replay."""
    tool.validate()
    _require_sha256(request_fingerprint, "Request fingerprint")
    request_fingerprint = request_fingerprint.lower()
    if not execution_id.strip() or not idempotency_key.strip() or not operation.strip():
        raise ExecutionPersistenceError("Execution ID, idempotency key and operation are required.")
    if operation not in tool.supported_operations:
        raise ExecutionPersistenceError("Tool profile does not allow the requested operation.")

    analysis_owner = db.execute(
        select(Analysis.id, Case.organization_id)
        .join(Case, Case.id == Analysis.case_id)
        .where(Analysis.id == analysis_id)
    ).one_or_none()
    if analysis_owner is None or analysis_owner.organization_id != organization_id:
        raise ExecutionPersistenceError("Analysis does not belong to the requesting organization.")

    environment = db.get(ExecutionEnvironmentRegistration, environment_registration_id)
    if environment is None:
        raise ExecutionPersistenceError("Execution environment registration does not exist.")
    if environment.owner_scope == "LABORATORY" and environment.organization_id != organization_id:
        raise ExecutionPersistenceError("Execution environment belongs to a different organization.")
    if environment.qualification_status != "ENVIRONMENT_QUALIFIED":
        raise ExecutionPersistenceError("Only environment-qualified registrations may receive executions.")
    env_snapshot = environment.profile_json
    if tool.profile_id not in env_snapshot.get("supported_tool_profile_ids", []):
        raise ExecutionPersistenceError("Tool profile is not allowlisted by the registered environment.")
    if tool.platform != env_snapshot.get("platform"):
        raise ExecutionPersistenceError("Tool and environment platforms do not match.")
    if tool.runtime_image_digest != env_snapshot.get("runtime_image_digest"):
        raise ExecutionPersistenceError("Tool and environment runtime image digests do not match.")
    approved_executable_digest = env_snapshot.get("tool_executable_sha256", {}).get(tool.profile_id)
    if approved_executable_digest != tool.executable_sha256.lower():
        raise ExecutionPersistenceError(
            "Tool executable SHA-256 does not match the environment's approved executable digest."
        )

    expected_fingerprint = execution_request_fingerprint(
        organization_id=organization_id,
        analysis_id=analysis_id,
        execution_id=execution_id,
        environment_registration_id=environment_registration_id,
        tool=tool,
        operation=operation,
        request_snapshot=request_snapshot,
        input_manifest=input_manifest,
    )
    if request_fingerprint != expected_fingerprint:
        raise ExecutionPersistenceError(
            "Request fingerprint does not match the immutable execution request contents."
        )

    existing = db.scalar(
        select(ToolExecutionRecord).where(
            ToolExecutionRecord.organization_id == organization_id,
            ToolExecutionRecord.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.request_fingerprint != request_fingerprint
            or existing.analysis_id != analysis_id
            or existing.execution_id != execution_id
            or existing.environment_registration_id != environment_registration_id
            or existing.tool_id != tool.tool_id
            or existing.tool_version != tool.version
            or existing.tool_profile_id != tool.profile_id
            or existing.executable_sha256 != tool.executable_sha256.lower()
            or existing.operation != operation
        ):
            raise ExecutionPersistenceError("Idempotency key was reused for a different execution request.")
        return existing

    duplicate_execution = db.scalar(
        select(ToolExecutionRecord).where(
            ToolExecutionRecord.organization_id == organization_id,
            ToolExecutionRecord.execution_id == execution_id,
        )
    )
    if duplicate_execution is not None:
        raise ExecutionPersistenceError("Execution ID is already registered under another idempotency key.")

    safe_inputs = _json_safe(input_manifest)
    if not isinstance(safe_inputs, list):
        raise ExecutionPersistenceError("Input manifest must be a list.")
    names: set[str] = set()
    for item in safe_inputs:
        if not isinstance(item, dict) or not item.get("name"):
            raise ExecutionPersistenceError("Every input manifest entry requires a name.")
        if item["name"] in names:
            raise ExecutionPersistenceError("Input manifest names must be unique.")
        names.add(item["name"])
        _require_sha256(item.get("sha256"), f"Input {item['name']} SHA-256")

    row = ToolExecutionRecord(
        id=uuid4(),
        execution_id=execution_id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint.lower(),
        organization_id=organization_id,
        analysis_id=analysis_id,
        environment_registration_id=environment_registration_id,
        tool_id=tool.tool_id,
        tool_version=tool.version,
        tool_profile_id=tool.profile_id,
        executable_sha256=tool.executable_sha256.lower(),
        platform=tool.platform,
        operation=operation,
        request_snapshot=_safe_provenance(request_snapshot),
        environment_snapshot=env_snapshot,
        input_manifest=safe_inputs,
        output_manifest=[],
        status="PENDING",
        attempt=0,
    )
    db.add(row)
    db.flush()
    return row


def claim_tool_execution(
    db: Session,
    *,
    organization_id: UUID,
    execution_record_id: UUID,
    worker_id: str,
    lease_seconds: int = 300,
    now: datetime | None = None,
) -> str:
    """Claim or reclaim an execution with a fencing token; return the token."""
    if not worker_id.strip() or not 1 <= lease_seconds <= 86400:
        raise ExecutionPersistenceError("Worker identity and a valid lease duration are required.")
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise ExecutionPersistenceError("Execution claim time must be timezone-aware.")
    row = db.scalar(
        select(ToolExecutionRecord)
        .where(
            ToolExecutionRecord.id == execution_record_id,
            ToolExecutionRecord.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise ExecutionPersistenceError("Execution record was not found for this organization.")
    if row.status in {"SUCCEEDED", "FAILED"}:
        raise ExecutionPersistenceError("Terminal executions cannot be claimed.")
    lease_expires_at = row.lease_expires_at
    if lease_expires_at is not None and lease_expires_at.tzinfo is None:
        # SQLite does not round-trip timezone metadata for DateTime columns.
        lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
    if row.status == "RUNNING" and lease_expires_at and lease_expires_at > observed_now:
        raise ExecutionPersistenceError("Execution is already leased by another worker.")
    if row.status not in {"PENDING", "RUNNING", "INTERRUPTED"}:
        raise ExecutionPersistenceError(f"Execution cannot be claimed from status {row.status!r}.")

    token = str(uuid4())
    row.status = "RUNNING"
    row.attempt += 1
    row.lease_owner = worker_id
    row.lease_token = token
    row.lease_expires_at = observed_now + timedelta(seconds=lease_seconds)
    row.started_at = row.started_at or observed_now
    row.completed_at = None
    row.error_code = None
    row.error_message = None
    row.updated_at = observed_now
    db.flush()
    return token


def _assert_current_lease(row: ToolExecutionRecord, lease_token: str) -> None:
    if row.status != "RUNNING" or not lease_token or row.lease_token != lease_token:
        raise ExecutionPersistenceError("Execution lease is stale or no longer owned by this worker.")


def _load_execution_for_update(
    db: Session, organization_id: UUID, execution_record_id: UUID
) -> ToolExecutionRecord:
    row = db.scalar(
        select(ToolExecutionRecord)
        .where(
            ToolExecutionRecord.id == execution_record_id,
            ToolExecutionRecord.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise ExecutionPersistenceError("Execution record was not found for this organization.")
    return row


def complete_tool_execution(
    db: Session,
    *,
    organization_id: UUID,
    execution_record_id: UUID,
    lease_token: str,
    provenance: Any,
    output_manifest: list[Mapping[str, Any]],
    now: datetime | None = None,
) -> ToolExecutionRecord:
    """Persist successful provenance only after every declared output artifact exists durably."""
    row = _load_execution_for_update(db, organization_id, execution_record_id)
    _assert_current_lease(row, lease_token)
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise ExecutionPersistenceError("Execution completion time must be timezone-aware.")
    payload = _safe_provenance(provenance)
    if payload.get("execution_id") != row.execution_id or payload.get("organization_id") != str(organization_id):
        raise ExecutionPersistenceError("Provenance execution or organization identity does not match the record.")
    expected_identity = {
        "tool_id": row.tool_id,
        "tool_version": row.tool_version,
        "profile_id": row.tool_profile_id,
        "executable_sha256": row.executable_sha256,
        "platform": row.platform,
    }
    if any(payload.get(key) != value for key, value in expected_identity.items()):
        raise ExecutionPersistenceError("Provenance tool identity does not match the registered execution.")
    if payload.get("operation") != row.operation:
        raise ExecutionPersistenceError("Provenance operation does not match the registered execution.")
    expected_workflow = row.request_snapshot.get("workflow_id")
    if expected_workflow is not None and payload.get("workflow_id") != expected_workflow:
        raise ExecutionPersistenceError("Provenance workflow identity does not match the registered request.")
    if payload.get("runtime_image_digest") != row.environment_snapshot.get("runtime_image_digest"):
        raise ExecutionPersistenceError("Provenance runtime image does not match the registered environment.")
    _require_sha256(payload.get("environment_sha256"), "Environment SHA-256")
    if payload.get("exit_code") != 0:
        raise ExecutionPersistenceError("A successful execution record requires process exit code zero.")
    _require_sha256(payload.get("stdout_sha256"), "stdout SHA-256")
    _require_sha256(payload.get("stderr_sha256"), "stderr SHA-256")
    provenance_inputs = payload.get("input_sha256", [])
    actual_inputs = {
        item.get("name"): str(item.get("sha256", "")).lower()
        for item in provenance_inputs if isinstance(item, dict)
    }
    expected_inputs = {
        item["name"]: str(item["sha256"]).lower()
        for item in row.input_manifest
    }
    if actual_inputs != expected_inputs:
        raise ExecutionPersistenceError("Provenance input checksums do not match the registered input manifest.")

    safe_outputs = _json_safe(output_manifest)
    if not isinstance(safe_outputs, list):
        raise ExecutionPersistenceError("Output manifest must be a list.")
    output_names: set[str] = set()
    artifact_ids: list[UUID] = []
    expected_hashes: dict[str, str] = {}
    for item in safe_outputs:
        if not isinstance(item, dict) or not item.get("name"):
            raise ExecutionPersistenceError("Each output must identify its name and SHA-256.")
        if not item.get("artifact_id") and item.get("retention") != "EPHEMERAL_INTERMEDIATE":
            raise ExecutionPersistenceError(
                "An output without a persisted artifact_id must be explicitly classified as an ephemeral intermediate."
            )
        name = item["name"]
        if name in output_names:
            raise ExecutionPersistenceError("Output manifest names must be unique.")
        output_names.add(name)
        _require_sha256(item.get("sha256"), f"Output {name} SHA-256")
        if item.get("artifact_id"):
            try:
                artifact_id = UUID(str(item["artifact_id"]))
            except (ValueError, TypeError) as exc:
                raise ExecutionPersistenceError(f"Output {name} has an invalid artifact ID.") from exc
            artifact_ids.append(artifact_id)
        expected_hashes[name] = item["sha256"].lower()

    artifacts = db.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids))).all() if artifact_ids else []
    by_id = {item.id: item for item in artifacts}
    if len(by_id) != len(artifact_ids):
        raise ExecutionPersistenceError("One or more declared output artifacts are not durably registered.")
    analysis_case_id = db.scalar(select(Analysis.case_id).where(Analysis.id == row.analysis_id))
    for item in safe_outputs:
        if not item.get("artifact_id"):
            continue
        artifact = by_id[UUID(str(item["artifact_id"]))]
        if artifact.analysis_id != row.analysis_id or artifact.case_id != analysis_case_id:
            raise ExecutionPersistenceError("Output artifact is not attached to this analysis and case.")
        if artifact.sha256.lower() != item["sha256"].lower():
            raise ExecutionPersistenceError("Output artifact checksum does not match the declared output manifest.")

    provenance_outputs = payload.get("output_sha256", [])
    actual_hashes = {
        item.get("name"): str(item.get("sha256", "")).lower()
        for item in provenance_outputs if isinstance(item, dict)
    }
    if actual_hashes != expected_hashes:
        raise ExecutionPersistenceError("Persisted output artifacts do not match executor output checksums.")

    row.output_manifest = safe_outputs
    row.provenance = payload
    row.exit_code = 0
    row.stdout_sha256 = payload["stdout_sha256"]
    row.stderr_sha256 = payload["stderr_sha256"]
    row.status = "SUCCEEDED"
    row.completed_at = observed_now
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = observed_now
    db.flush()
    return row


def fail_tool_execution(
    db: Session,
    *,
    organization_id: UUID,
    execution_record_id: UUID,
    lease_token: str,
    error_code: str,
    error_message: str,
    retryable: bool = False,
    provenance: Any | None = None,
    now: datetime | None = None,
) -> ToolExecutionRecord:
    """Persist a failed or interrupted attempt; retryable attempts may be reclaimed."""
    row = _load_execution_for_update(db, organization_id, execution_record_id)
    _assert_current_lease(row, lease_token)
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise ExecutionPersistenceError("Execution failure time must be timezone-aware.")
    if not error_code.strip() or not error_message.strip():
        raise ExecutionPersistenceError("Execution failure requires an error code and message.")
    payload = None
    if provenance is not None:
        payload = _safe_provenance(provenance)
        if (
            payload.get("execution_id") != row.execution_id
            or payload.get("organization_id") != str(organization_id)
            or payload.get("tool_id") != row.tool_id
            or payload.get("tool_version") != row.tool_version
            or payload.get("profile_id") != row.tool_profile_id
        ):
            raise ExecutionPersistenceError("Failure provenance identity does not match the registered execution.")
    row.status = "INTERRUPTED" if retryable else "FAILED"
    row.error_code = error_code[:128]
    row.error_message = error_message[:2000]
    if payload is not None:
        row.provenance = payload
        row.exit_code = payload.get("exit_code")
        row.stdout_sha256 = payload.get("stdout_sha256")
        row.stderr_sha256 = payload.get("stderr_sha256")
    row.completed_at = observed_now
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = observed_now
    db.flush()
    return row
