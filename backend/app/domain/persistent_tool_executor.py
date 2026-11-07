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

from backend.app.domain.execution_persistence import (
    ExecutionPersistenceError,
    execution_request_fingerprint,
    fail_tool_execution,
    register_tool_execution,
    claim_tool_execution,
    complete_tool_execution,
)
from backend.app.domain.tool_execution import (
    LocalProcessToolExecutor,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolIdentity,
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
        analysis_id: UUID,
        environment_registration_id: UUID,
        worker_id: str,
        executor: LocalProcessToolExecutor | None = None,
        artifact_publisher: ArtifactPublisher | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ExecutionPersistenceError("Persistent execution requires a stable worker identity.")
        self.db = db
        self.organization_id = organization_id
        self.analysis_id = analysis_id
        self.environment_registration_id = environment_registration_id
        self.worker_id = worker_id
        self.executor = executor or LocalProcessToolExecutor()
        self.artifact_publisher = artifact_publisher

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

        input_manifest = [
            {"name": item.name, "sha256": item.sha256.lower()}
            for item in request.inputs
        ]
        request_snapshot = {
            "workflow_id": request.workflow_id,
            "operation": request.operation,
            "argv": list(request.argv),
            "workspace": request.workspace,
            "timeout_seconds": request.timeout_seconds,
            "max_output_bytes": request.max_output_bytes,
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
        fingerprint = execution_request_fingerprint(
            organization_id=self.organization_id,
            analysis_id=self.analysis_id,
            execution_id=request.execution_id,
            environment_registration_id=self.environment_registration_id,
            tool=profile,
            operation=request.operation,
            request_snapshot=request_snapshot,
            input_manifest=input_manifest,
        )
        idempotency_key = hashlib.sha256(
            f"{self.organization_id}:{self.analysis_id}:{request.execution_id}".encode("utf-8")
        ).hexdigest()

        record = register_tool_execution(
            self.db,
            organization_id=self.organization_id,
            analysis_id=self.analysis_id,
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
            result = self.executor.execute(profile, request)
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
