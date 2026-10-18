from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.application.analysis import (
    create_analysis,
    enqueue_analysis,
    preflight_analysis_resources,
    validate_analysis_input_artifact,
)
from backend.app.application.entitlements import (
    require_analysis_quota,
    reserve_analysis_quota,
)
from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    get_accessible_analysis,
    get_analysis_variant_ids,
    require_role,
)
from backend.app.auth.principal import (
    Principal,
    get_current_principal,
    require_case_tenant,
)
from backend.app.domain.resource_deployment import resolve_resource_deployment_policy
from backend.app.domain.schemas import AnalysisCreate
from backend.app.domain.storage_capacity import (
    enforce_laboratory_capacity_policy,
    preflight_analysis_capacity,
)
from backend.app.infrastructure.db.models import (
    Analysis,
    Annotation,
    Artifact,
    Assay,
    Case,
    Variant,
    WorkflowStep,
)
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["analyses"])

TERMINAL_ANALYSIS_STATUSES = {
    "SUCCEEDED",
    "FAILED",
    "BLOCKED",
    "REQUIRES_REVIEW",
    "RESOURCE_FAILURE",
}

def _resolve_workflow_next_step(step_payloads: list[dict]) -> str | None:
    """Resolve the durable next action without allowing an older failure to mask active work."""
    for status in ("RUNNING", "RETRYING"):
        active = next((item for item in step_payloads if item["status"] == status), None)
        if active is not None:
            return active.get("next_step") or active["step_id"]

    for item in step_payloads:
        if item["status"] in {"FAILED", "BLOCKED", "REQUIRES_REVIEW", "RESOURCE_FAILURE"}:
            return item.get("next_step")

    pending = next(
        (item for item in step_payloads if item["status"] not in {"SUCCEEDED", "FAILED", "BLOCKED", "REQUIRES_REVIEW", "RESOURCE_FAILURE"}),
        None,
    )
    if pending is not None:
        return pending["step_id"]

    if step_payloads and all(item["status"] == "SUCCEEDED" for item in step_payloads):
        return "ANALYSIS_COMPLETE"
    return None


@router.post("/cases/{case_id}/analyses", status_code=201)
def create(
    case_id: str,
    payload: AnalysisCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    cid = UUID(case_id)

    case = db.get(Case, cid)

    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found",
        )

    require_case_tenant(case, principal)
    require_role(principal, CASE_WRITE_ROLES)

    require_analysis_quota(
        db,
        principal.organization_id,
    )

    if payload.assay_id:
        assay = db.get(Assay, payload.assay_id)

        if (
            not assay
            or assay.organization_id != principal.organization_id
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid assay_id for this organization",
            )

    try:
        analysis = create_analysis(
            db,
            case_id=cid,
            input_artifact_id=payload.input_artifact_id,
            assay_id=payload.assay_id,
            analysis_type=payload.analysis_type,
            workflow_id=payload.workflow_id,
            workflow_version=payload.workflow_version,
            reference_build=payload.reference_build,
            configuration=payload.configuration,
            created_by=principal.user_id,
            resource_profile_id=payload.resource_profile_id,
            commit=False,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    try:
        reserve_analysis_quota(db, principal.organization_id, commit=False)
        db.commit()
        db.refresh(analysis)
    except HTTPException:
        db.rollback()
        raise

    return {
        "analysis_id": str(analysis.id),
        "case_id": str(cid),
        "status": analysis.status,
        "analysis_version": analysis.analysis_version,
        "parent_analysis_id": str(analysis.parent_analysis_id) if analysis.parent_analysis_id else None,
        "workflow_id": analysis.workflow_id,
        "workflow_version": analysis.workflow_version,
        "reference_build": analysis.reference_build,
        "assay_id": (
            str(analysis.assay_id)
            if analysis.assay_id
            else None
        ),
        "created_at": analysis.created_at,
    }


@router.post("/analyses/{analysis_id}/start")
def start(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    analysis = get_accessible_analysis(
        analysis_id,
        db,
        principal,
    )

    require_role(
        principal,
        CASE_WRITE_ROLES,
    )

    # Preflight can persist BLOCKED and capacity state without dispatching a
    # task. Serialize that branch against duplicate starts and worker claims,
    # then make the lifecycle decision from the current database row.
    db.refresh(analysis, with_for_update=True)
    current_status = str(analysis.status)
    configuration = dict(analysis.configuration or {})
    if current_status in {"QUEUED", "RUNNING"}:
        resource_plan = configuration.get("resource_plan")
        resource_plan = resource_plan if isinstance(resource_plan, dict) else {}
        return {
            "analysis_id": str(analysis_id),
            "status": analysis.status,
            "task_id": analysis.queue_task_id,
            "resource_plan_status": resource_plan.get("status"),
            "resource_issues": resource_plan.get("issues", []),
            "capacity_preflight": configuration.get("capacity_preflight"),
        }

    if current_status not in {"CREATED", "FAILED", "RESOURCE_FAILURE", "BLOCKED"}:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis cannot be started from status {current_status}",
        )

    blocked_for_capacity = False
    if current_status == "BLOCKED":
        previous_plan = configuration.get("resource_plan")
        previous_plan = previous_plan if isinstance(previous_plan, dict) else {}
        preflight_step = db.scalar(
            select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis.id,
                WorkflowStep.step_id == "preflight",
            )
        )
        blocked_for_capacity = bool(
            preflight_step
            and preflight_step.error_code == "STORAGE_CAPACITY_PREFLIGHT_BLOCKED"
        )
        if (
            str(previous_plan.get("status") or "").upper() != "BLOCKED"
            and not blocked_for_capacity
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "A blocked analysis can only be restarted after its persisted "
                    "preflight blocker is resolved"
                ),
            )

    try:
        plan = preflight_analysis_resources(
            db,
            analysis=analysis,
            organization_id=principal.organization_id,
        )
    except (ValueError, KeyError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    configuration = dict(analysis.configuration or {})
    input_artifact_id = configuration.get("input_artifact_id")
    input_artifact = None
    if input_artifact_id:
        try:
            input_artifact = db.get(Artifact, UUID(str(input_artifact_id)))
        except (TypeError, ValueError):
            raise HTTPException(status_code=409, detail="Analysis input artifact reference is invalid")
        if input_artifact is None or input_artifact.case_id != analysis.case_id:
            raise HTTPException(status_code=409, detail="Analysis input artifact is missing or no longer belongs to this case")
        try:
            validate_analysis_input_artifact(input_artifact, analysis.reference_build)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    capacity = preflight_analysis_capacity(int(input_artifact.size_bytes or 0) if input_artifact else 0)
    deployment_policy = resolve_resource_deployment_policy(
        db,
        organization_id=principal.organization_id,
    )
    capacity = enforce_laboratory_capacity_policy(
        capacity,
        is_laboratory=deployment_policy.is_laboratory,
    )
    configuration["capacity_preflight"] = capacity
    analysis.configuration = configuration

    preflight_step = db.scalar(
        select(WorkflowStep).where(
            WorkflowStep.analysis_id == analysis.id,
            WorkflowStep.step_id == "preflight",
        )
    )
    if preflight_step is not None:
        step_metadata = dict(preflight_step.metadata_json or {})
        step_metadata["capacity_preflight"] = capacity
        preflight_step.metadata_json = step_metadata
        if capacity.get("status") == "BLOCKED":
            if not (preflight_step.error_code and str(preflight_step.error_code).startswith("RESOURCE_")):
                preflight_step.status = "BLOCKED"
                preflight_step.error_code = "STORAGE_CAPACITY_PREFLIGHT_BLOCKED"
                preflight_step.error_message = "Storage-capacity preflight is not ready. Resolve the reported capacity issues before starting analysis."
        elif preflight_step.error_code == "STORAGE_CAPACITY_PREFLIGHT_BLOCKED" and (plan is None or plan.is_ready):
            preflight_step.status = "SUCCEEDED"
            preflight_step.error_code = None
            preflight_step.error_message = None
        db.add(preflight_step)

    resource_blocked = plan is not None and not plan.is_ready
    capacity_blocked = capacity.get("status") == "BLOCKED"
    if capacity_blocked:
        analysis.status = "BLOCKED"
        analysis.completed_at = None
    elif blocked_for_capacity and not resource_blocked:
        # Capacity is an operational preflight blocker, not a scientific result.
        # Restore only this explicitly identified state before durable dispatch.
        analysis.status = "CREATED"
        analysis.completed_at = None
    db.add(analysis)

    resource_issues = [
        {
            "capability": issue.capability,
            "required": issue.required,
            "code": issue.code,
            "message": issue.message,
        }
        for issue in (plan.issues if plan is not None else [])
    ]
    if resource_blocked or capacity_blocked:
        db.commit()
        db.refresh(analysis)
        return {
            "analysis_id": str(analysis_id),
            "status": analysis.status,
            "task_id": None,
            "resource_plan_status": plan.status if plan is not None else None,
            "resource_issues": resource_issues,
            "capacity_preflight": capacity,
        }

    # Persist preflight recovery inside this transaction before enqueue_analysis
    # refreshes the locked row to fence concurrent starts.
    db.flush()
    task_id = enqueue_analysis(db, analysis)

    return {
        "analysis_id": str(analysis_id),
        "status": analysis.status,
        "task_id": task_id,
        "resource_plan_status": plan.status if plan is not None else None,
        "resource_issues": resource_issues,
        "capacity_preflight": capacity,
    }


@router.get("/analyses/{analysis_id}")
def get(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    analysis = get_accessible_analysis(
        analysis_id,
        db,
        principal,
    )

    steps = db.scalars(
        select(WorkflowStep)
        .where(WorkflowStep.analysis_id == analysis.id)
        .order_by(WorkflowStep.step_order)
    ).all()

    step_payloads = []
    for index, step in enumerate(steps):
        metadata = dict(step.metadata_json or {})
        if step.status in {"FAILED", "BLOCKED", "REQUIRES_REVIEW", "RESOURCE_FAILURE"}:
            next_step = metadata.get("next_step")
        elif step.status == "SUCCEEDED":
            next_step = steps[index + 1].step_id if index + 1 < len(steps) else "ANALYSIS_COMPLETE"
        else:
            next_step = step.step_id

        step_payloads.append(
            {
                "step_id": step.step_id,
                "status": step.status,
                "attempt": step.attempt,
                "last_heartbeat": step.last_heartbeat,
                "error_code": step.error_code,
                "error_message": step.error_message,
                "metadata": metadata,
                "next_step": next_step,
            }
        )

    workflow_next_step = _resolve_workflow_next_step(step_payloads)

    return {
        "analysis_id": str(analysis.id),
        "case_id": str(analysis.case_id),
        "status": analysis.status,
        "analysis_version": analysis.analysis_version,
        "parent_analysis_id": str(analysis.parent_analysis_id) if analysis.parent_analysis_id else None,
        "workflow_id": analysis.workflow_id,
        "workflow_version": analysis.workflow_version,
        "reference_build": analysis.reference_build,
        "queue_task_id": analysis.queue_task_id,
        "started_at": analysis.started_at,
        "completed_at": analysis.completed_at,
        "next_step": workflow_next_step,
        "steps": step_payloads,
        "capacity_preflight": (analysis.configuration or {}).get("capacity_preflight"),
    }


@router.get("/analyses/{analysis_id}/variants")
def list_variants(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    analysis = get_accessible_analysis(
        analysis_id,
        db,
        principal,
    )

    aid = analysis_id

    # The shared helper distinguishes current manifests (including an empty
    # completed normalization) from legacy analyses that have no manifest.
    manifest_variant_ids = get_analysis_variant_ids(analysis, db)
    if manifest_variant_ids is not None:
        rows = db.scalars(
            select(Variant)
            .where(Variant.id.in_(manifest_variant_ids))
            .order_by(
                Variant.chromosome,
                Variant.position,
                Variant.reference,
                Variant.alternate,
            )
        ).all()
    else:
        # Compatibility fallback for analyses created before the partition
        # manifest carried persisted variant IDs.
        rows = db.scalars(
            select(Variant)
            .join(
                Annotation,
                Annotation.variant_id == Variant.id,
            )
            .where(Annotation.analysis_id == aid)
            .distinct()
            .order_by(
                Variant.chromosome,
                Variant.position,
                Variant.reference,
                Variant.alternate,
            )
        ).all()

    return [
        {
            "variant_id": str(v.id),
            "genome_build": v.genome_build,
            "chromosome": v.chromosome,
            "position": v.position,
            "reference": v.reference,
            "alternate": v.alternate,
        }
        for v in rows
    ]
