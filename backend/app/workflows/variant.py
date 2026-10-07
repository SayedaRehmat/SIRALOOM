from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.adapters.annotation.genebe import GeneBeError, GeneBeProvider
from backend.app.adapters.annotation.vep import VEPProviderError
from backend.app.adapters.annotation.normalizer import normalize_annotation_payload
from backend.app.adapters.evidence.clinvar import ClinVarProviderError, ClinVarVCVProvider
from backend.app.adapters.clingen.variant_pathogenicity import ClinGenVariantPathogenicityProvider
from backend.app.adapters.clingen.gene_disease_validity import ClinGenGeneDiseaseValidityProvider
from backend.app.adapters.annotation.genebe_normalizer import normalize_gene_be_variant
from backend.app.adapters.population.gnomad import GnomADGraphQLProvider, GnomADProviderError, PopulationObservationData
from backend.app.config import settings
from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.normalization import NormalizationError, UnsupportedVariantError, iter_normalized_vcf
from backend.app.domain.reference import ReferenceError
from backend.app.domain.reference_package import ReferencePackageError, load_reference_package, sha256_file
from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict
from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid, normalize_build
from backend.app.domain.vcf_tools import VCFToolError, classify_records, normalize_vcf_with_bcftools
from backend.app.domain.resource_fallback import resolve_resource_with_fallback
from backend.app.domain.resource_execution import ResourceExecutionError, resolve_resource_execution, start_resource_execution, complete_resource_execution
from backend.app.domain.resource_capabilities import ResourceCapability, CapabilityRequirement
from backend.app.domain.resource_execution_plan import build_resource_execution_plan
from backend.app.domain.provider_registry import register_builtin_providers
from backend.app.domain.workflow_decision import OutcomeKind, WorkflowAction, decide_step_outcome
from backend.app.domain.workflow_decision_persistence import record_workflow_decision
from backend.app.domain.reanalysis import STEP_ORDER, snapshot_analysis_resources
from backend.app.acmg.source_assertions import persist_clingen_source_assertions
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.audit.service import AuditService
from backend.app.partition_scheduler import PartitionCapacityError, PartitionLeaseError, PartitionScheduler, configure_partition
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    Annotation,
    Artifact,
    Classification,
    Evidence,
    PopulationObservation,
    Resource,
    Variant,
    WorkflowStep,
    AnalysisPartition,
    Case,
    Report,
    ReportabilityDecision,
)

WORKFLOW_STEPS = [
    ("validate_input", 1),
    ("normalize", 2),
    ("annotate", 3),
    ("population", 4),
    ("build_evidence", 5),
    ("acmg_assessment", 6),
    ("review", 7),
    ("reportability", 8),
    ("report", 9),
    ("export_provenance", 10),
]


@dataclass
class WorkflowContext:
    db: Session
    artifacts: ArtifactStore
    audit: AuditService


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TransientWorkflowError(RuntimeError):
    """Signals a transient provider/worker failure that a durable queue may retry."""
    def __init__(self, message: str, *, countdown: int = 10):
        super().__init__(message)
        self.countdown = max(1, countdown)


class ResourceConsumptionError(RuntimeError):
    """Signals that a workflow resource is not governed or is incompatible."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _batch_key(start: int, end: int) -> str:
    return f"{start}:{end}"


def _batch_checkpoint(step: WorkflowStep, start: int, end: int) -> dict:
    batches = (step.metadata_json or {}).get("batches") or {}
    return dict(batches.get(_batch_key(start, end)) or {})


def _save_batch_checkpoint(
    db: Session,
    step: WorkflowStep,
    start: int,
    end: int,
    *,
    status: str,
    attempt: int | None = None,
    metadata: dict | None = None,
    commit: bool = True,
) -> None:
    current = dict(step.metadata_json or {})
    batches = dict(current.get("batches") or {})
    key = _batch_key(start, end)
    item = dict(batches.get(key) or {})
    item["start"] = start
    item["end"] = end
    item["status"] = status
    item["updated_at"] = _now().isoformat()
    if attempt is not None:
        item["attempt"] = attempt
    if metadata:
        item.update(metadata)
    batches[key] = item
    current["batches"] = batches
    step.metadata_json = current
    step.last_heartbeat = _now()
    step.updated_at = _now()
    db.add(step)
    if commit:
        db.commit()


def _completed_batch_keys(step: WorkflowStep) -> set[str]:
    batches = (step.metadata_json or {}).get("batches") or {}
    return {k for k, v in batches.items() if (v or {}).get("status") == "SUCCEEDED"}

def _chunk_ranges(length: int, size: int = 250):
    size = max(1, size)
    for start in range(0, length, size):
        yield start, min(length, start + size)


def _apply_reanalysis_reuse(db: Session, analysis: Analysis) -> None:
    config = analysis.configuration or {}
    reanalysis = config.get("reanalysis") or {}
    reuse_through = reanalysis.get("reuse_through_step")
    if not reuse_through or reanalysis.get("reuse_applied"):
        return

    max_order = STEP_ORDER[reuse_through]
    parent_id = UUID(str(reanalysis["parent_analysis_id"]))
    parent = db.get(Analysis, parent_id)
    if not parent:
        raise RuntimeError("Reanalysis parent analysis not found.")

    parent_steps = {s.step_id: s for s in db.scalars(select(WorkflowStep).where(WorkflowStep.analysis_id == parent_id)).all()}
    child_steps = {s.step_id: s for s in db.scalars(select(WorkflowStep).where(WorkflowStep.analysis_id == analysis.id)).all()}
    from uuid import uuid4

    for step_id, order in WORKFLOW_STEPS:
        if order > max_order:
            continue
        source, target = parent_steps.get(step_id), child_steps.get(step_id)
        if not source or not target or source.status != StepStatus.SUCCEEDED:
            continue
        target.status = StepStatus.SUCCEEDED
        target.attempt = source.attempt
        target.started_at = source.started_at
        target.completed_at = source.completed_at
        target.last_heartbeat = _now()
        target.input_artifacts = list(source.input_artifacts or [])
        target.output_artifacts = list(source.output_artifacts or [])
        target.metadata_json = {**(source.metadata_json or {}), "reused_from_analysis_id": str(parent_id), "reanalysis_reuse": True}
        target.error_code = None
        target.error_message = None
        db.add(target)

    if max_order >= STEP_ORDER["normalize"]:
        parent_normalized = _existing_normalized_artifact(db, parent_id)
        if parent_normalized and _existing_normalized_artifact(db, analysis.id) is None:
            db.add(Artifact(
                id=uuid4(), analysis_id=analysis.id, case_id=analysis.case_id,
                artifact_type=parent_normalized.artifact_type, filename=parent_normalized.filename,
                media_type=parent_normalized.media_type, size_bytes=parent_normalized.size_bytes,
                sha256=parent_normalized.sha256, storage_uri=parent_normalized.storage_uri,
                genome_build=parent_normalized.genome_build, specimen_id=parent_normalized.specimen_id,
                paired_artifact_id=parent_normalized.paired_artifact_id,
                validation_status=parent_normalized.validation_status,
                metadata_json={**(parent_normalized.metadata_json or {}), "reused_from_analysis_id": str(parent_id)},
            ))
        for src in db.scalars(select(AnalysisPartition).where(
            AnalysisPartition.analysis_id == parent_id,
            AnalysisPartition.step_id == "normalize",
        ).order_by(AnalysisPartition.ordinal)).all():
            exists = db.scalar(select(AnalysisPartition.id).where(
                AnalysisPartition.analysis_id == analysis.id,
                AnalysisPartition.step_id == "normalize",
                AnalysisPartition.partition_key == src.partition_key,
            ))
            if not exists:
                db.add(AnalysisPartition(
                    id=uuid4(), analysis_id=analysis.id, step_id="normalize",
                    partition_key=src.partition_key, ordinal=src.ordinal,
                    record_start=src.record_start, record_end=src.record_end,
                    variant_count=src.variant_count, status="SUCCEEDED",
                    input_artifact_id=src.input_artifact_id,
                    metadata_json={**(src.metadata_json or {}), "reused_from_analysis_id": str(parent_id)},
                    resource_class=src.resource_class, cpu_request=src.cpu_request,
                    memory_mb=src.memory_mb, attempt=src.attempt,
                ))

    reanalysis["reuse_applied"] = True
    config["reanalysis"] = reanalysis
    analysis.configuration = config
    db.add(analysis)
    db.commit()


def ensure_steps(db: Session, analysis_id: UUID) -> None:
    existing = {x.step_id for x in db.scalars(select(WorkflowStep).where(WorkflowStep.analysis_id == analysis_id)).all()}
    from uuid import uuid4
    for step_id, order in WORKFLOW_STEPS:
        if step_id not in existing:
            db.add(
                WorkflowStep(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    step_id=step_id,
                    step_order=order,
                    status=StepStatus.PENDING,
                    attempt=0,
                    input_artifacts=[],
                    output_artifacts=[],
                    metadata_json={},
                )
            )
    db.commit()


def mark_step(
    db: Session,
    step: WorkflowStep,
    status: StepStatus,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
) -> None:
    now = _now()
    previous = step.status
    step.status = status
    step.updated_at = now
    if status == StepStatus.RUNNING:
        step.attempt += 1
        step.started_at = step.started_at or now
        step.last_heartbeat = now
    elif status == StepStatus.SUCCEEDED:
        step.completed_at = now
        step.last_heartbeat = now
    if metadata:
        step.metadata_json = {**(step.metadata_json or {}), **metadata}
    step.error_code = error_code
    step.error_message = error_message
    db.add(step)
    db.commit()


def _apply_scientific_limitation(
    db: Session,
    step: WorkflowStep,
    *,
    outcome: OutcomeKind,
    code: str,
    message: str,
    metadata: dict | None = None,
) -> None:
    """Persist a governed scientific limitation without turning it into failure.

    The decision contract is consulted before persistence. A limitation that is
    not safe to continue from at this stage is rejected here so callers cannot
    accidentally mark an unsafe stage as successful.
    """
    decision = decide_step_outcome(step.step_id, outcome, code=code, message=message)
    record_workflow_decision(
        db,
        analysis_id=step.analysis_id,
        step_id=step.step_id,
        attempt=step.attempt,
        outcome=outcome,
        decision=decision,
        metadata=metadata,
    )
    if decision.action is not WorkflowAction.CONTINUE_WITH_LIMITATION:
        raise RuntimeError(
            f"Scientific limitation {outcome.value} is not continuation-safe for step "
            f"{step.step_id}: {decision.action.value}"
        )
    mark_step(
        db,
        step,
        StepStatus.SUCCEEDED,
        error_code=decision.code,
        error_message=decision.message,
        metadata={
            **(metadata or {}),
            "scientific_outcome": outcome.value,
            "workflow_action": decision.action.value,
            "scientific_limitation": True,
        },
    )


def _ensure_execution_partitions(db: Session, analysis_id: UUID, source_step: str, target_step: str) -> None:
    """Clone the normalized manifest into an independently leased execution plan."""
    source = db.scalars(
        select(AnalysisPartition).where(
            AnalysisPartition.analysis_id == analysis_id,
            AnalysisPartition.step_id == source_step,
        ).order_by(AnalysisPartition.ordinal)
    ).all()
    existing = db.scalar(
        select(func.count(AnalysisPartition.id)).where(
            AnalysisPartition.analysis_id == analysis_id,
            AnalysisPartition.step_id == target_step,
        )
    ) or 0
    if existing == len(source) and source:
        return
    if existing:
        db.query(AnalysisPartition).filter(
            AnalysisPartition.analysis_id == analysis_id,
            AnalysisPartition.step_id == target_step,
        ).delete(synchronize_session=False)
    from uuid import uuid4
    for src in source:
        part = AnalysisPartition(
            id=uuid4(), analysis_id=analysis_id, step_id=target_step,
            partition_key=src.partition_key, ordinal=src.ordinal,
            record_start=src.record_start, record_end=src.record_end,
            variant_count=src.variant_count, status="READY",
            input_artifact_id=src.input_artifact_id,
            metadata_json={"source_partition": str(src.id), "genome_build": (src.metadata_json or {}).get("genome_build")},
        )
        configure_partition(part, settings.partition_default_resource_class)
        db.add(part)
    db.commit()


def recover_interrupted_execution(db: Session, analysis_id: UUID) -> bool:
    """Recover durable execution state after Celery redelivery of a lost worker task.

    A late-acknowledged task can be redelivered after an abrupt worker loss. The
    database may still contain RUNNING workflow steps and partition leases owned
    by the lost execution. Those leases must be released before the redelivered
    task resumes; otherwise the scheduler can see stale capacity and the workflow
    can remain falsely RUNNING.
    """
    # Serialize recovery itself. Multiple Celery redeliveries can enter this
    # function after the execution fence has already admitted RUNNING retries.
    # The analysis row is the durable recovery mutex: once the first recovery
    # commits the affected steps/partitions, a concurrent redelivery must see
    # the recovered state and become a no-op rather than recording duplicate
    # recovery events or mutating the same leases twice.
    analysis = db.get(Analysis, analysis_id, with_for_update=True)
    if not analysis:
        return False
    db.refresh(analysis, with_for_update=True)

    running_steps = db.scalars(
        select(WorkflowStep)
        .where(
            WorkflowStep.analysis_id == analysis_id,
            WorkflowStep.status == StepStatus.RUNNING,
        )
        .with_for_update()
    ).all()
    running_partitions = db.scalars(
        select(AnalysisPartition)
        .where(
            AnalysisPartition.analysis_id == analysis_id,
            AnalysisPartition.status == "RUNNING",
        )
        .with_for_update()
    ).all()

    if not running_steps and not running_partitions:
        return False

    recovery_time = _now()
    for step in running_steps:
        step.status = StepStatus.RETRYING
        step.error_code = "WORKER_INTERRUPTED"
        step.error_message = "Previous worker execution was interrupted; durable state is being resumed."
        step.metadata_json = {
            **(step.metadata_json or {}),
            "next_step": step.step_id,
            "recovery": "CELERY_REDELIVERY",
            "recovered_at": recovery_time.isoformat(),
        }
        step.updated_at = recovery_time
        step.last_heartbeat = recovery_time
        db.add(step)

    for partition in running_partitions:
        partition.status = "READY"
        partition.lease_owner = None
        partition.lease_token = None
        partition.lease_expires_at = None
        partition.error_code = "WORKER_INTERRUPTED"
        partition.error_message = "Previous worker execution was interrupted; partition returned to durable scheduler queue."
        partition.updated_at = recovery_time
        db.add(partition)

    analysis.status = AnalysisStatus.RUNNING
    analysis.completed_at = None
    db.add(analysis)

    AuditService(db).record(
        event_type="WORKFLOW_WORKER_RECOVERY",
        case_id=analysis.case_id,
        analysis_id=analysis.id,
        actor_type="SYSTEM",
        actor_id="workflow-recovery",
        reason="Celery redelivery detected interrupted worker execution",
        payload={
            "recovered_steps": [step.step_id for step in running_steps],
            "recovered_partitions": len(running_partitions),
            "next_step": running_steps[0].step_id if running_steps else None,
        },
    )
    db.commit()
    return True


def run_variant_analysis(analysis_id: UUID) -> None:
    from backend.app.infrastructure.db.session import SessionLocal

    db = SessionLocal()
    try:
        analysis = db.get(Analysis, analysis_id)
        if not analysis:
            raise RuntimeError(f"Analysis not found: {analysis_id}")

        artifacts = ArtifactStore(settings.artifact_root)
        audit = AuditService(db)
        ctx = WorkflowContext(db=db, artifacts=artifacts, audit=audit)
        ensure_steps(db, analysis_id)
        _apply_reanalysis_reuse(db, analysis)

        input_artifact_id = analysis.configuration["input_artifact_id"]
        input_artifact = db.get(Artifact, UUID(str(input_artifact_id)))
        if not input_artifact:
            raise RuntimeError("Input artifact not found")
        input_path = Path(input_artifact.storage_uri.removeprefix("file://"))
        if not input_path.is_file():
            raise RuntimeError(f"Input artifact path does not exist: {input_path}")

        if analysis.status not in {AnalysisStatus.SUCCEEDED, AnalysisStatus.REQUIRES_REVIEW}:
            analysis.status = AnalysisStatus.RUNNING
            analysis.started_at = analysis.started_at or _now()
            db.commit()
            audit.record(
                event_type="WORKFLOW_STARTED",
                case_id=analysis.case_id,
                analysis_id=analysis.id,
                actor_type="SYSTEM",
                actor_id="workflow",
            )
            db.commit()

        # 1. Validate the source VCF before scientific transformation.
        validation_step = _step(db, analysis.id, "validate_input")
        if validation_step.status != StepStatus.SUCCEEDED:
            mark_step(db, validation_step, StepStatus.RUNNING)
            try:
                profile = validate_vcf_strict(str(input_path))
                validation_step.input_artifacts = [str(input_artifact.id)]
                validation_step.output_artifacts = [str(input_artifact.id)]
                mark_step(
                    db,
                    validation_step,
                    StepStatus.SUCCEEDED,
                    metadata={"variant_count": profile["records"], "validation": "PASS", "validation_profile": profile},
                )
                audit.record(
                    event_type="ARTIFACT_VALIDATED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="vcf-validator",
                    subject_type="ARTIFACT",
                    subject_id=str(input_artifact.id),
                    input_artifacts=[{"artifact_id": str(input_artifact.id), "sha256": input_artifact.sha256}],
                    payload={"validation_profile": profile},
                )
                db.commit()
            except StrictVCFValidationError as exc:
                mark_step(
                    db,
                    validation_step,
                    StepStatus.BLOCKED,
                    error_code=exc.code,
                    error_message=str(exc),
                    metadata={"next_step": "VALID_VCF_REQUIRED"},
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="WORKFLOW_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="vcf-validator",
                    reason=str(exc),
                    payload={"error_code": exc.code, "next_step": "VALID_VCF_REQUIRED"},
                )
                db.commit()
                return
            except Exception as exc:
                mark_step(db, validation_step, StepStatus.FAILED, error_code="VCF_VALIDATION_UNEXPECTED_ERROR", error_message=str(exc))
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(
                    event_type="WORKFLOW_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="vcf-validator",
                    reason=str(exc),
                )
                db.commit()
                return

        # 2. Reference-aware normalization + bounded-memory variant indexing.
        # M13 never retains the complete normalized variant set in Python memory.
        normalization_step = _step(db, analysis.id, "normalize")
        normalized_artifact = _existing_normalized_artifact(db, analysis.id)
        reference_build = normalize_build(analysis.reference_build)
        reference_resource_id = analysis.configuration.get("reference_resource_id")
        partition_size = min(max(1, int(analysis.configuration.get("partition_size", 500) or 500)), 1000)

        if normalization_step.status != StepStatus.SUCCEEDED:
            mark_step(db, normalization_step, StepStatus.RUNNING)
            try:
                case = db.get(Case, analysis.case_id)
                if case is None:
                    raise ReferencePackageError(
                        "Analysis case was not found while resolving the organization-approved reference package.",
                        code="CASE_NOT_FOUND",
                    )
                try:
                    requested_reference = db.get(Resource, UUID(str(reference_resource_id))) if reference_resource_id else None
                except (TypeError, ValueError) as exc:
                    raise ReferencePackageError(
                        f"Invalid reference package resource ID: {reference_resource_id!r}.",
                        code="REFERENCE_PACKAGE_INVALID",
                    ) from exc
                if requested_reference is None:
                    raise ReferencePackageError(
                        "The configured reference package resource was not found.",
                        code="REFERENCE_PACKAGE_NOT_FOUND",
                    )
                resolution = resolve_resource_with_fallback(
                    db,
                    organization_id=case.organization_id,
                    requested_resource_id=reference_resource_id,
                    expected_type="REFERENCE_PACKAGE",
                    expected_build=reference_build,
                    expected_provider=requested_reference.provider,
                )
                record_workflow_decision(
                    db,
                    analysis_id=analysis.id,
                    step_id="normalize",
                    attempt=normalization_step.attempt,
                    outcome=OutcomeKind.RESOURCE_UNAVAILABLE if resolution.used_fallback or resolution.resource is None else OutcomeKind.SUCCESS,
                    decision=resolution.decision,
                    resource_id=resolution.requested_resource_id,
                    fallback_resource_id=resolution.fallback_resource_id,
                    metadata={
                        "resource_type": "REFERENCE_PACKAGE",
                        "reference_build": reference_build,
                        "fallback_used": resolution.used_fallback,
                    },
                )
                db.commit()
                if resolution.resource is None:
                    status = (
                        StepStatus.REQUIRES_REVIEW
                        if resolution.decision.action is WorkflowAction.REQUIRE_HUMAN_REVIEW
                        else StepStatus.RESOURCE_FAILURE
                    )
                    mark_step(
                        db,
                        normalization_step,
                        status,
                        error_code=resolution.decision.code,
                        error_message=resolution.decision.message,
                        metadata={
                            "next_action": resolution.decision.action.value,
                            "requested_resource_id": str(reference_resource_id),
                        },
                    )
                    analysis.status = (
                        AnalysisStatus.REQUIRES_REVIEW
                        if status is StepStatus.REQUIRES_REVIEW
                        else AnalysisStatus.RESOURCE_FAILURE
                    )
                    analysis.completed_at = None
                    db.commit()
                    audit.record(
                        event_type="NORMALIZATION_RESOURCE_DECISION",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SYSTEM",
                        actor_id="reference-resource",
                        reason=resolution.decision.message,
                        payload={
                            "action": resolution.decision.action.value,
                            "code": resolution.decision.code,
                            "requested_resource_id": str(reference_resource_id),
                        },
                    )
                    db.commit()
                    return

                selected_reference_resource = resolution.resource
                reference_package = load_reference_package(
                    db,
                    resource_id=selected_reference_resource.id,
                    expected_genome_build=reference_build,
                    allow_approved_qualified=resolution.used_fallback,
                )
                reference_fasta_path = Path(reference_package["fasta_path"])

                # The reference package is a governed executable resource. The
                # runtime contract must be the same contract that technical
                # qualification approved; workflow settings may not reconstruct
                # provider identity or local resource location.
                reference_execution = resolve_resource_execution(
                    db,
                    resource=selected_reference_resource,
                )
                if reference_execution.contract.access_method in {"LOCAL", "FILE", "LOCAL_ONLY"}:
                    contract_location = reference_execution.contract.location or ""
                    normalized_contract_location = str(Path(contract_location.removeprefix("file://")).resolve())
                    normalized_reference_location = str(reference_fasta_path.resolve())
                    if normalized_contract_location != normalized_reference_location:
                        raise ResourceExecutionError(
                            "Qualified reference execution location does not match the "
                            f"validated FASTA location: {contract_location!r} != "
                            f"{str(reference_fasta_path)!r}."
                        )

                reference_contigs = {item["name"] for item in reference_package["contigs"]}

                # Re-validate against the selected package so build/contig compatibility
                # is established before bcftools is allowed to transform the VCF.
                package_profile = validate_vcf_strict(
                    str(input_path),
                    reference_contigs=reference_contigs,
                )
            except ReferencePackageError as exc:
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.BLOCKED,
                    error_code=exc.code,
                    error_message=str(exc),
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="WORKFLOW_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="reference-package",
                    reason=str(exc),
                    payload={"error_code": exc.code, "reference_build": reference_build},
                )
                db.commit()
                return
            except StrictVCFValidationError as exc:
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.BLOCKED,
                    error_code=exc.code,
                    error_message=str(exc),
                    metadata={"next_step": "VALID_VCF_REQUIRED"},
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="NORMALIZATION_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="vcf-validator",
                    reason=str(exc),
                    payload={
                        "error_code": exc.code,
                        "reference_build": reference_build,
                        "next_step": "VALID_VCF_REQUIRED",
                    },
                )
                db.commit()
                return
            except ResourceExecutionError as exc:
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.RESOURCE_FAILURE,
                    error_code="REFERENCE_EXECUTION_CONTRACT_INVALID",
                    error_message=str(exc),
                    metadata={
                        "resource_id": str(selected_reference_resource.id),
                        "requested_resource_id": str(reference_resource_id),
                        "fallback_used": resolution.used_fallback,
                        "next_action": WorkflowAction.REQUEST_LAB_ACTION.value,
                    },
                )
                analysis.status = AnalysisStatus.RESOURCE_FAILURE
                analysis.completed_at = None
                db.commit()
                audit.record(
                    event_type="NORMALIZATION_RESOURCE_EXECUTION_INVALID",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="reference-resource",
                    reason=str(exc),
                    payload={
                        "error_code": "REFERENCE_EXECUTION_CONTRACT_INVALID",
                        "resource_id": str(selected_reference_resource.id),
                        "requested_resource_id": str(reference_resource_id),
                        "fallback_used": resolution.used_fallback,
                    },
                )
                db.commit()
                return

            temp_path: Path | None = None
            try:
                suffix = ".vcf.gz"
                with NamedTemporaryFile(prefix="siraloom-normalized-", suffix=suffix, delete=False) as temp:
                    temp_path = Path(temp.name)

                profile = classify_records(input_path)
                if profile["gvcf_markers"]:
                    raise UnsupportedVariantError(
                        "GVCF input detected. Phase 1 requires a genotyped VCF; "
                        "GVCF reference blocks must first pass the appropriate "
                        "genotyping/joint-genotyping workflow.",
                        code="UNSUPPORTED_GVCF_INPUT",
                    )
                if profile["symbolic_records"]:
                    raise UnsupportedVariantError(
                        "Symbolic/breakend variants detected. Phase 1 currently "
                        "normalizes SNVs and short indels; SV/CNV records require "
                        "the dedicated structural-variant workflow.",
                        code="UNSUPPORTED_STRUCTURAL_VARIANT",
                    )

                request_material = {
                    "input_artifact_sha256": input_artifact.sha256,
                    "reference_package_checksum": reference_package["package_checksum"],
                    "reference_fasta_sha256": reference_package["fasta_sha256"],
                    "bcftools_version": settings.bcftools_version,
                    "execution_contract_hash": reference_execution.contract_hash,
                }
                request_fingerprint = hashlib.sha256(
                    json.dumps(request_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()

                execution_record = start_resource_execution(
                    db,
                    analysis_id=analysis.id,
                    step_id="normalize",
                    attempt=normalization_step.attempt,
                    resolved=reference_execution,
                    requested_resource_id=resolution.requested_resource_id,
                    fallback_resource_id=resolution.fallback_resource_id,
                    batch_key="reference-vcf",
                    metadata={
                        "resource_type": "REFERENCE_PACKAGE",
                        "genome_build": reference_build,
                        "request_material": request_material,
                    },
                )
                db.commit()

                try:
                    normalization_stats = normalize_vcf_with_bcftools(
                        input_path,
                        temp_path,
                        reference_fasta=reference_fasta_path,
                        expected_bcftools_version=settings.bcftools_version,
                    )
                    response_sha256 = sha256_file(temp_path)
                    complete_resource_execution(
                        db,
                        execution_record,
                        status="SUCCEEDED",
                        request_fingerprint=request_fingerprint,
                        response_sha256=response_sha256,
                    )
                    db.commit()
                except Exception as exc:
                    complete_resource_execution(
                        db,
                        execution_record,
                        status="FAILED",
                        error_code=getattr(exc, "code", None) or "REFERENCE_NORMALIZATION_EXECUTION_FAILED",
                        error_message=str(exc),
                    )
                    db.commit()
                    raise

                normalized_artifact = artifacts.put_file(
                    db=db, case_id=analysis.case_id, analysis_id=analysis.id, source_path=temp_path,
                    filename="normalized.vcf.gz",
                    artifact_type="NORMALIZED_VCF", media_type="application/gzip",
                    genome_build=reference_build,
                    metadata={
                        "normalization_version": "2.2",
                        "record_count": profile["records"],
                        "streaming": True,
                        "reference_source": "PINNED_REFERENCE_PACKAGE",
                        "reference_package_id": reference_package["resource_id"],
                        "reference_package_version": reference_package["version"],
                        "reference_package_checksum": reference_package["package_checksum"],
                        "reference_fasta_sha256": reference_package["fasta_sha256"],
                        "reference_fai_sha256": reference_package["fai_sha256"],
                        "reference_contigs_sha256": reference_package["contigs_sha256"],
                        "normalization_tool": normalization_stats["tool"],
                        "normalization_tool_version": normalization_stats["tool_version"],
                        "normalization_expected_tool_version": normalization_stats["expected_tool_version"],
                        "normalization_command": normalization_stats["command"],
                        "compression": normalization_stats["compression"],
                        "index": normalization_stats["index"],
                        "execution_contract": reference_execution.snapshot,
                        "execution_contract_hash": reference_execution.contract_hash,
                    },
                )
                index_path = Path(normalization_stats["index_path"])
                index_artifact = artifacts.put_file(
                    db=db, case_id=analysis.case_id, analysis_id=analysis.id, source_path=index_path,
                    filename="normalized.vcf.gz.csi",
                    artifact_type="VCF_INDEX", media_type="application/octet-stream",
                    genome_build=reference_build, paired_artifact_id=normalized_artifact.id,
                    metadata={
                        "index_type": normalization_stats["index"],
                        "indexed_artifact_id": str(normalized_artifact.id),
                        "normalization_tool": normalization_stats["tool"],
                        "normalization_tool_version": normalization_stats["tool_version"],
                        "reference_package_checksum": reference_package["package_checksum"],
                    },
                )
                normalized_artifact.paired_artifact_id = index_artifact.id
                db.add(normalized_artifact)
                normalization_step.input_artifacts = [str(input_artifact.id)]
                normalization_step.output_artifacts = [str(normalized_artifact.id), str(index_artifact.id)]
                fallback_metadata = {
                    "requested_resource_id": str(resolution.requested_resource_id),
                    "selected_resource_id": str(selected_reference_resource.id),
                    "fallback_used": resolution.used_fallback,
                    "decision_action": resolution.decision.action.value,
                }
                mark_step(db, normalization_step, StepStatus.SUCCEEDED, metadata={"normalization": "REFERENCE_AWARE", "resource_resolution": fallback_metadata, "record_count": profile["records"], "streaming": True, "partition_size": partition_size, "reference_source": "PINNED_REFERENCE_PACKAGE", "reference_package_id": reference_package["resource_id"], "reference_package_version": reference_package["version"], "reference_package_checksum": reference_package["package_checksum"], "reference_fasta_sha256": reference_package["fasta_sha256"], "reference_fai_sha256": reference_package["fai_sha256"], "reference_contigs_sha256": reference_package["contigs_sha256"], "reference_contig_policy": reference_package["contig_policy"], "reference_package_profile": package_profile, "normalization_tool": normalization_stats["tool"], "normalization_tool_version": normalization_stats["tool_version"], "normalization_expected_tool_version": normalization_stats["expected_tool_version"], "normalization_command": normalization_stats["command"], "execution_contract": reference_execution.snapshot, "execution_contract_hash": reference_execution.contract_hash, "input_profile": profile})
                audit.record(event_type="NORMALIZATION_COMPLETED", case_id=analysis.case_id, analysis_id=analysis.id, actor_type="SYSTEM", actor_id="siraloom-normalizer", input_artifacts=[{"artifact_id": str(input_artifact.id), "sha256": input_artifact.sha256}], output_artifacts=[{"artifact_id": str(normalized_artifact.id), "sha256": normalized_artifact.sha256}], workflow={"step": "normalize", "version": "2.1"}, payload={"record_count": profile["records"], "streaming": True, "reference_source": "PINNED_REFERENCE_PACKAGE", "reference_package_id": reference_package["resource_id"], "reference_package_version": reference_package["version"], "reference_package_checksum": reference_package["package_checksum"], "reference_fasta_sha256": reference_package["fasta_sha256"], "reference_fai_sha256": reference_package["fai_sha256"], "reference_contigs_sha256": reference_package["contigs_sha256"], "normalization_tool": normalization_stats["tool"], "normalization_tool_version": normalization_stats["tool_version"], "normalization_command": normalization_stats["command"], "execution_contract": reference_execution.snapshot, "execution_contract_hash": reference_execution.contract_hash, "input_profile": profile})
                db.commit()
            except UnsupportedVariantError as exc:
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.BLOCKED,
                    error_code=exc.code,
                    error_message=str(exc),
                    metadata={"next_step": "SUPPORTED_INPUT_REQUIRED"},
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="NORMALIZATION_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="siraloom-normalizer",
                    reason=str(exc),
                    payload={"error_code": exc.code, "next_step": "SUPPORTED_INPUT_REQUIRED"},
                )
                db.commit()
                return
            except (NormalizationError, ReferenceError, ReferencePackageError, VCFToolError) as exc:
                error_code = getattr(exc, "code", None) or "NORMALIZATION_FAILED"
                mark_step(db, normalization_step, StepStatus.FAILED, error_code=error_code, error_message=str(exc))
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(event_type="NORMALIZATION_FAILED", case_id=analysis.case_id, analysis_id=analysis.id, actor_type="SYSTEM", actor_id="siraloom-normalizer", reason=str(exc))
                db.commit()
                return
            except Exception as exc:
                # Catch-all: anything unexpected here (a bug, an artifact-storage failure,
                # etc.) must still mark *this step* FAILED with a message, or the UI is
                # left showing "Running" forever while the outer handler only flips
                # analysis.status. See NORMALIZATION_FAILED/REFERENCE errors above for the
                # expected-error path; this is the safety net for everything else.
                mark_step(db, normalization_step, StepStatus.FAILED, error_code="NORMALIZATION_UNEXPECTED_ERROR", error_message=str(exc))
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(event_type="NORMALIZATION_FAILED", case_id=analysis.case_id, analysis_id=analysis.id, actor_type="SYSTEM", actor_id="siraloom-normalizer", reason=str(exc))
                db.commit()
                return
            finally:
                if temp_path and temp_path.exists():
                    temp_path.unlink()
        elif normalized_artifact is None:
            raise RuntimeError("Normalization step is marked complete but normalized artifact is missing")

        normalized_path = Path(normalized_artifact.storage_uri.removeprefix("file://"))
        if not normalized_path.is_file():
            raise RuntimeError(f"Normalized artifact path does not exist: {normalized_path}")

        # Build/rebuild a durable logical partition manifest and persist canonical
        # Variant identities batch-by-batch. This is the memory boundary for all
        # downstream steps; only one bounded partition is resident at a time.
        existing_partitions = db.scalars(select(AnalysisPartition).where(AnalysisPartition.analysis_id == analysis.id, AnalysisPartition.step_id == "normalize").order_by(AnalysisPartition.ordinal)).all()
        if not existing_partitions or sum(p.variant_count for p in existing_partitions) != int((normalization_step.metadata_json or {}).get("record_count", 0) or 0):
            db.query(AnalysisPartition).filter(AnalysisPartition.analysis_id == analysis.id, AnalysisPartition.step_id == "normalize").delete(synchronize_session=False)
            db.commit()
            existing_partitions = []

        ordinal = 0
        total_variants = 0
        for start, batch in _iter_variant_batches(normalized_path, reference_build, partition_size):
            end = start + len(batch)
            partition_key = _batch_key(start, end)
            part = db.scalar(select(AnalysisPartition).where(AnalysisPartition.analysis_id == analysis.id, AnalysisPartition.step_id == "normalize", AnalysisPartition.partition_key == partition_key))
            if part is None:
                part = AnalysisPartition(id=__import__("uuid").uuid4(), analysis_id=analysis.id, step_id="normalize", partition_key=partition_key, ordinal=ordinal, record_start=start, record_end=end, variant_count=len(batch), status="READY", input_artifact_id=normalized_artifact.id, metadata_json={"genome_build": reference_build})
                db.add(part)
            else:
                part.status = "READY"
                part.variant_count = len(batch)
                part.input_artifact_id = normalized_artifact.id
            rows = []
            for v in batch:
                key = canonical_key(v.genome_build, v.chromosome, v.position, v.reference, v.alternate)
                row = db.scalar(select(Variant).where(Variant.canonical_key == key))
                if row is None:
                    row = Variant(id=stable_variant_uuid(key), genome_build=reference_build, chromosome=v.chromosome, position=v.position, reference=v.reference, alternate=v.alternate, normalization_status="NORMALIZED", canonical_key=key, identifiers={"canonical_key_sha256": __import__("hashlib").sha256(key.encode()).hexdigest()})
                    db.add(row)
                    db.flush()
                rows.append(row.id)
            part.metadata_json = {**(part.metadata_json or {}), "variant_ids": [str(x) for x in rows]}
            total_variants += len(batch)
            ordinal += 1
            db.commit()

        normalization_step.metadata_json = {**(normalization_step.metadata_json or {}), "partition_count": ordinal, "record_count": total_variants, "partition_size": partition_size, "streaming": True}
        normalization_step.last_heartbeat = _now()
        db.commit()
        _ensure_execution_partitions(db, analysis.id, "normalize", "annotate")

        # 3. Annotation is selected from the governed execution plan.
        # GeneBe is a SIRALOOM trial provider only. Laboratory deployments use
        # only organization-approved annotation resources with real provider
        # implementations (for example, VEP).
        annotation_step = _step(db, analysis.id, "annotate")
        provider = None
        annotation_resource = None
        if annotation_step.status != StepStatus.SUCCEEDED:
            mark_step(db, annotation_step, StepStatus.RUNNING)
            try:
                case = db.get(Case, analysis.case_id)
                if case is None:
                    raise ResourceConsumptionError(
                        "CASE_NOT_FOUND",
                        "Analysis case was not found while resolving the annotation resource.",
                    )

                registry = register_builtin_providers()
                plan = build_resource_execution_plan(
                    db,
                    organization_id=case.organization_id,
                    requirements=(
                        CapabilityRequirement(ResourceCapability.ANNOTATION, required=True),
                    ),
                )
                candidates = plan.for_capability(ResourceCapability.ANNOTATION)
                if not candidates:
                    raise ResourceConsumptionError(
                        "ANNOTATION_PROVIDER_UNAVAILABLE",
                        "No executable annotation provider is registered for this deployment.",
                    )

                requested_annotation_resource_id = (analysis.configuration or {}).get(
                    "annotation_resource_id"
                )
                selected = None
                if requested_annotation_resource_id:
                    for candidate in candidates:
                        if str(candidate.resource.id) == str(requested_annotation_resource_id):
                            selected = candidate
                            break
                if selected is None:
                    selected = candidates[0]

                annotation_resource = selected.resource
                annotation_execution = resolve_resource_execution(
                    db,
                    resource=annotation_resource,
                )
                implementation = registry.require(
                    provider_id=annotation_execution.contract.provider_id,
                    provider_version=annotation_execution.contract.provider_version,
                )
                provider = implementation.factory(annotation_execution.contract)

                if not hasattr(provider, "annotate"):
                    raise ResourceConsumptionError(
                        "ANNOTATION_PROVIDER_NOT_EXECUTABLE",
                        f"Provider {annotation_execution.contract.provider_id} has no batch annotation operation.",
                    )

                batch_limit = (
                    min(max(1, settings.genebe_max_batch), 1000)
                    if provider.provider_id == "GeneBe"
                    else 250
                )
                requested_annotation_resource_id = str(annotation_resource.id)

                resolution = resolve_resource_with_fallback(
                    db,
                    organization_id=case.organization_id,
                    requested_resource_id=requested_annotation_resource_id,
                    expected_type="ANNOTATION",
                    expected_build=normalize_build(analysis.reference_build),
                    expected_provider=annotation_resource.provider,
                    expected_provider_version=annotation_execution.contract.provider_version,
                )
                record_workflow_decision(
                    db,
                    analysis_id=analysis.id,
                    step_id="annotate",
                    attempt=annotation_step.attempt,
                    outcome=(
                        OutcomeKind.RESOURCE_UNAVAILABLE
                        if resolution.used_fallback or resolution.resource is None
                        else OutcomeKind.SUCCESS
                    ),
                    decision=resolution.decision,
                    resource_id=resolution.requested_resource_id,
                    fallback_resource_id=resolution.fallback_resource_id,
                    metadata={
                        "capability": ResourceCapability.ANNOTATION.value,
                        "provider": annotation_resource.provider,
                        "provider_version": annotation_execution.contract.provider_version,
                        "reference_build": normalize_build(analysis.reference_build),
                        "deployment_profile": plan.profile_type,
                    },
                )
                db.commit()

                if resolution.resource is None:
                    raise ResourceConsumptionError(
                        resolution.decision.code,
                        resolution.decision.message,
                    )
                annotation_resource = resolution.resource
                annotation_execution = resolve_resource_execution(
                    db,
                    resource=annotation_resource,
                )
                implementation = registry.require(
                    provider_id=annotation_execution.contract.provider_id,
                    provider_version=annotation_execution.contract.provider_version,
                )
                provider = implementation.factory(annotation_execution.contract)
            except (ResourceConsumptionError, ResourceExecutionError) as exc:
                mark_step(
                    db,
                    annotation_step,
                    StepStatus.BLOCKED,
                    error_code=getattr(exc, "code", "ANNOTATION_RESOURCE_UNAVAILABLE"),
                    error_message=str(exc),
                    metadata={"next_step": "RESOURCE_REQUIRED"},
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="ANNOTATION_RESOURCE_DECISION",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="resource-registry",
                    reason=str(exc),
                )
                db.commit()
                return

                annotation_resource = resolution.resource
                try:
                    annotation_execution = resolve_resource_execution(db, resource=annotation_resource)
                    provider = registry.require(provider_id=annotation_execution.contract.provider_id, provider_version=annotation_execution.contract.provider_version).factory(annotation_execution.contract)
                except (ResourceExecutionError, GeneBeError) as exc:
                    mark_step(db, annotation_step, StepStatus.RESOURCE_FAILURE, error_code="ANNOTATION_EXECUTION_CONTRACT_INVALID", error_message=str(exc), metadata={"next_step": "ANNOTATION_RESOURCE_REVIEW"})
                    analysis.status = AnalysisStatus.RESOURCE_FAILURE
                    db.commit()
                    audit.record(event_type="ANNOTATION_EXECUTION_CONTRACT_INVALID", case_id=analysis.case_id, analysis_id=analysis.id, actor_type="SYSTEM", actor_id="resource-registry", reason=str(exc), payload={"resource_id": str(annotation_resource.id)})
                    db.commit()
                    return

                if resolution.used_fallback:
                    annotation_step.metadata_json = {
                        **(annotation_step.metadata_json or {}),
                        "resource_fallback": {
                            "requested_resource_id": str(resolution.requested_resource_id),
                            "fallback_resource_id": str(resolution.fallback_resource_id),
                            "action": resolution.decision.action.value,
                        },
                    }
                    db.add(annotation_step)
                    db.commit()
                    audit.record(
                        event_type="ANNOTATION_RESOURCE_FALLBACK",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SYSTEM",
                        actor_id="resource-registry",
                        reason=resolution.decision.message,
                        payload={
                            "requested_resource_id": str(resolution.requested_resource_id),
                            "fallback_resource_id": str(resolution.fallback_resource_id),
                            "provider": provider.provider_id,
                            "reference_build": normalize_build(analysis.reference_build),
                        },
                    )
                    db.commit()

                # One streamed iterator drives all annotation batches; no repeated file scans.
                genome = "hg38" if normalize_build(analysis.reference_build) == "GRCh38" else "hg19"
                expected_count = int((normalization_step.metadata_json or {}).get("record_count", 0) or 0)
                scheduler = PartitionScheduler(db)
                worker_id = f"workflow:{analysis.id}"
                for start, batch in _iter_variant_batches(normalized_path, reference_build, batch_limit):
                    end = start + len(batch)
                    partition = db.scalar(select(AnalysisPartition).where(
                        AnalysisPartition.analysis_id == analysis.id,
                        AnalysisPartition.step_id == "annotate",
                        AnalysisPartition.partition_key == _batch_key(start, end),
                    ))
                    if partition is None:
                        raise RuntimeError(f"Annotation execution partition missing: {_batch_key(start, end)}")
                    if partition.status != "SUCCEEDED":
                        claimed = scheduler.claim_next(analysis.id, "annotate", worker_id)
                        if claimed is None or claimed.id != partition.id:
                            raise PartitionCapacityError("No resource capacity available for the next annotation partition")
                    # The lease token is the fencing generation. A worker may
                    # keep the stable workflow identity across retries, but every
                    # successful claim receives a new token.
                    lease_token = claimed.lease_token if partition.status == "RUNNING" else None
                    if partition.status == "RUNNING" and not lease_token:
                        raise PartitionLeaseError("Claimed annotation partition has no lease fencing token")
                    variant_ids = {
                        canonical_key(v.genome_build, v.chromosome, v.position, v.reference, v.alternate): stable_variant_uuid(canonical_key(v.genome_build, v.chromosome, v.position, v.reference, v.alternate))
                        for v in batch
                    }
                    key = _batch_key(start, end)
                    # Reuse is allowed only for the exact governed observation
                    # identity. A row from another resource release must never be
                    # mistaken for the current annotation result.
                    existing_rows = db.scalars(
                        select(Annotation).where(
                            Annotation.analysis_id == analysis.id,
                            Annotation.provider_name == provider.provider_id,
                            Annotation.provider_version == provider.provider_version,
                            Annotation.resource_id == annotation_resource.id,
                            Annotation.resource_version == annotation_resource.version,
                            Annotation.variant_id.in_(list(variant_ids.values())),
                        )
                    ).all()

                    # Legacy/unbound or resource-drifted observations are unsafe to
                    # merge into the current governed result set. Fail closed rather
                    # than allowing the same analysis to contain scientifically
                    # ambiguous annotation releases.
                    conflicting_rows = db.scalars(
                        select(Annotation).where(
                            Annotation.analysis_id == analysis.id,
                            Annotation.provider_name == provider.provider_id,
                            Annotation.variant_id.in_(list(variant_ids.values())),
                            or_(
                                Annotation.provider_version != provider.provider_version,
                                Annotation.resource_id.is_(None),
                                Annotation.resource_id != annotation_resource.id,
                                Annotation.resource_version.is_(None),
                                Annotation.resource_version != annotation_resource.version,
                            ),
                        )
                    ).all()
                    if conflicting_rows:
                        raise ResourceConsumptionError(
                            "ANNOTATION_OBSERVATION_IDENTITY_CONFLICT",
                            "Existing annotation observations for this analysis use a different "
                            "provider/resource identity; the analysis cannot silently mix annotation releases.",
                        )

                    existing_variant_rows = {
                        row.id: row for row in db.scalars(
                            select(Variant).where(Variant.id.in_(list(variant_ids.values())))
                        ).all()
                    }
                    existing_keys = {
                        canonical_key(
                            normalize_build(analysis.reference_build),
                            existing_variant_rows[ann.variant_id].chromosome,
                            existing_variant_rows[ann.variant_id].position,
                            existing_variant_rows[ann.variant_id].reference,
                            existing_variant_rows[ann.variant_id].alternate,
                        )
                        for ann in existing_rows
                        if ann.variant_id in existing_variant_rows
                    }
                    checkpoint = _batch_checkpoint(annotation_step, start, end)
                    if checkpoint.get("status") == "SUCCEEDED" and all(k in existing_keys for k in variant_ids):
                        if partition.status == "RUNNING" and partition.lease_owner == worker_id:
                            scheduler.succeed(partition.id, worker_id, lease_token, metadata={"provider": provider.provider_id, "recovered_existing_rows": True})
                        continue
                    if all(k in existing_keys for k in variant_ids):
                        _save_batch_checkpoint(
                            db, annotation_step, start, end, status="SUCCEEDED",
                            attempt=int(checkpoint.get("attempt", 0)),
                            metadata={"provider": provider.provider_id, "recovered_existing_rows": True, "variant_count": len(batch)},
                            commit=False,
                        )
                        if partition.status == "RUNNING" and partition.lease_owner == worker_id:
                            scheduler.succeed(partition.id, worker_id, lease_token, metadata={"provider": provider.provider_id, "recovered_existing_rows": True})
                        continue

                    attempt = int(checkpoint.get("attempt", 0)) + 1
                    _save_batch_checkpoint(
                        db, annotation_step, start, end, status="RUNNING", attempt=attempt,
                        metadata={"provider": provider.provider_id, "variant_count": len(batch)},
                    )
                    execution_record = start_resource_execution(db, analysis_id=analysis.id, step_id="annotate", attempt=attempt, resolved=annotation_execution, requested_resource_id=resolution.requested_resource_id, fallback_resource_id=resolution.fallback_resource_id, batch_key=key, metadata={"provider": provider.provider_id, "genome": genome})
                    db.commit()
                    try:
                        scheduler.heartbeat(partition.id, worker_id, lease_token)
                        payloads = provider.annotate(batch, {"genome": genome})
                        scheduler.heartbeat(partition.id, worker_id, lease_token)
                        sample = next((item.get("_siraloom_annotation_provenance", {}) for item in payloads if isinstance(item, dict)), {})
                        complete_resource_execution(db, execution_record, status="SUCCEEDED", request_fingerprint=sample.get("request_fingerprint"), response_sha256=sample.get("response_sha256"))
                        db.commit()
                    except (GeneBeError, VEPProviderError) as exc:
                        complete_resource_execution(
                            db,
                            execution_record,
                            status="FAILED",
                            error_code="ANNOTATION_PROVIDER_TRANSIENT" if exc.retryable else "ANNOTATION_PROVIDER_ERROR",
                            error_message=str(exc),
                        )
                        db.commit()
                        if exc.retryable:
                            if partition.status == "RUNNING" and partition.lease_owner == worker_id:
                                scheduler.fail(partition.id, worker_id, lease_token, error_code="ANNOTATION_PROVIDER_TRANSIENT", error_message=str(exc))
                            _save_batch_checkpoint(
                                db, annotation_step, start, end, status="RETRYING", attempt=attempt,
                                metadata={"error": str(exc)},
                            )
                            mark_step(db, annotation_step, StepStatus.RETRYING, error_code="ANNOTATION_PROVIDER_TRANSIENT", error_message=str(exc))
                            raise TransientWorkflowError(str(exc), countdown=min(60, 5 * attempt)) from exc
                        if partition.status == "RUNNING" and partition.lease_owner == worker_id:
                            scheduler.fail(partition.id, worker_id, lease_token, error_code="ANNOTATION_PROVIDER_ERROR", error_message=str(exc))
                        _save_batch_checkpoint(
                            db, annotation_step, start, end, status="FAILED", attempt=attempt,
                            metadata={"error": str(exc)},
                        )
                        raise

                    payloads_by_key: dict[str, dict] = {}
                    for payload in payloads:
                        try:
                            payload_key = canonical_key(
                                normalize_build(analysis.reference_build),
                                str(payload.get("chr")),
                                int(payload["pos"]),
                                str(payload["ref"]),
                                str(payload["alt"]),
                            )
                        except (KeyError, TypeError, ValueError) as exc:
                            raise GeneBeError(f"Invalid GeneBe response record in batch {key}") from exc
                        if payload_key in payloads_by_key:
                            raise GeneBeError(f"Duplicate provider result for canonical variant {payload_key}")
                        payloads_by_key[payload_key] = payload

                    expected_batch = set(variant_ids)
                    if payloads_by_key.keys() != expected_batch:
                        missing = expected_batch - payloads_by_key.keys()
                        extra = payloads_by_key.keys() - expected_batch
                        raise GeneBeError(
                            f"Provider result set does not match batch {key}; missing={len(missing)}, extra={len(extra)}"
                        )

                    existing_by_variant = {str(a.variant_id): a for a in existing_rows}
                    new_count = 0
                    for canonical, row_id in variant_ids.items():
                        if str(row_id) in existing_by_variant:
                            continue
                        payload = payloads_by_key[canonical]
                        provenance = dict(payload.pop("_siraloom_annotation_provenance", {}) or {})
                        normalized = normalize_annotation_payload(provider.provider_id, payload)
                        db.add(
                            Annotation(
                                id=__import__("uuid").uuid4(),
                                variant_id=row_id,
                                analysis_id=analysis.id,
                                provider_name=provider.provider_id,
                                provider_version=provider.provider_version,
                                resource_id=annotation_resource.id if annotation_resource else None,
                                resource_name=annotation_resource.name if annotation_resource else "GeneBe",
                                resource_version=annotation_resource.version if annotation_resource else None,
                                request_fingerprint=provenance.get("request_fingerprint"),
                                response_sha256=provenance.get("response_sha256"),
                                request_metadata={
                                    "endpoint": provenance.get("endpoint"),
                                    "genome": provenance.get("genome"),
                                    "provider": provenance.get("provider"),
                                    "provider_version": provenance.get("provider_version"),
                                },
                                observed_at=(
                                    datetime.fromisoformat(provenance["observed_at"])
                                    if provenance.get("observed_at")
                                    else None
                                ),
                                retry_count=int(provenance.get("retry_count", 0) or 0),
                                payload={"raw": payload, "normalized": normalized},
                            )
                        )
                        new_count += 1
                    db.commit()
                    _save_batch_checkpoint(
                        db, annotation_step, start, end, status="SUCCEEDED", attempt=attempt,
                        metadata={"provider": provider.provider_id, "new_annotation_rows": new_count, "returned_rows": len(payloads_by_key)},
                        commit=False,
                    )
                    if partition.status == "RUNNING" and partition.lease_owner == worker_id:
                        scheduler.succeed(partition.id, worker_id, lease_token, metadata={"provider": provider.provider_id, "variant_count": len(batch)})
                    else:
                        raise PartitionLeaseError(
                            f"Annotation partition {partition.id} lost its lease before result persistence"
                        )
                    audit.record(
                        event_type="ANNOTATION_BATCH_COMPLETED",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SERVICE",
                        actor_id=provider.provider_id,
                        input_artifacts=[{"artifact_id": str(normalized_artifact.id), "sha256": normalized_artifact.sha256}],
                        workflow={"step": "annotate", "batch": key, "provider_version": provider.provider_version},
                        payload={"variant_count": len(batch), "new_annotation_rows": new_count},
                    )
                    db.commit()

                persisted_count = db.scalar(
                    select(func.count(Annotation.id)).where(
                        Annotation.analysis_id == analysis.id,
                        Annotation.provider_name == provider.provider_id,
                    )
                ) or 0
                if persisted_count < expected_count:
                    raise GeneBeError(
                        f"Annotation checkpoint reconciliation failed: expected {expected_count} rows, found {persisted_count}"
                    )
                annotation_step.input_artifacts = [str(normalized_artifact.id)] if normalized_artifact else []
                mark_step(db, annotation_step, StepStatus.SUCCEEDED, metadata={
                    "provider": provider.provider_id,
                    "provider_version": provider.provider_version,
                    "count": persisted_count,
                    "batch_limit": batch_limit,
                    "checkpointed": True,
                })
                audit.record(
                    event_type="ANNOTATION_COMPLETED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id=provider.provider_id,
                    input_artifacts=[{"artifact_id": str(normalized_artifact.id), "sha256": normalized_artifact.sha256}],
                    payload={"provider_results": persisted_count, "checkpointed_batches": len((annotation_step.metadata_json or {}).get("batches", {}))},
                )
                db.commit()
            except TransientWorkflowError:
                raise
            except PartitionCapacityError as exc:
                mark_step(
                    db,
                    annotation_step,
                    StepStatus.RESOURCE_FAILURE,
                    error_code="ANNOTATION_RESOURCE_CAPACITY_EXHAUSTED",
                    error_message=str(exc),
                    metadata={"next_step": "annotate"},
                )
                analysis.status = AnalysisStatus.RESOURCE_FAILURE
                db.commit()
                audit.record(
                    event_type="ANNOTATION_RESOURCE_FAILURE",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="partition-scheduler",
                    reason=str(exc),
                    payload={"error_code": "ANNOTATION_RESOURCE_CAPACITY_EXHAUSTED", "next_step": "annotate"},
                )
                db.commit()
                return
            except GeneBeError as exc:
                mark_step(db, annotation_step, StepStatus.FAILED, error_code="ANNOTATION_PROVIDER_ERROR", error_message=str(exc))
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(
                    event_type="ANNOTATION_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id=provider.provider_id,
                    reason=str(exc),
                )
                db.commit()
                return
            except Exception as exc:
                # Safety net -- see the matching comment on the normalization step above.
                mark_step(db, annotation_step, StepStatus.FAILED, error_code="ANNOTATION_UNEXPECTED_ERROR", error_message=str(exc))
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(
                    event_type="ANNOTATION_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id=provider.provider_id,
                    reason=str(exc),
                )
                db.commit()
                return

        # 4. Population evidence is capability-driven.
        # Only resources that are actually executable in this deployment are run.
        # GeneBe population data is available only in the SIRALOOM trial profile.
        population_step = _step(db, analysis.id, "population")
        if population_step.status != StepStatus.SUCCEEDED:
            mark_step(db, population_step, StepStatus.RUNNING)
            try:
                case = db.get(Case, analysis.case_id)
                if case is None:
                    raise ResourceConsumptionError(
                        "CASE_NOT_FOUND",
                        "Analysis case was not found during population resource planning.",
                    )

                plan = build_resource_execution_plan(
                    db,
                    organization_id=case.organization_id,
                    requirements=(
                        CapabilityRequirement(
                            ResourceCapability.POPULATION_FREQUENCY,
                            required=False,
                        ),
                    ),
                )
                population_candidates = plan.for_capability(
                    ResourceCapability.POPULATION_FREQUENCY
                )

                created = 0
                direct_count = 0
                executed_resources: list[dict[str, str]] = []
                registry = register_builtin_providers()

                for candidate in population_candidates:
                    resource = candidate.resource
                    execution = resolve_resource_execution(db, resource=resource)
                    implementation = registry.resolve(
                        provider_id=execution.contract.provider_id,
                        provider_version=execution.contract.provider_version,
                    )
                    if implementation is None:
                        continue

                    provider = implementation.factory(execution.contract)
                    executed_resources.append({
                        "resource_id": str(resource.id),
                        "resource_name": resource.name,
                        "provider": execution.contract.provider_id,
                        "provider_version": execution.contract.provider_version,
                    })

                    # GeneBe exposes population observations as part of its
                    # annotation response. It is deliberately a trial-only
                    # source and is never used for laboratory execution.
                    if provider.provider_id == "GeneBe":
                        if not plan.profile_type == "TRIAL_PUBLIC":
                            continue
                        annotation_count = db.scalar(
                            select(func.count(Annotation.id)).where(
                                Annotation.analysis_id == analysis.id,
                                Annotation.provider_name == "GeneBe",
                            )
                        ) or 0
                        pop_batch_size = int(
                            analysis.configuration.get("population_batch_size", partition_size)
                            or partition_size
                        )
                        for pop_start, pop_end in _chunk_ranges(
                            annotation_count, pop_batch_size
                        ):
                            annotations = db.scalars(
                                select(Annotation)
                                .where(
                                    Annotation.analysis_id == analysis.id,
                                    Annotation.provider_name == "GeneBe",
                                )
                                .order_by(Annotation.created_at, Annotation.id)
                                .offset(pop_start)
                                .limit(pop_end - pop_start)
                            ).all()
                            for ann in annotations:
                                payload = (ann.payload or {}).get("normalized", {})
                                pop = payload.get("population", {})
                                if (
                                    pop.get("reference_population_af") is None
                                    and pop.get("reference_population_ac") is None
                                ):
                                    continue
                                existing = db.scalar(
                                    select(PopulationObservation).where(
                                        PopulationObservation.analysis_id == analysis.id,
                                        PopulationObservation.variant_id == ann.variant_id,
                                        PopulationObservation.resource_id == resource.id,
                                        PopulationObservation.population_code == "GLOBAL",
                                    )
                                )
                                if existing:
                                    continue
                                db.add(
                                    PopulationObservation(
                                        id=__import__("uuid").uuid4(),
                                        analysis_id=analysis.id,
                                        variant_id=ann.variant_id,
                                        resource_id=resource.id,
                                        population_level="GLOBAL",
                                        population_code="GLOBAL",
                                        population_label="Global",
                                        allele_count=_safe_int(
                                            pop.get("reference_population_ac")
                                        ),
                                        allele_number=None,
                                        allele_frequency=_safe_float(
                                            pop.get("reference_population_af")
                                        ),
                                        homozygote_count=_safe_int(
                                            pop.get("reference_population_hom")
                                        ),
                                        availability="AVAILABLE",
                                        quality_status="PROVIDER_DERIVED",
                                    )
                                )
                                created += 1
                        db.commit()
                        continue

                    # Direct population providers expose query_variant() and
                    # return SIRALOOM population observations. This is the
                    # provider execution contract used by the current gnomAD
                    # GraphQL and local tabix implementations.
                    query_variant = getattr(provider, "query_variant", None)
                    if query_variant is None:
                        continue

                    for variant in iter_normalized_vcf(
                        normalized_path, reference_build
                    ):
                        execution_record = start_resource_execution(
                            db,
                            analysis_id=analysis.id,
                            step_id="population",
                            attempt=population_step.attempt,
                            resolved=execution,
                            requested_resource_id=resource.id,
                            fallback_resource_id=None,
                            batch_key=(
                                f"{provider.provider_id}:{variant.chromosome}:"
                                f"{variant.position}:{variant.reference}:{variant.alternate}"
                            ),
                            metadata={
                                "provider": provider.provider_id,
                                "resource_id": str(resource.id),
                            },
                        )
                        db.commit()
                        try:
                            obs_list = query_variant(variant)
                            sample = next(iter(obs_list), None)
                            complete_resource_execution(
                                db,
                                execution_record,
                                status="SUCCEEDED",
                                request_fingerprint=(
                                    sample.request_fingerprint if sample else None
                                ),
                                response_sha256=(
                                    sample.response_sha256 if sample else None
                                ),
                            )
                            db.commit()
                        except GnomADProviderError as exc:
                            complete_resource_execution(
                                db,
                                execution_record,
                                status="FAILED",
                                error_code="POPULATION_PROVIDER_ERROR",
                                error_message=str(exc),
                            )
                            db.commit()
                            raise

                        row = db.get(
                            Variant,
                            stable_variant_uuid(
                                canonical_key(
                                    variant.genome_build,
                                    variant.chromosome,
                                    variant.position,
                                    variant.reference,
                                    variant.alternate,
                                )
                            ),
                        )
                        if row is None:
                            raise RuntimeError(
                                "Canonical variant row missing during population processing"
                            )

                        for obs in obs_list:
                            existing = db.scalar(
                                select(PopulationObservation).where(
                                    PopulationObservation.analysis_id == analysis.id,
                                    PopulationObservation.variant_id == row.id,
                                    PopulationObservation.resource_id == resource.id,
                                    PopulationObservation.population_code == obs.population_code,
                                )
                            )
                            if existing:
                                continue
                            db.add(
                                PopulationObservation(
                                    id=__import__("uuid").uuid4(),
                                    analysis_id=analysis.id,
                                    variant_id=row.id,
                                    resource_id=resource.id,
                                    population_level=obs.population_level,
                                    population_code=obs.population_code,
                                    population_label=obs.population_label,
                                    allele_count=obs.allele_count,
                                    allele_number=obs.allele_number,
                                    allele_frequency=obs.allele_frequency,
                                    homozygote_count=obs.homozygote_count,
                                    availability=obs.availability,
                                    quality_status=obs.quality_status,
                                    source_record_id=obs.source_record_id,
                                    request_fingerprint=obs.request_fingerprint,
                                    response_sha256=obs.response_sha256,
                                    request_metadata=obs.request_metadata or {},
                                    observed_at=(
                                        datetime.fromisoformat(obs.observed_at)
                                        if obs.observed_at
                                        else None
                                    ),
                                )
                            )
                            direct_count += 1
                        db.commit()

                population_metadata = {
                    "executed_resources": executed_resources,
                    "profile_type": plan.profile_type,
                    "profile_version": plan.profile_version,
                    "gene_be_global_observations": created,
                    "direct_population_observations": direct_count,
                    "optional_resources_not_selected": len(plan.unavailable_optional),
                }
                # Absence of an optional population resource is not a workflow
                # failure and is not converted into a user-facing limitation.
                mark_step(
                    db,
                    population_step,
                    StepStatus.SUCCEEDED,
                    metadata=population_metadata,
                )
                audit.record(
                    event_type="POPULATION_COMPLETED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id="population-engine",
                    payload=population_metadata,
                )
                db.commit()
            except ResourceConsumptionError as exc:
                mark_step(
                    db,
                    population_step,
                    StepStatus.BLOCKED,
                    error_code=exc.code,
                    error_message=str(exc),
                    metadata={"next_step": "RESOURCE_REQUIRED"},
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="WORKFLOW_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="population",
                    actor_id="resource-registry",
                    reason=str(exc),
                    payload={"error_code": exc.code, "next_step": "RESOURCE_REQUIRED"},
                )
                db.commit()
                return
            except GnomADProviderError as exc:
                mark_step(db, population_step, StepStatus.FAILED, error_code="GNOMAD_PROVIDER_ERROR", error_message=str(exc))
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(
                    event_type="POPULATION_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id="gnomad",
                    reason=str(exc),
                )
                db.commit()
                return
            except Exception as exc:
                # Safety net -- see the matching comment on the normalization step above.
                mark_step(db, population_step, StepStatus.FAILED, error_code="POPULATION_UNEXPECTED_ERROR", error_message=str(exc))
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(
                    event_type="POPULATION_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id="gnomad",
                    reason=str(exc),
                )
                db.commit()
                return

        # 5. Build traceable evidence records from persisted annotations and population observations.
        evidence_step = _step(db, analysis.id, "build_evidence")
        if evidence_step.status != StepStatus.SUCCEEDED:
            mark_step(db, evidence_step, StepStatus.RUNNING)
            try:
                from backend.app.evidence.engine import EvidenceContext, EvidenceEngine
                from backend.app.domain.evidence import evidence_fingerprint
                engine = EvidenceEngine()
                total_annotation_rows = db.scalar(select(func.count(Annotation.id)).where(Annotation.analysis_id == analysis.id)) or 0
                resource_rows = {r.id: r for r in db.scalars(select(Resource)).all()}

                # ClinVar is consumed here as direct clinical-database evidence,
                # not as an annotation-stage side effect. The analysis must pin a
                # registered resource version; runtime execution then resolves the
                # exact qualified contract and reads only the staged authoritative
                # release through the governed adapter.
                clinvar_resource = None
                clinvar_provider = None
                clinvar_execution = None
                clinvar_execution_metadata = None
                configured_clinvar_id = (analysis.configuration or {}).get("clinvar_resource_id")

                # ClinVar is an optional clinical-variant evidence capability.
                # If the laboratory has adopted a qualified ClinVar release, use
                # it automatically. An explicit analysis resource ID remains a
                # hard pin and is validated rather than silently substituted.
                if configured_clinvar_id:
                    clinvar_resource = _require_registered_resource(
                        db,
                        resource_id=configured_clinvar_id,
                        expected_type="EVIDENCE",
                        expected_build=analysis.reference_build,
                        expected_provider="NCBI ClinVar",
                    )
                else:
                    case_for_resources = db.get(Case, analysis.case_id)
                    if case_for_resources is not None:
                        clinvar_plan = build_resource_execution_plan(
                            db,
                            organization_id=case_for_resources.organization_id,
                            requirements=(
                                CapabilityRequirement(ResourceCapability.CLINICAL_VARIANT),
                            ),
                        )
                        clinvar_candidates = [
                            item for item in clinvar_plan.for_capability(ResourceCapability.CLINICAL_VARIANT)
                            if item.resource.provider == "NCBI ClinVar"
                        ]
                        if clinvar_candidates:
                            clinvar_resource = clinvar_candidates[0].resource

                if clinvar_resource is not None:
                    clinvar_execution = resolve_resource_execution(
                        db,
                        resource=clinvar_resource,
                    )
                    clinvar_provider = ClinVarVCVProvider.from_execution_contract(
                        resolved=clinvar_execution,
                        resource_location=clinvar_resource.location,
                        genome_build=analysis.reference_build,
                        index_root=settings.resource_cache_root,
                    )
                    clinvar_execution_metadata = {
                        **clinvar_execution.snapshot,
                        "resource_name": clinvar_resource.name,
                        "resource_checksum": clinvar_resource.checksum,
                        "execution_dataset": clinvar_execution.contract.dataset,
                    }

                # ClinGen evidence activities are optional and independently governed.
                clingen_vp_resource = None
                clingen_vp_provider = None
                clingen_vp_execution = None
                clingen_vp_metadata = None
                clingen_gdv_resource = None
                clingen_gdv_provider = None
                clingen_gdv_execution = None
                clingen_gdv_metadata = None
                case_for_clingen = db.get(Case, analysis.case_id)
                if case_for_clingen is not None:
                    vp_plan = build_resource_execution_plan(db, organization_id=case_for_clingen.organization_id, requirements=(CapabilityRequirement(ResourceCapability.CLINICAL_VARIANT),))
                    vp_candidates = [x for x in vp_plan.for_capability(ResourceCapability.CLINICAL_VARIANT) if x.resource.provider == ClinGenVariantPathogenicityProvider.provider_id]
                    if vp_candidates:
                        clingen_vp_resource = vp_candidates[0].resource
                        clingen_vp_execution = resolve_resource_execution(db, resource=clingen_vp_resource)
                        clingen_vp_provider = ClinGenVariantPathogenicityProvider.from_execution_contract(resolved=clingen_vp_execution)
                        clingen_vp_metadata = {**clingen_vp_execution.snapshot, "resource_name": clingen_vp_resource.name, "resource_checksum": clingen_vp_resource.checksum}
                    gdv_plan = build_resource_execution_plan(db, organization_id=case_for_clingen.organization_id, requirements=(CapabilityRequirement(ResourceCapability.GENE_DISEASE),))
                    gdv_candidates = [x for x in gdv_plan.for_capability(ResourceCapability.GENE_DISEASE) if x.resource.provider == ClinGenGeneDiseaseValidityProvider.provider_id]
                    if gdv_candidates:
                        clingen_gdv_resource = gdv_candidates[0].resource
                        clingen_gdv_execution = resolve_resource_execution(db, resource=clingen_gdv_resource)
                        clingen_gdv_provider = ClinGenGeneDiseaseValidityProvider.from_execution_contract(resolved=clingen_gdv_execution)
                        clingen_gdv_metadata = {**clingen_gdv_execution.snapshot, "resource_name": clingen_gdv_resource.name, "resource_checksum": clingen_gdv_resource.checksum}
                from backend.app.infrastructure.db.models import Case, PhenotypeObservation
                case = db.get(Case, analysis.case_id)
                case_context = case.clinical_context if case else {}
                phenotype_rows = db.scalars(select(PhenotypeObservation).where(PhenotypeObservation.case_id == analysis.case_id, (PhenotypeObservation.analysis_id == analysis.id) | (PhenotypeObservation.analysis_id.is_(None)))).all()
                case_hpo_terms = [{"hpo_id": x.hpo_id, "label": x.label, "present": x.present} for x in phenotype_rows]
                gene_disease_records = list(case_context.get("gene_disease_evidence") or [])
                literature_records = list(case_context.get("literature_evidence") or [])

                created = 0
                batch_size = int(analysis.configuration.get("evidence_batch_size", 250) or 250)
                completed_batches = _completed_batch_keys(evidence_step)
                for start_i, end_i in _chunk_ranges(total_annotation_rows, batch_size):
                    key = _batch_key(start_i, end_i)
                    if key in completed_batches:
                        continue
                    attempt = int((_batch_checkpoint(evidence_step, start_i, end_i).get("attempt") or 0)) + 1
                    _save_batch_checkpoint(db, evidence_step, start_i, end_i, status="RUNNING", attempt=attempt)
                    batch_created = 0
                    annotations = db.scalars(select(Annotation).where(Annotation.analysis_id == analysis.id).order_by(Annotation.created_at, Annotation.id).offset(start_i).limit(end_i - start_i)).all()
                    variant_ids_for_batch = [a.variant_id for a in annotations]
                    population_rows = db.scalars(select(PopulationObservation).where(PopulationObservation.analysis_id == analysis.id, PopulationObservation.variant_id.in_(variant_ids_for_batch))).all() if variant_ids_for_batch else []
                    population_by_variant: dict[str, list[dict]] = {}
                    for obs in population_rows:
                        resource = resource_rows.get(obs.resource_id)
                        population_by_variant.setdefault(str(obs.variant_id), []).append({"observation_id": obs.id, "resource_name": resource.name if resource else None, "resource_version": resource.version if resource else None, "population_code": obs.population_code, "population_label": obs.population_label, "allele_count": obs.allele_count, "allele_number": obs.allele_number, "allele_frequency": obs.allele_frequency, "homozygote_count": obs.homozygote_count, "availability": obs.availability, "quality_status": obs.quality_status})
                    for ann_row in annotations:
                        row = db.get(Variant, ann_row.variant_id)
                        if row is None:
                            continue
                        ann = ann_row
                        normalized = (ann.payload or {}).get("normalized") or {}
                        gene_symbol = ((normalized.get("gene") or {}).get("symbol"))
                        records = engine.build_from_annotation(
                            variant_id=row.id, annotation=normalized, provider_name=ann.provider_name,
                            provider_version=ann.provider_version, resource_name=ann.resource_name,
                            resource_version=ann.resource_version, context=EvidenceContext(analysis_id=analysis.id),
                            population_observations=population_by_variant.get(str(row.id), []),
                        )
                        records.extend(engine.build_case_context_evidence(
                            variant_id=row.id, case_hpo_terms=case_hpo_terms, gene=gene_symbol,
                            gene_disease_records=gene_disease_records, literature_records=literature_records,
                        ))

                        gene = ((ann.payload or {}).get("gene") or {}).get("symbol") or (ann.payload or {}).get("gene_symbol")
                        hgvs_values = list((ann.payload or {}).get("hgvs_consequences") or [])
                        if (ann.payload or {}).get("hgvs"):
                            hgvs_values.append((ann.payload or {}).get("hgvs"))
                        if clingen_vp_provider is not None and clingen_vp_resource is not None and clingen_vp_execution is not None and gene:
                            query_material = {"analysis_id": str(analysis.id), "variant_id": str(row.id), "gene": gene, "hgvs": hgvs_values, "resource_id": str(clingen_vp_execution.resource_id), "resource_version": clingen_vp_execution.resource_version, "contract_hash": clingen_vp_execution.contract_hash}
                            request_fingerprint = hashlib.sha256(json.dumps(query_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                            execution_row = start_resource_execution(db, analysis_id=analysis.id, step_id="build_evidence", attempt=attempt, batch_key=key, resolved=clingen_vp_execution, requested_resource_id=clingen_vp_resource.id, fallback_resource_id=None, metadata={"execution_kind": "CLINGEN_VARIANT_PATHOGENICITY_QUERY", "query": query_material})
                            try:
                                assertions = clingen_vp_provider.query_variant(gene=gene, hgvs=hgvs_values)
                                response_material = [{"source_record_id": x.source_record_id, "record_sha256": x.record_sha256} for x in assertions]
                                response_sha256 = hashlib.sha256(json.dumps(response_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                                complete_resource_execution(db, execution_row, status="SUCCESS" if assertions else "NO_DATA", request_fingerprint=request_fingerprint, response_sha256=response_sha256)
                                records.extend(engine.build_from_clingen_variant_assertions(variant_id=row.id, assertions=assertions, resource_id=clingen_vp_execution.resource_id, resource_name=clingen_vp_resource.name, resource_version=clingen_vp_resource.version, request_fingerprint=request_fingerprint, execution_metadata={**clingen_vp_metadata, "query": query_material, "response_sha256": response_sha256}))
                            except Exception as exc:
                                complete_resource_execution(db, execution_row, status="FAILED", request_fingerprint=request_fingerprint, error_code="CLINGEN_VARIANT_PATHOGENICITY_QUERY_FAILED", error_message=str(exc))
                                raise

                        if clingen_gdv_provider is not None and clingen_gdv_resource is not None and clingen_gdv_execution is not None and gene:
                            query_material = {"analysis_id": str(analysis.id), "variant_id": str(row.id), "gene": gene, "resource_id": str(clingen_gdv_execution.resource_id), "resource_version": clingen_gdv_execution.resource_version, "contract_hash": clingen_gdv_execution.contract_hash}
                            request_fingerprint = hashlib.sha256(json.dumps(query_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                            execution_row = start_resource_execution(db, analysis_id=analysis.id, step_id="build_evidence", attempt=attempt, batch_key=key, resolved=clingen_gdv_execution, requested_resource_id=clingen_gdv_resource.id, fallback_resource_id=None, metadata={"execution_kind": "CLINGEN_GENE_DISEASE_VALIDITY_QUERY", "query": query_material})
                            try:
                                assertions = clingen_gdv_provider.query_gene(gene=gene)
                                response_material = [{"source_record_id": x.source_record_id, "record_sha256": x.record_sha256} for x in assertions]
                                response_sha256 = hashlib.sha256(json.dumps(response_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                                complete_resource_execution(db, execution_row, status="SUCCESS" if assertions else "NO_DATA", request_fingerprint=request_fingerprint, response_sha256=response_sha256)
                                records.extend(engine.build_from_clingen_gene_disease_assertions(variant_id=row.id, assertions=assertions, resource_id=clingen_gdv_execution.resource_id, resource_name=clingen_gdv_resource.name, resource_version=clingen_gdv_resource.version, request_fingerprint=request_fingerprint, execution_metadata={**clingen_gdv_metadata, "query": query_material, "response_sha256": response_sha256}))
                            except Exception as exc:
                                complete_resource_execution(db, execution_row, status="FAILED", request_fingerprint=request_fingerprint, error_code="CLINGEN_GENE_DISEASE_VALIDITY_QUERY_FAILED", error_message=str(exc))
                                raise
                        if clinvar_provider is not None and clinvar_resource is not None and clinvar_execution is not None:
                            query_material = {
                                "analysis_id": str(analysis.id),
                                "variant_id": str(row.id),
                                "genome_build": row.genome_build,
                                "chromosome": row.chromosome,
                                "position": row.position,
                                "reference": row.reference,
                                "alternate": row.alternate,
                                "resource_id": str(clinvar_execution.resource_id),
                                "resource_version": clinvar_execution.resource_version,
                                "contract_hash": clinvar_execution.contract_hash,
                            }
                            request_fingerprint = hashlib.sha256(
                                json.dumps(query_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
                            ).hexdigest()
                            execution_row = start_resource_execution(
                                db,
                                analysis_id=analysis.id,
                                step_id="build_evidence",
                                attempt=attempt,
                                batch_key=key,
                                resolved=clinvar_execution,
                                requested_resource_id=clinvar_resource.id,
                                fallback_resource_id=None,
                                metadata={
                                    "execution_kind": "CLINVAR_VARIANT_QUERY",
                                    "query": query_material,
                                },
                            )
                            try:
                                assertions = clinvar_provider.query_variant(
                                    chromosome=row.chromosome,
                                    position=row.position,
                                    reference=row.reference,
                                    alternate=row.alternate,
                                )
                                response_material = [
                                    {
                                        "record_type": x.record_type,
                                        "accession": x.accession,
                                        "version": x.version,
                                        "record_sha256": x.record_sha256,
                                    }
                                    for x in assertions
                                ]
                                response_sha256 = hashlib.sha256(
                                    json.dumps(response_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
                                ).hexdigest()
                                complete_resource_execution(
                                    db,
                                    execution_row,
                                    status="SUCCESS" if assertions else "NO_DATA",
                                    request_fingerprint=request_fingerprint,
                                    response_sha256=response_sha256,
                                )
                                records.extend(
                                    engine.build_from_clinvar_assertions(
                                        variant_id=row.id,
                                        assertions=assertions,
                                        resource_id=clinvar_execution.resource_id,
                                        resource_name=clinvar_resource.name,
                                        resource_version=clinvar_resource.version,
                                        request_fingerprint=request_fingerprint,
                                        execution_metadata={
                                            **clinvar_execution_metadata,
                                            "query": query_material,
                                            "response_sha256": response_sha256,
                                        },
                                    )
                                )
                            except Exception as exc:
                                complete_resource_execution(
                                    db,
                                    execution_row,
                                    status="FAILED",
                                    request_fingerprint=request_fingerprint,
                                    error_code="CLINVAR_QUERY_FAILED",
                                    error_message=str(exc),
                                )
                                raise

                        for record in records:
                            if record.resource_id is not None:
                                provenance = {
                                    "resource_id": record.resource_id,
                                    "source_record_id": record.source_record_id,
                                    "request_fingerprint": record.request_fingerprint,
                                    "response_sha256": record.response_sha256,
                                    "request_metadata": record.request_metadata or {},
                                    "observed_at": record.observed_at,
                                    "source_name": record.source_name,
                                    "source_version": record.source_version,
                                }
                            else:
                                provenance = {
                                    "resource_id": ann.resource_id,
                                    "source_record_id": None,
                                    "request_fingerprint": ann.request_fingerprint,
                                    "response_sha256": ann.response_sha256,
                                    "request_metadata": ann.request_metadata or {},
                                    "observed_at": ann.observed_at,
                                    "source_name": record.source_name,
                                    "source_version": record.source_version,
                                }
                            if len(record.observation_ids) == 1:
                                obs = next((o for o in population_rows if o.id == record.observation_ids[0]), None)
                                if obs is not None:
                                    resource = resource_rows.get(obs.resource_id)
                                    provenance = {
                                        "resource_id": obs.resource_id,
                                        "source_record_id": obs.source_record_id,
                                        "request_fingerprint": obs.request_fingerprint,
                                        "response_sha256": obs.response_sha256,
                                        "request_metadata": obs.request_metadata or {},
                                        "observed_at": obs.observed_at,
                                        "source_name": resource.name if resource else record.source_name,
                                        "source_version": resource.version if resource else record.source_version,
                                    }
                            fp = evidence_fingerprint(
                                variant_id=record.variant_id, analysis_id=analysis.id,
                                evidence_type=record.evidence_type, statement=record.statement,
                                direction=record.direction, source_name=provenance["source_name"],
                                source_version=provenance["source_version"], observation_ids=record.observation_ids,
                                payload=record.payload, resource_id=provenance["resource_id"],
                                source_record_id=provenance["source_record_id"],
                                request_fingerprint=provenance["request_fingerprint"],
                                response_sha256=provenance["response_sha256"],
                            )
                            exists = db.scalar(select(Evidence).where(Evidence.analysis_id == analysis.id, Evidence.evidence_fingerprint == fp))
                            if exists:
                                continue
                            evidence_row = Evidence(
                                id=record.evidence_id, variant_id=record.variant_id, analysis_id=analysis.id,
                                evidence_type=record.evidence_type, statement=record.statement, direction=record.direction,
                                source_name=provenance["source_name"], source_version=provenance["source_version"],
                                resource_id=provenance["resource_id"], source_record_id=provenance["source_record_id"],
                                request_fingerprint=provenance["request_fingerprint"], response_sha256=provenance["response_sha256"],
                                request_metadata=provenance["request_metadata"], observed_at=provenance["observed_at"],
                                observation_ids=[str(x) for x in record.observation_ids], payload=record.payload,
                                created_by_type="SYSTEM", created_by_id=engine.engine_id, evidence_fingerprint=fp,
                            )
                            db.add(evidence_row)
                            # ClinGen criterion assertions are a separate source-assertion
                            # layer. They remain bound to this Evidence row and never
                            # become a SIRALOOM classification by ingestion alone.
                            persist_clingen_source_assertions(db, evidence=evidence_row)
                            created += 1; batch_created += 1
                    db.commit()
                    _save_batch_checkpoint(db, evidence_step, start_i, end_i, status="SUCCEEDED", attempt=attempt, metadata={"created_evidence": batch_created})
                db.commit()
                evidence_step.input_artifacts = [str(normalized_artifact.id)] if normalized_artifact else []
                evidence_metadata = {
                    "engine": engine.engine_id,
                    "engine_version": engine.engine_version,
                    "created_evidence": created,
                }
                if created == 0:
                    _apply_scientific_limitation(
                        db,
                        evidence_step,
                        outcome=OutcomeKind.INSUFFICIENT_EVIDENCE,
                        code="EVIDENCE_INSUFFICIENT",
                        message=(
                            "Evidence collection completed, but no reportable evidence records were "
                            "established from the available annotation, population, phenotype, gene-disease, "
                            "or literature context."
                        ),
                        metadata=evidence_metadata,
                    )
                else:
                    mark_step(db, evidence_step, StepStatus.SUCCEEDED, metadata=evidence_metadata)
                audit.record(
                    event_type="EVIDENCE_COMPLETED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id=engine.engine_id,
                    payload={"created_evidence": created, "engine_version": engine.engine_version},
                )
                db.commit()
            except (ResourceConsumptionError, ResourceExecutionError, ClinVarProviderError) as exc:
                code = getattr(exc, "code", None) or "CLINVAR_RESOURCE_UNAVAILABLE"
                mark_step(
                    db,
                    evidence_step,
                    StepStatus.BLOCKED,
                    error_code=code,
                    error_message=str(exc),
                    metadata={"next_step": "RESOURCE_REQUIRED", "automatic_fallback": False},
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="EVIDENCE_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id="clinvar-resource",
                    reason=str(exc),
                    payload={"error_code": code, "automatic_fallback": False},
                )
                db.commit()
                return
            except Exception as exc:
                mark_step(db, evidence_step, StepStatus.FAILED, error_code="EVIDENCE_BUILD_FAILED", error_message=str(exc))
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(
                    event_type="EVIDENCE_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id="siraloom-evidence",
                    reason=str(exc),
                )
                db.commit()
                return

        # 6. Specification-aware ACMG assessment. This step is fail-closed:
        # a validated and applicable ClinGen specification must exist, and the
        # selected specification must contain structured configuration supported
        # by SIRALOOM evaluators. Otherwise the case is blocked/review-required,
        # never silently classified by a generic rule set.
        acmg_step = _step(db, analysis.id, "acmg_assessment")
        if acmg_step.status != StepStatus.SUCCEEDED:
            mark_step(db, acmg_step, StepStatus.RUNNING)
            try:
                from backend.app.acmg.assessment_service import ACMGSpecificationAssessmentService
                from backend.app.infrastructure.db.models import Case

                case = db.get(Case, analysis.case_id)
                case_context = case.clinical_context if case else {}
                disease = analysis.configuration.get("disease") or case_context.get("disease")
                assessment_service = ACMGSpecificationAssessmentService()
                resource_rows = {r.id: r for r in db.scalars(select(Resource)).all()}
                total_annotation_rows = db.scalar(select(func.count(Annotation.id)).where(Annotation.analysis_id == analysis.id)) or 0
                existing_assessment_variant_ids = set(db.scalars(select(ACMGAssessment.variant_id).where(ACMGAssessment.analysis_id == analysis.id)).all())
                existing_classifications = db.scalars(select(Classification).where(Classification.analysis_id == analysis.id)).all()
                assessed = len(existing_assessment_variant_ids)
                blocked_variants = 0
                review_variants = 0
                acmg_requires_human_review = False
                proposed_variants = sum(1 for c in existing_classifications if c.state == "PROPOSED")
                batch_size = int(analysis.configuration.get("acmg_batch_size", 250) or 250)
                completed_batches = _completed_batch_keys(acmg_step)
                for start_i, end_i in _chunk_ranges(total_annotation_rows, batch_size):
                    rows = db.scalars(select(Annotation).where(Annotation.analysis_id == analysis.id).order_by(Annotation.created_at, Annotation.id).offset(start_i).limit(end_i - start_i)).all()
                    key = _batch_key(start_i, end_i)
                    if key in completed_batches:
                        # Reconcile counts from persisted ACMG assessments on recovery.
                        continue
                    attempt = int((_batch_checkpoint(acmg_step, start_i, end_i).get("attempt") or 0)) + 1
                    _save_batch_checkpoint(db, acmg_step, start_i, end_i, status="RUNNING", attempt=attempt)
                    batch_assessed = 0
                    batch_proposed = 0
                    batch_review = 0
                    batch_blocked = 0
                    for ann in rows:
                        normalized = (ann.payload or {}).get("normalized") or {}
                        gene = ((normalized.get("gene") or {}).get("symbol"))
                        if not gene:
                            blocked_variants += 1; batch_blocked += 1; continue
                        variant_row = db.get(Variant, ann.variant_id)
                        if variant_row is None:
                            blocked_variants += 1; batch_blocked += 1; continue
                        population_rows_for_variant = db.scalars(select(PopulationObservation).where(PopulationObservation.analysis_id == analysis.id, PopulationObservation.variant_id == ann.variant_id)).all()
                        result = assessment_service.assess_variant(db, analysis=analysis, variant=variant_row, annotation=ann, population_rows=population_rows_for_variant, resource_rows=resource_rows, gene=gene, disease=disease)
                        if result.status in {"PROPOSED", "REQUIRES_REVIEW"} and result.binding.status == "SELECTED":
                            # Evidence and criterion assessments are persisted even
                            # when final combination is not automatable. Only the
                            # classification decision is routed to human review.
                            assessment_service.persist(db, analysis=analysis, variant=variant_row, result=result)
                            assessed += 1
                            batch_assessed += 1
                            if result.status == "PROPOSED":
                                proposed_variants += 1
                                batch_proposed += 1
                            else:
                                review_variants += 1
                                batch_review += 1
                        else:
                            blocked_variants += 1
                            batch_blocked += 1
                    db.commit()
                    _save_batch_checkpoint(
                        db,
                        acmg_step,
                        start_i,
                        end_i,
                        status="SUCCEEDED",
                        attempt=attempt,
                        metadata={
                            "assessed": batch_assessed,
                            "proposed": batch_proposed,
                            "requires_review": batch_review,
                            "blocked": batch_blocked,
                        },
                    )

                if assessed == 0 or review_variants > 0 or blocked_variants > 0:
                    # The analysis itself is not failed. Evidence generation and
                    # criterion persistence have completed for the variants that
                    # could be assessed, while classification automation is
                    # explicitly routed to human review where required.
                    acmg_requires_human_review = True
                    if assessed == 0:
                        review_code = "NO_AUTOMATABLE_CLINGEN_CONTEXT"
                        review_message = (
                            "No variant received a validated, applicable ClinGen specification "
                            "with supported structured criterion configuration. Manual ACMG "
                            "classification is required for all variants in this case."
                        )
                    elif review_variants > 0:
                        review_code = "CLASSIFICATION_COMBINATION_REQUIRES_REVIEW"
                        review_message = (
                            "Criterion evidence was collected and persisted, but one or more "
                            "variants use a ClinGen combination method without a validated "
                            "SIRALOOM combination engine. Human classification review is required."
                        )
                    else:
                        review_code = "ACMG_VARIANTS_REQUIRE_REVIEW"
                        review_message = (
                            "One or more variants could not be safely automated and require "
                            "human ACMG classification review."
                        )
                    mark_step(
                        db,
                        acmg_step,
                        StepStatus.REQUIRES_REVIEW,
                        error_code=review_code,
                        error_message=review_message,
                        metadata={
                            "disease_context_present": bool(disease),
                            "assessed_variants": assessed,
                            "proposed_variants": proposed_variants,
                            "classification_review_variants": review_variants,
                            "blocked_variants": blocked_variants,
                            "classification_automation": "PARTIAL_OR_REVIEW_REQUIRED",
                            "next_step": "review",
                        },
                    )
                    audit.record(
                        event_type="ACMG_ASSESSMENT_REQUIRES_MANUAL_REVIEW",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SERVICE",
                        actor_id="siraloom-acmg-specification-engine",
                        reason=review_message,
                        payload={
                            "assessed": assessed,
                            "proposed_variants": proposed_variants,
                            "classification_review_variants": review_variants,
                            "blocked_variants": blocked_variants,
                        },
                    )
                    db.commit()
                else:
                    mark_step(
                        db,
                        acmg_step,
                        StepStatus.SUCCEEDED,
                        metadata={
                            "assessed_variants": assessed,
                            "proposed_variants": proposed_variants,
                            "classification_review_variants": 0,
                            "blocked_variants": blocked_variants,
                            "classification_automation": "PROPOSED",
                            "disease_context_present": bool(disease),
                        },
                    )
                    audit.record(
                        event_type="ACMG_ASSESSMENT_COMPLETED",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SERVICE",
                        actor_id="siraloom-acmg-specification-engine",
                        payload={
                            "assessed_variants": assessed,
                            "proposed_variants": proposed_variants,
                            "blocked_variants": blocked_variants,
                        },
                    )
                db.commit()
            except Exception as exc:
                mark_step(db, acmg_step, StepStatus.FAILED, error_code="ACMG_ASSESSMENT_FAILED", error_message=str(exc))
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(
                    event_type="ACMG_ASSESSMENT_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id="siraloom-acmg-specification-engine",
                    reason=str(exc),
                )
                db.commit()
                return

        # 7. Human-review gate. Classification approval is distinct from
        # reportability disposition so the workflow can route the reviewer to
        # the exact next clinical action instead of dead-ending at review.
        review_step = _step(db, analysis.id, "review")
        if not _classification_review_gate_ready(db, analysis.id):
            if review_step.status != StepStatus.REQUIRES_REVIEW:
                mark_step(
                    db,
                    review_step,
                    StepStatus.REQUIRES_REVIEW,
                    metadata={"reason": "Awaiting required human classification review.", "next_step": "review"},
                )
            analysis.status = AnalysisStatus.REQUIRES_REVIEW
            analysis.completed_at = None
            db.commit()
            audit.record(
                event_type="WORKFLOW_REQUIRES_REVIEW",
                case_id=analysis.case_id,
                analysis_id=analysis.id,
                actor_type="SYSTEM",
                actor_id="workflow",
                payload={"next_step": "review", "state": "AWAITING_HUMAN_CLASSIFICATION"},
            )
            db.commit()
            return

        if review_step.status != StepStatus.SUCCEEDED:
            mark_step(
                db,
                review_step,
                StepStatus.SUCCEEDED,
                metadata={"review_gate": "PASSED", "next_step": "reportability"},
            )
            audit.record(
                event_type="REVIEW_GATE_COMPLETED",
                case_id=analysis.case_id,
                analysis_id=analysis.id,
                actor_type="SYSTEM",
                actor_id="workflow",
                payload={"next_step": "reportability"},
            )
            db.commit()

        # 8. Reportability is an explicit human gate. Proposed decisions are
        # created automatically, but release cannot proceed until each latest
        # decision is explicitly finalized by an authorized reviewer.
        reportability_step = _step(db, analysis.id, "reportability")
        if reportability_step.status != StepStatus.SUCCEEDED:
            mark_step(db, reportability_step, StepStatus.RUNNING)
            try:
                from backend.app.reporting.reportability import evaluate_analysis, final_reportability_state

                evaluate_analysis(db, analysis)
                reportability_ready, reportability_errors = final_reportability_state(db, analysis.id)
                if not reportability_ready:
                    mark_step(
                        db,
                        reportability_step,
                        StepStatus.REQUIRES_REVIEW,
                        metadata={
                            "reason": "Awaiting final reportability disposition for all classified variants.",
                            "next_step": "reportability",
                            "errors": reportability_errors,
                        },
                    )
                    analysis.status = AnalysisStatus.REQUIRES_REVIEW
                    analysis.completed_at = None
                    audit.record(
                        event_type="WORKFLOW_AWAITING_REPORTABILITY",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SYSTEM",
                        actor_id="workflow",
                        reason="Final reportability disposition is required before report generation.",
                        payload={"next_step": "reportability", "errors": reportability_errors},
                    )
                    db.commit()
                    return

                mark_step(
                    db,
                    reportability_step,
                    StepStatus.SUCCEEDED,
                    metadata={"reportability_gate": "PASSED", "next_step": "report"},
                )
                audit.record(
                    event_type="REPORTABILITY_GATE_COMPLETED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="workflow",
                    payload={"next_step": "report"},
                )
                db.commit()
            except Exception as exc:
                mark_step(
                    db,
                    reportability_step,
                    StepStatus.FAILED,
                    error_code="REPORTABILITY_EVALUATION_FAILED",
                    error_message=str(exc),
                    metadata={"next_step": "reportability"},
                )
                analysis.status = AnalysisStatus.FAILED
                analysis.completed_at = _now()
                audit.record(
                    event_type="REPORTABILITY_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="workflow",
                    reason=str(exc),
                    payload={"error_code": "REPORTABILITY_EVALUATION_FAILED", "next_step": "reportability"},
                )
                db.commit()
                return

        # 9. Generate an immutable report draft after classification and
        # reportability gates have passed. Final clinical release remains a
        # separate human approval.
        report_step = _step(db, analysis.id, "report")
        if report_step.status != StepStatus.SUCCEEDED:
            mark_step(db, report_step, StepStatus.RUNNING)
            try:
                from backend.app.reporting.service import build_report_content, render_pdf
                from backend.app.infrastructure.db.models import Report

                existing_report = db.scalar(
                    select(Report)
                    .where(
                        Report.analysis_id == analysis.id,
                        Report.status == "DRAFT",
                    )
                    .order_by(Report.report_version.desc())
                    .limit(1)
                )
                if existing_report is None:
                    content = build_report_content(
                        db,
                        analysis,
                        str(analysis.configuration.get("report_language") or "en"),
                        report_type=str(
                            analysis.configuration.get(
                                "report_type", "CLINICAL_INTERPRETATION"
                            )
                        ),
                        include_full_evidence=bool(
                            analysis.configuration.get("report_include_full_evidence", False)
                        ),
                    )
                    last_version = db.scalar(
                        select(func.max(Report.report_version)).where(
                            Report.case_id == analysis.case_id,
                            Report.report_type == content["report_type"],
                        )
                    ) or 0
                    version = int(last_version) + 1
                    content["report_version"] = version
                    pdf = render_pdf(content)
                    with NamedTemporaryFile(
                        prefix="siraloom-report-", suffix=".pdf", delete=False
                    ) as report_tmp:
                        report_tmp.write(pdf)
                        report_tmp_path = Path(report_tmp.name)
                    try:
                        artifact = artifacts.put_file(
                            db=db,
                            case_id=analysis.case_id,
                            analysis_id=analysis.id,
                            source_path=report_tmp_path,
                            filename=f"report_v{version}.pdf",
                            artifact_type="REPORT_PDF",
                            media_type="application/pdf",
                            genome_build=analysis.reference_build,
                            metadata={
                                "rendered_format": "PDF",
                                "report_schema_version": content["report_schema_version"],
                                "report_status": "DRAFT",
                            },
                        )
                    finally:
                        report_tmp_path.unlink(missing_ok=True)

                    report = Report(
                        id=__import__("uuid").uuid4(),
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        report_version=version,
                        language=content["language"],
                        report_type=content["report_type"],
                        status="DRAFT",
                        artifact_id=artifact.id,
                        content_json=content,
                    )
                    db.add(report)
                    db.flush()
                    audit.record(
                        event_type="REPORT_GENERATED",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SYSTEM",
                        actor_id="reporting",
                        subject_type="REPORT",
                        subject_id=str(report.id),
                        operation="CREATE",
                        output_artifacts=[{"artifact_id": str(artifact.id), "sha256": artifact.sha256}],
                        payload={"draft": True, "next_step": "export_provenance"},
                    )
                report_step.output_artifacts = (
                    [str(existing_report.artifact_id)]
                    if existing_report is not None and existing_report.artifact_id
                    else [str(report.artifact_id)]
                )
                mark_step(
                    db,
                    report_step,
                    StepStatus.SUCCEEDED,
                    metadata={"report_status": "DRAFT", "next_step": "export_provenance"},
                )
                db.commit()
            except Exception as exc:
                mark_step(
                    db,
                    report_step,
                    StepStatus.FAILED,
                    error_code="REPORT_GENERATION_FAILED",
                    error_message=str(exc),
                )
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(
                    event_type="REPORT_GENERATION_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="reporting",
                    reason=str(exc),
                )
                db.commit()
                return

        # 9. Final report sign-out is the terminal human gate. Provenance is
        # exported only after the report itself is FINAL, so the terminal
        # provenance package contains the actual sign-out event and report lineage.
        report_for_release = db.scalar(
            select(Report)
            .where(
                Report.analysis_id == analysis.id,
                Report.status == "FINAL",
            )
            .order_by(Report.report_version.desc())
            .limit(1)
        )
        if report_for_release is None:
            provenance_step = _step(db, analysis.id, "export_provenance")
            if provenance_step.status != StepStatus.REQUIRES_REVIEW:
                mark_step(
                    db,
                    provenance_step,
                    StepStatus.REQUIRES_REVIEW,
                    metadata={"reason": "Awaiting final report sign-out.", "next_step": "report_finalization"},
                )
            analysis.status = AnalysisStatus.REQUIRES_REVIEW
            analysis.completed_at = None
            db.commit()
            audit.record(
                event_type="WORKFLOW_AWAITING_REPORT_SIGNOUT",
                case_id=analysis.case_id,
                analysis_id=analysis.id,
                actor_type="SYSTEM",
                actor_id="workflow",
                payload={"next_step": "report_finalization"},
            )
            db.commit()
            return

        # Persist a standalone provenance manifest for the fully completed
        # computational + human-review + report-signout workflow. This is
        # separate from the optional case-export ZIP.
        provenance_step = _step(db, analysis.id, "export_provenance")
        if provenance_step.status != StepStatus.SUCCEEDED:
            mark_step(db, provenance_step, StepStatus.RUNNING)
            try:
                import json

                with NamedTemporaryFile(
                    prefix="siraloom-provenance-", suffix=".json", mode="w", encoding="utf-8", delete=False
                ) as provenance_tmp:
                    provenance_tmp.write(json.dumps({
                        "schema_version": "1.0.0",
                        "analysis_id": str(analysis.id),
                        "case_id": str(analysis.case_id),
                        "workflow_id": analysis.workflow_id,
                        "workflow_version": analysis.workflow_version,
                        "reference_build": analysis.reference_build,
                        "steps": [
                            {
                                "step_id": s.step_id,
                                "step_order": s.step_order,
                                "status": s.status,
                                "attempt": s.attempt,
                                "input_artifacts": s.input_artifacts,
                                "output_artifacts": s.output_artifacts,
                                "metadata": s.metadata_json,
                                "error_code": s.error_code,
                                "error_message": s.error_message,
                            }
                            for s in db.scalars(
                                select(WorkflowStep)
                                .where(WorkflowStep.analysis_id == analysis.id)
                                .order_by(WorkflowStep.step_order)
                            )
                        ],
                    }, indent=2, ensure_ascii=False))
                    provenance_tmp_path = Path(provenance_tmp.name)
                try:
                    provenance_artifact = artifacts.put_file(
                        db=db,
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        source_path=provenance_tmp_path,
                        filename="provenance.json",
                        artifact_type="JSON",
                        media_type="application/json",
                        genome_build=analysis.reference_build,
                        metadata={"provenance_schema_version": "1.0.0"},
                    )
                finally:
                    provenance_tmp_path.unlink(missing_ok=True)
                provenance_step.output_artifacts = [str(provenance_artifact.id)]
                mark_step(
                    db,
                    provenance_step,
                    StepStatus.SUCCEEDED,
                    metadata={"provenance_artifact_id": str(provenance_artifact.id), "next_step": "report_finalization"},
                )
                snapshot_analysis_resources(db, analysis)
                analysis.status = AnalysisStatus.SUCCEEDED
                analysis.completed_at = _now()
                audit.record(
                    event_type="PROVENANCE_EXPORT_COMPLETED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="provenance",
                    output_artifacts=[{"artifact_id": str(provenance_artifact.id), "sha256": provenance_artifact.sha256}],
                    payload={"next_step": "analysis_complete"},
                )
                db.commit()
            except Exception as exc:
                mark_step(
                    db,
                    provenance_step,
                    StepStatus.FAILED,
                    error_code="PROVENANCE_EXPORT_FAILED",
                    error_message=str(exc),
                )
                analysis.status = AnalysisStatus.FAILED
                db.commit()
                audit.record(
                    event_type="PROVENANCE_EXPORT_FAILED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="provenance",
                    reason=str(exc),
                )
                db.commit()
                return

        return
    except TransientWorkflowError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        analysis = db.get(Analysis, analysis_id)
        if analysis:
            analysis.status = AnalysisStatus.FAILED
            analysis.completed_at = _now()
            db.commit()
        raise
    finally:
        db.close()


def _classification_review_gate_ready(db: Session, analysis_id: UUID) -> bool:
    """Return True only when every classified variant has a final approved classification."""
    classifications = list(
        db.scalars(
            select(Classification)
            .where(Classification.analysis_id == analysis_id)
            .order_by(Classification.variant_id, Classification.version.desc())
        )
    )
    latest: dict[UUID, Classification] = {}
    for row in classifications:
        latest.setdefault(row.variant_id, row)

    if not latest:
        return False

    return all(
        classification.state == "FINAL"
        and classification.review_status == "APPROVED"
        for classification in latest.values()
    )


def _reportability_gate_ready(db: Session, analysis_id: UUID) -> bool:
    """Return True only when every latest reportability decision is FINAL."""
    classifications = list(
        db.scalars(
            select(Classification)
            .where(Classification.analysis_id == analysis_id)
            .order_by(Classification.variant_id, Classification.version.desc())
        )
    )
    latest: dict[UUID, Classification] = {}
    for row in classifications:
        latest.setdefault(row.variant_id, row)

    if not latest:
        return False

    for variant_id in latest:
        decision = db.scalar(
            select(ReportabilityDecision)
            .where(
                ReportabilityDecision.analysis_id == analysis_id,
                ReportabilityDecision.variant_id == variant_id,
            )
            .order_by(ReportabilityDecision.version.desc())
        )
        if decision is None or decision.status != "FINAL":
            return False

    return True

def _iter_variant_batches(path: Path, genome_build: str, batch_size: int):
    """Yield (zero-based record start, bounded list) from a normalized VCF."""
    batch: list[CanonicalVariant] = []
    start = 0
    for variant in iter_normalized_vcf(path, genome_build):
        batch.append(variant)
        if len(batch) >= batch_size:
            yield start, batch
            start += len(batch)
            batch = []
    if batch:
        yield start, batch


def _partition_variant_ids(partition: AnalysisPartition) -> list[UUID]:
    return [UUID(str(x)) for x in (partition.metadata_json or {}).get("variant_ids", [])]


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _require_registered_resource(
    db: Session,
    *,
    resource_id: object,
    expected_type: str,
    expected_build: str,
    expected_provider: str | None = None,
) -> Resource:
    """Consume only an explicitly registered resource version.

    Workflow execution never creates scientific resources. The analysis pins a
    registry UUID; the registry row supplies the provider/version/build identity
    used by the downstream observation provenance. SUPERSEDED resources remain
    consumable when explicitly pinned by an existing analysis so historical
    analyses remain reproducible; unregistered resources are never synthesized.
    """
    if not resource_id:
        raise ResourceConsumptionError(
            "RESOURCE_REQUIRED",
            f"Analysis must explicitly select a registered {expected_type} resource before population processing.",
        )
    try:
        rid = UUID(str(resource_id))
    except (TypeError, ValueError) as exc:
        raise ResourceConsumptionError(
            "RESOURCE_REQUIRED",
            f"Configured resource ID is not a valid UUID: {resource_id}",
        ) from exc

    row = db.get(Resource, rid)
    if row is None:
        raise ResourceConsumptionError(
            "RESOURCE_NOT_FOUND",
            f"Registered resource {rid} was not found.",
        )
    if row.resource_type != expected_type:
        raise ResourceConsumptionError(
            "RESOURCE_TYPE_MISMATCH",
            f"Resource {rid} is {row.resource_type}, expected {expected_type}.",
        )
    if row.genome_build and normalize_build(row.genome_build) != normalize_build(expected_build):
        raise ResourceConsumptionError(
            "RESOURCE_BUILD_MISMATCH",
            f"Resource {rid} is registered for {row.genome_build}, not {expected_build}.",
        )
    if expected_provider and row.provider != expected_provider:
        raise ResourceConsumptionError(
            "RESOURCE_PROVIDER_MISMATCH",
            f"Resource {rid} is provided by {row.provider}, expected {expected_provider}.",
        )
    if row.status not in {"ACTIVE", "SUPERSEDED"}:
        raise ResourceConsumptionError(
            "RESOURCE_UNAVAILABLE",
            f"Resource {rid} has registry status {row.status} and cannot be consumed.",
        )
    return row


def _existing_normalized_artifact(db: Session, analysis_id: UUID) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.analysis_id == analysis_id, Artifact.artifact_type == "NORMALIZED_VCF")
        .order_by(Artifact.created_at.desc())
        .limit(1)
    )


def _step(db: Session, analysis_id: UUID, step_id: str) -> WorkflowStep:
    step = db.scalar(
        select(WorkflowStep).where(
            WorkflowStep.analysis_id == analysis_id,
            WorkflowStep.step_id == step_id,
        )
    )
    if not step:
        ensure_steps(db, analysis_id)
        step = db.scalar(
            select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == step_id,
            )
        )
    if step is None:
        raise RuntimeError(f"Workflow step missing: {step_id}")
    return step
