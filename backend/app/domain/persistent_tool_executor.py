"""Bridge the common local executor to the durable tenant execution ledger.

The service commits PENDING and RUNNING transitions before starting a process,
then commits terminal provenance only after process completion and output
checksum verification. The caller owns artifact publication; intermediate
outputs may be retained by checksum only and must not be mistaken for durable
workflow artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.domain.container_tool_execution import (
    ContainerResourceLimits,
    EnvironmentAwareToolExecutor,
)
from backend.app.domain.execution_environments import execution_environment_profile_from_snapshot
from backend.app.infrastructure.db.models import ExecutionEnvironmentRegistration

from backend.app.domain.execution_persistence import (
    ExecutionPersistenceError,
    execution_request_fingerprint,
    fail_tool_execution,
    register_tool_execution,
    claim_tool_execution,
    complete_tool_execution,
)
from backend.app.domain.tool_execution import (
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolIdentity,
    ToolExecutor,
)


@dataclass(frozen=True)
class PersistentToolExecutionResult:
    result: ToolExecutionResult
    record_id: UUID


ArtifactPublisher = Callable[
    [ToolExecutionRequest, ToolExecutionResult, UUID],
    Mapping[str, UUID],
]


class PersistentToolExecutionService:
    """Execute one tool request under a registered environment and durable lease."""

    def __init__(
        self,
        db: Session,
        *,
        organization_id: UUID,
        analysis_id: UUID | None = None,
        case_id: UUID | None = None,
        environment_registration_id: UUID,
        worker_id: str,
        executor: ToolExecutor | None = None,
        container_limits: ContainerResourceLimits | None = None,
        artifact_publisher: ArtifactPublisher | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ExecutionPersistenceError("Persistent execution requires a stable worker identity.")
        self.db = db
        if analysis_id is None and case_id is None:
            raise ExecutionPersistenceError("Persistent execution requires a case or analysis ID.")
        self.organization_id = organization_id
        self.analysis_id = analysis_id
        self.case_id = case_id
        self.environment_registration_id = environment_registration_id
        self.worker_id = worker_id
        self.executor = executor
        self.container_limits = container_limits
        self.artifact_publisher = artifact_publisher
        self.execution_record_ids: list[UUID] = []

    def _canonical_request_snapshot(self, request: ToolExecutionRequest) -> dict:
        argv = list(request.argv)
        replacements = [(request.workspace, "$WORKSPACE")]
        replacements.extend((item.path, f"$INPUT:{item.name}") for item in request.inputs)
        replacements.extend((item.path, f"$OUTPUT:{item.name}") for item in request.outputs)
        for source, target in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
            argv = [value.replace(source, target) for value in argv]
        return {
            "workflow_id": request.workflow_id,
            "operation": request.operation,
            "argv": argv,
            "workspace": "$WORKSPACE",
            "timeout_seconds": request.timeout_seconds,
            "max_output_bytes": request.max_output_bytes,
            "request_environment": dict(request.environment),
            "resource_bindings": [
                {
                    "resource_id": item.resource_id,
                    "version": item.version,
                    "sha256": item.sha256,
                    "assembly": item.assembly,
                }
                for item in request.resources
            ],
        }

    def execute(
        self,
        profile: ToolIdentity,
        request: ToolExecutionRequest,
        *,
        artifact_publisher: ArtifactPublisher | None = None,
    ) -> PersistentToolExecutionResult:
        profile.validate()
        request.validate(profile)
        if request.organization_id != str(self.organization_id):
            raise ExecutionPersistenceError("Tool request organization does not match its persistence context.")

        executor = self.executor
        if executor is None:
            registration = self.db.get(ExecutionEnvironmentRegistration, self.environment_registration_id)
            if registration is None:
                raise ExecutionPersistenceError("Execution environment registration does not exist.")
            environment = execution_environment_profile_from_snapshot(registration.profile_json)
            environment.assert_tenant_access(self.organization_id)
            executor = EnvironmentAwareToolExecutor(
                environment,
                container_limits=self.container_limits,
            )

        input_manifest = [
            {"name": item.name, "sha256": item.sha256.lower()}
            for item in request.inputs
        ]
        request_snapshot = self._canonical_request_snapshot(request)
        fingerprint = execution_request_fingerprint(
            organization_id=self.organization_id,
            analysis_id=self.analysis_id,
            case_id=self.case_id,
            execution_id=request.execution_id,
            environment_registration_id=self.environment_registration_id,
            tool=profile,
            operation=request.operation,
            request_snapshot=request_snapshot,
            input_manifest=input_manifest,
        )
        # Preserve the pre-0064 idempotency namespace for analysis-scoped
        # callers so existing retries/replays retain their original identity.
        if self.analysis_id is not None and self.case_id is None:
            idempotency_identity = f"{self.organization_id}:{self.analysis_id}:{request.execution_id}"
        else:
            idempotency_identity = f"{self.organization_id}:case:{self.case_id}:analysis:{self.analysis_id}:{request.execution_id}"
        idempotency_key = hashlib.sha256(idempotency_identity.encode("utf-8")).hexdigest()

        record = register_tool_execution(
            self.db,
            organization_id=self.organization_id,
            analysis_id=self.analysis_id,
            case_id=self.case_id,
            execution_id=request.execution_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            environment_registration_id=self.environment_registration_id,
            tool=profile,
            operation=request.operation,
            request_snapshot=request_snapshot,
            input_manifest=input_manifest,
        )
        self.db.commit()
        if record.id not in self.execution_record_ids:
            self.execution_record_ids.append(record.id)
        if record.status == "SUCCEEDED":
            raise ExecutionPersistenceError(
                "This execution already succeeded; resume from its persisted workflow output checkpoint."
            )
        if record.status == "FAILED":
            raise ExecutionPersistenceError(
                "This execution is terminally failed; a deliberate new execution identity is required."
            )

        lease_token = claim_tool_execution(
            self.db,
            organization_id=self.organization_id,
            execution_record_id=record.id,
            worker_id=self.worker_id,
        )
        self.db.commit()

        try:
            result = executor.execute(profile, request)
        except Exception as exc:
            provenance = exc.provenance if isinstance(exc, ToolExecutionError) else None
            retryable = bool(getattr(exc, "retryable", False))
            try:
                fail_tool_execution(
                    self.db,
                    organization_id=self.organization_id,
                    execution_record_id=record.id,
                    lease_token=lease_token,
                    error_code=(
                        "TOOL_EXECUTION_RETRYABLE"
                        if retryable else "TOOL_EXECUTION_FAILED"
                    ),
                    error_message=str(exc),
                    retryable=retryable,
                    provenance=provenance,
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            raise

        publisher = artifact_publisher or self.artifact_publisher
        published: Mapping[str, UUID] = {}
        try:
            if publisher is not None:
                published = publisher(request, result, record.id)
            output_by_name = {
                item["name"]: item["sha256"].lower()
                for item in result.provenance.output_sha256
            }
            if len(output_by_name) != len(request.outputs):
                raise ExecutionPersistenceError(
                    "Executor output checksums do not cover every declared output."
                )
            output_manifest = []
            if set(published) - {item.name for item in request.outputs}:
                raise ExecutionPersistenceError(
                    "Artifact publisher returned an ID for an undeclared tool output."
                )
            if publisher is not None and set(published) != {item.name for item in request.outputs}:
                raise ExecutionPersistenceError(
                    "Artifact publisher did not persist every declared tool output."
                )
            for output in request.outputs:
                item = {
                    "name": output.name,
                    "sha256": output_by_name[output.name],
                }
                artifact_id = published.get(output.name)
                if artifact_id is not None:
                    item["artifact_id"] = str(artifact_id)
                else:
                    # Temporary/intermediate output bytes are checksum-attested
                    # in the execution record but are not claimed as retained
                    # workflow artifacts. The workflow must publish final
                    # scientific artifacts through its existing ArtifactStore.
                    item["retention"] = "EPHEMERAL_INTERMEDIATE"
                output_manifest.append(item)

            complete_tool_execution(
                self.db,
                organization_id=self.organization_id,
                execution_record_id=record.id,
                lease_token=lease_token,
                provenance=result.provenance,
                output_manifest=output_manifest,
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            try:
                fail_tool_execution(
                    self.db,
                    organization_id=self.organization_id,
                    execution_record_id=record.id,
                    lease_token=lease_token,
                    error_code="TOOL_OUTPUT_PERSISTENCE_FAILED",
                    error_message=str(exc),
                    retryable=True,
                    provenance=result.provenance,
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            raise

        return PersistentToolExecutionResult(result=result, record_id=record.id)
