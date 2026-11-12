"""Resolve mandatory, case-bound persistent execution context."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.domain.persistent_tool_executor import PersistentToolExecutionService
from backend.app.infrastructure.db.models import Case, ExecutionEnvironmentRegistration


class ExecutionEnvironmentAssignmentError(RuntimeError):
    """A case cannot execute scientific tools without an approved environment."""


def persistent_execution_for_case(
    db: Session,
    *,
    case: Case,
    worker_id: str,
    analysis_id=None,
) -> PersistentToolExecutionService:
    registration_id = case.execution_environment_registration_id
    if registration_id is None:
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_REQUIRED: assign an environment-qualified registration "
            "to the case before scientific processing."
        )
    registration = db.get(ExecutionEnvironmentRegistration, registration_id)
    if registration is None:
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_MISSING: the assigned execution environment registration "
            "does not exist."
        )
    if registration.owner_scope == "LABORATORY" and registration.organization_id != case.organization_id:
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_TENANT_MISMATCH: the assigned environment belongs to another laboratory."
        )
    if registration.qualification_status != "ENVIRONMENT_QUALIFIED":
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_NOT_QUALIFIED: the assigned environment is not qualified."
        )
    return PersistentToolExecutionService(
        db,
        organization_id=case.organization_id,
        case_id=case.id,
        analysis_id=analysis_id,
        environment_registration_id=registration.id,
        worker_id=worker_id,
    )
