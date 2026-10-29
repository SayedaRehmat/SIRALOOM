from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from uuid import UUID, uuid5

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.acmg.source_assertions import persist_clingen_source_assertions
from backend.app.adapters.annotation.genebe import GeneBeError, GeneBeProvider
from backend.app.adapters.annotation.genebe_normalizer import normalize_gene_be_variant
from backend.app.adapters.annotation.normalizer import normalize_annotation_payload
from backend.app.adapters.annotation.vep import VEPProviderError
from backend.app.adapters.clingen.gene_disease_validity import (
    ClinGenGeneDiseaseValidityError,
    ClinGenGeneDiseaseValidityProvider,
)
from backend.app.adapters.clingen.variant_pathogenicity import (
    ClinGenVariantPathogenicityError,
    ClinGenVariantPathogenicityProvider,
)
from backend.app.adapters.evidence.clinvar import ClinVarProviderError, ClinVarVCVProvider
from backend.app.adapters.phenotype.hpo_obo import HPOOntologyError
from backend.app.adapters.phenotype.hpoa import HPOAError
from backend.app.adapters.population.gnomad import (
    GnomADGraphQLProvider,
    GnomADProviderError,
    PopulationObservationData,
)
from backend.app.adapters.population.secondary import (
    LocalTabixSecondaryPopulationProvider,
    SecondaryPopulationProviderError,
)
from backend.app.application.analysis import validate_analysis_input_artifact
from backend.app.auth.authorization import get_analysis_variant_ids
from backend.app.config import settings
from backend.app.domain.artifact_integrity import verify_artifact_file
from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.local_uri import local_path_from_uri
from backend.app.domain.normalization import (
    NormalizationError,
    UnsupportedVariantError,
    iter_normalized_vcf,
)
from backend.app.domain.profile_runtime_resources import (
    ProfileRuntimeResourceError,
    resolve_profile_runtime_resource,
    resolve_profile_runtime_resources,
)
from backend.app.domain.provider_registry import ProviderRegistryError, register_builtin_providers
from backend.app.domain.reanalysis import (
    STEP_ORDER,
    mark_reanalysis_completed,
    snapshot_analysis_resources,
)
from backend.app.domain.reference import ReferenceError
from backend.app.domain.reference_package import (
    ReferencePackageError,
    load_reference_package,
    sha256_file,
)
from backend.app.domain.resource_capabilities import CapabilityRequirement, ResourceCapability
from backend.app.domain.resource_execution import (
    ResourceExecutionError,
    complete_resource_execution,
    resolve_resource_execution,
    start_resource_execution,
)
from backend.app.domain.resource_execution_plan import build_resource_execution_plan
from backend.app.domain.resource_fallback import resolve_resource_with_fallback
from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.storage_profiles import (
    StorageProfileError,
    artifact_store_for_organization,
    artifact_store_for_uri,
)
from backend.app.domain.variant_identity import canonical_key, normalize_build, stable_variant_uuid
from backend.app.domain.vcf_tools import (
    VCFToolError,
    classify_records,
    normalize_vcf_with_bcftools,
    route_vcf_records,
)
from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_reference_alleles,
    validate_vcf_strict,
)
from backend.app.domain.workflow_decision import OutcomeKind, WorkflowAction, decide_step_outcome
from backend.app.domain.workflow_decision_persistence import record_workflow_decision
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    AnalysisPartition,
    Annotation,
    Artifact,
    Case,
    Classification,
    Evidence,
    PopulationObservation,
    Report,
    ReportabilityDecision,
    Resource,
    ResourceExecutionRecord,
    Variant,
    WorkflowStep,
)
from backend.app.partition_scheduler import (
    PartitionCapacityError,
    PartitionLeaseError,
    PartitionScheduler,
    configure_partition,
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
    """Signals a transient workflow condition that a durable queue may retry."""

    def __init__(
        self,
        message: str,
        *,
        countdown: int = 10,
        max_retries: int = 3,
        error_code: str = "ANNOTATION_PROVIDER_RETRY_EXHAUSTED",
    ):
        super().__init__(message)
        self.countdown = max(1, countdown)
        self.max_retries = max(0, int(max_retries))
        self.error_code = error_code


def _schedule_transient_step_retry(
    db: Session,
    *,
    analysis_id: UUID,
    step_id: str,
    error_code: str,
    error_message: str,
    event_type: str,
    actor_id: str,
    next_step: str,
) -> None:
    """Persist a retryable stage failure before the Celery wrapper retries it.

    The stage's durable checkpoint remains available; the analysis is not marked
    terminally failed until the bounded retry policy is exhausted.
    """
    db.rollback()
    analysis = db.get(Analysis, analysis_id)
    step = _step(db, analysis_id, step_id)
    if analysis is not None:
        analysis.status = AnalysisStatus.RUNNING
        analysis.completed_at = None
        db.add(analysis)
    metadata = dict(step.metadata_json or {})
    metadata["next_step"] = next_step
    metadata["retry_policy"] = "bounded_transient_retry"
    step.status = StepStatus.RETRYING
    step.error_code = error_code
    step.error_message = error_message
    step.metadata_json = metadata
    step.last_heartbeat = _now()
    step.updated_at = _now()
    db.add(step)
    AuditService(db).record(
        event_type=event_type,
        case_id=analysis.case_id if analysis is not None else None,
        analysis_id=analysis_id,
        actor_type="SYSTEM",
        actor_id=actor_id,
        reason=error_message,
        payload={"error_code": error_code, "next_step": next_step},
    )
    db.commit()


def _route_step_to_human_review(
    db: Session,
    *,
    analysis_id: UUID,
    step_id: str,
    error_code: str,
    error_message: str,
    event_type: str,
    actor_id: str,
    next_step: str,
    payload: dict | None = None,
) -> None:
    """Persist a recoverable scientific/resource gap for explicit human action.

    This is not a technical success: downstream clinical decisions remain gated,
    but the analysis is kept resumable instead of being terminally FAILED/BLOCKED.
    """
    analysis = db.get(Analysis, analysis_id)
    step = _step(db, analysis_id, step_id)
    mark_step(
        db,
        step,
        StepStatus.REQUIRES_REVIEW,
        error_code=error_code,
        error_message=error_message,
        metadata={"next_step": next_step, "human_action_required": True},
    )
    if analysis is not None:
        analysis.status = AnalysisStatus.REQUIRES_REVIEW
        analysis.completed_at = None
        db.add(analysis)
    db.commit()
    AuditService(db).record(
        event_type=event_type,
        case_id=analysis.case_id if analysis is not None else None,
        analysis_id=analysis_id,
        actor_type="SYSTEM",
        actor_id=actor_id,
        reason=error_message,
        payload={"error_code": error_code, "next_step": next_step, "human_action_required": True, **(payload or {})},
    )
    db.commit()


class ResourceConsumptionError(RuntimeError):
    """Signals that a workflow resource is not governed or is incompatible."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _resources_by_ids(db: Session, resource_ids) -> dict[UUID, Resource]:
    ids = {resource_id for resource_id in resource_ids if resource_id is not None}
    if not ids:
        return {}
    return {
        row.id: row
        for row in db.scalars(select(Resource).where(Resource.id.in_(ids))).all()
    }


def _require_population_resource_rows(
    db: Session,
    *,
    analysis_id: UUID,
    organization_id: UUID,
    observations: list[PopulationObservation],
) -> dict[UUID, Resource]:
    """Require every persisted population observation to retain tenant-safe provenance."""
    if any(observation.analysis_id != analysis_id for observation in observations):
        raise ResourceConsumptionError(
            "POPULATION_ANALYSIS_LINEAGE_INVALID",
            "A population observation is not linked to the current analysis.",
        )

    resource_ids = {observation.resource_id for observation in observations}
    if None in resource_ids:
        raise ResourceConsumptionError(
            "POPULATION_RESOURCE_MISSING",
            "A population observation has no source resource.",
        )

    resource_rows = _resources_by_ids(db, resource_ids)
    if resource_ids - resource_rows.keys():
        raise ResourceConsumptionError(
            "POPULATION_RESOURCE_MISSING",
            "A population observation references a missing source resource.",
        )
    if any(
        resource.organization_id not in {None, organization_id}
        for resource in resource_rows.values()
    ):
        raise ResourceConsumptionError(
            "POPULATION_RESOURCE_TENANT_MISMATCH",
            "A population observation references a resource outside this organization.",
        )
    return resource_rows


def _succeeded_population_execution(
    db: Session,
    *,
    analysis_id: UUID,
    resource_id: UUID,
    batch_key: str,
):
    """Return a durable succeeded population execution for this variant query."""
    return db.scalar(
        select(ResourceExecutionRecord.id).where(
            ResourceExecutionRecord.analysis_id == analysis_id,
            ResourceExecutionRecord.step_id == "population",
            ResourceExecutionRecord.resource_id == resource_id,
            ResourceExecutionRecord.batch_key == batch_key,
            ResourceExecutionRecord.status == "SUCCEEDED",
        ).limit(1)
    )


def _succeeded_evidence_execution(
    db: Session,
    *,
    analysis_id: UUID,
    resource_id: UUID,
    batch_key: str,
    request_fingerprint: str,
    execution_kind: str,
) -> bool:
    """Check whether this exact external evidence query and its rows committed."""
    rows = db.scalars(
        select(ResourceExecutionRecord).where(
            ResourceExecutionRecord.analysis_id == analysis_id,
            ResourceExecutionRecord.step_id == "build_evidence",
            ResourceExecutionRecord.resource_id == resource_id,
            ResourceExecutionRecord.batch_key == batch_key,
            ResourceExecutionRecord.request_fingerprint == request_fingerprint,
            ResourceExecutionRecord.status.in_(("SUCCESS", "NO_DATA")),
        )
    ).all()
    return any(
        (row.metadata_json or {}).get("execution_kind") == execution_kind
        for row in rows
    )


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

def _completed_acmg_batch_outcome_counts(step: WorkflowStep, start: int, end: int) -> tuple[int, int]:
    """Restore human-review/blocking counters from a durable successful batch checkpoint."""
    checkpoint = _batch_checkpoint(step, start, end)
    return (
        int(checkpoint.get("requires_review", 0) or 0),
        int(checkpoint.get("blocked", 0) or 0),
    )

def _ensure_annotation_request_fingerprint(
    payloads: list[dict],
    *,
    analysis: Analysis,
    start: int,
    end: int,
    resource: Resource,
    provider_id: str,
    provider_version: str,
) -> str:
    """Ensure API and local providers share a stable, governed request identity."""
    if not isinstance(payloads, list) or not payloads or not all(isinstance(item, dict) for item in payloads):
        raise ValueError("Annotation provider response must be a non-empty list of objects.")
    provenances = []
    for item in payloads:
        provenance = item.get("_siraloom_annotation_provenance")
        if not isinstance(provenance, dict):
            raise ValueError("Annotation response record is missing provider provenance.")
        if provenance.get("provider") != provider_id or provenance.get("provider_version") != provider_version:
            raise ValueError("Annotation response provenance does not match the selected provider.")
        if not isinstance(provenance.get("response_sha256"), str) or not provenance["response_sha256"]:
            raise ValueError("Annotation response record is missing its response fingerprint.")
        provenances.append(provenance)
    response_hashes = {provenance["response_sha256"] for provenance in provenances}
    if len(response_hashes) != 1:
        raise ValueError("Annotation response records do not share one provider response fingerprint.")
    existing_fingerprints = {
        str(provenance["request_fingerprint"])
        for provenance in provenances
        if provenance.get("request_fingerprint")
    }
    if len(existing_fingerprints) > 1:
        raise ValueError("Annotation response records have conflicting request fingerprints.")
    if existing_fingerprints:
        fingerprint = next(iter(existing_fingerprints))
        for item, provenance in zip(payloads, provenances):
            normalized_provenance = dict(provenance)
            normalized_provenance["request_fingerprint"] = fingerprint
            item["_siraloom_annotation_provenance"] = normalized_provenance
        return fingerprint
    variants = []
    for item in payloads:
        provenance = dict(item.get("_siraloom_annotation_provenance") or {})
        variants.append({
            "chromosome": item.get("chr"),
            "position": item.get("pos"),
            "reference": item.get("ref"),
            "alternate": item.get("alt"),
            "assembly": item.get("genome") or provenance.get("assembly") or analysis.reference_build,
        })
    request_material = {
        "analysis_id": str(analysis.id),
        "batch_key": _batch_key(start, end),
        "provider_id": provider_id,
        "provider_version": provider_version,
        "resource_id": str(resource.id),
        "resource_version": resource.version,
        "resource_checksum": resource.checksum,
        "reference_build": analysis.reference_build,
        "variants": variants,
    }
    fingerprint = hashlib.sha256(
        json.dumps(request_material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    for item in payloads:
        provenance = dict(item.get("_siraloom_annotation_provenance") or {})
        provenance["request_fingerprint"] = fingerprint
        item["_siraloom_annotation_provenance"] = provenance
    return fingerprint


def _persist_annotation_response_checkpoint(
    db: Session,
    artifacts: ArtifactStore,
    *,
    analysis: Analysis,
    step: WorkflowStep,
    start: int,
    end: int,
    payloads: list[dict],
    resource: Resource,
    provider_id: str,
    provider_version: str,
) -> Artifact:
    """Durably store a provider response before attempting annotation-row persistence.

    The artifact reference and batch checkpoint are committed together. On retry,
    the workflow can replay the exact received payload instead of issuing a second
    provider request after a crash between response receipt and annotation writes.
    """
    if not isinstance(payloads, list) or not payloads or not all(isinstance(x, dict) for x in payloads):
        raise ValueError("Annotation provider response must be a non-empty list of objects.")
    provenances = [
        item.get("_siraloom_annotation_provenance")
        for item in payloads
    ]
    if any(not isinstance(item, dict) for item in provenances):
        raise ValueError("Annotation response record is missing provider provenance.")
    provenance = provenances[0]
    request_fingerprint = provenance.get("request_fingerprint")
    response_sha256 = provenance.get("response_sha256")
    if any(
        item.get("provider") != provider_id
        or item.get("provider_version") != provider_version
        or item.get("request_fingerprint") != request_fingerprint
        or item.get("response_sha256") != response_sha256
        for item in provenances
    ):
        raise ValueError("Annotation response records have inconsistent provider provenance.")
    if not request_fingerprint or not response_sha256:
        raise ValueError("Annotation response is missing its request/response fingerprint.")
    response_material = {
        "schema_version": 1,
        "analysis_id": str(analysis.id),
        "batch_key": _batch_key(start, end),
        "provider_id": provider_id,
        "provider_version": provider_version,
        "resource_id": str(resource.id),
        "resource_version": resource.version,
        "request_fingerprint": provenance["request_fingerprint"],
        "response_sha256": provenance["response_sha256"],
        "payloads": payloads,
    }
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="siraloom-annotation-response-",
        suffix=".json",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(response_material, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    try:
        artifact = artifacts.put_file(
            db=db,
            case_id=analysis.case_id,
            analysis_id=analysis.id,
            source_path=temp_path,
            filename=f"annotation-response-{start}-{end}.json",
            artifact_type="ANNOTATION_PROVIDER_RESPONSE",
            media_type="application/json",
            genome_build=analysis.reference_build,
            validation_status="VALIDATED",
            metadata={
                "step_id": "annotate",
                "batch_key": _batch_key(start, end),
                "provider_id": provider_id,
                "provider_version": provider_version,
                "resource_id": str(resource.id),
                "resource_version": resource.version,
                "request_fingerprint": provenance["request_fingerprint"],
                "response_sha256": provenance["response_sha256"],
            },
        )
        _save_batch_checkpoint(
            db,
            step,
            start,
            end,
            status="RESPONSE_PERSISTED",
            metadata={
                "provider": provider_id,
                "provider_version": provider_version,
                "resource_id": str(resource.id),
                "resource_version": resource.version,
                "request_fingerprint": provenance["request_fingerprint"],
                "response_sha256": provenance["response_sha256"],
                "response_artifact_id": str(artifact.id),
                "response_artifact_sha256": artifact.sha256,
            },
            commit=False,
        )
        db.commit()
        return artifact
    finally:
        temp_path.unlink(missing_ok=True)


def _load_annotation_response_checkpoint(
    db: Session,
    *,
    step: WorkflowStep,
    start: int,
    end: int,
    analysis: Analysis,
    resource: Resource,
    provider_id: str,
    provider_version: str,
    temporary_paths: list[Path],
) -> list[dict] | None:
    """Load and validate the exact response artifact saved for an interrupted batch."""
    checkpoint = _batch_checkpoint(step, start, end)
    artifact_id = checkpoint.get("response_artifact_id")
    if not artifact_id:
        return None
    artifact = db.get(Artifact, UUID(str(artifact_id)))
    if artifact is None or artifact.artifact_type != "ANNOTATION_PROVIDER_RESPONSE":
        raise RuntimeError("Persisted annotation response checkpoint points to a missing or invalid artifact.")
    metadata = artifact.metadata_json or {}
    expected = {
        "step_id": "annotate",
        "batch_key": _batch_key(start, end),
        "provider_id": provider_id,
        "provider_version": provider_version,
        "resource_id": str(resource.id),
        "resource_version": resource.version,
    }
    if artifact.analysis_id != analysis.id or artifact.case_id != analysis.case_id:
        raise RuntimeError("Persisted annotation response belongs to a different analysis or case.")
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Persisted annotation response resource/provider identity conflicts with the active execution plan.")
    if checkpoint.get("response_artifact_sha256") != artifact.sha256:
        raise RuntimeError("Persisted annotation response artifact checksum conflicts with its workflow checkpoint.")
    path = _materialize_artifact_for_worker(db, artifact, temporary_paths)
    if sha256_file(path) != artifact.sha256:
        raise RuntimeError("Persisted annotation response artifact failed SHA-256 verification.")
    with path.open("r", encoding="utf-8") as handle:
        response = json.load(handle)
    if (
        response.get("schema_version") != 1
        or response.get("analysis_id") != str(analysis.id)
        or response.get("batch_key") != _batch_key(start, end)
        or response.get("provider_id") != provider_id
        or response.get("provider_version") != provider_version
        or response.get("resource_id") != str(resource.id)
        or response.get("resource_version") != resource.version
        or response.get("request_fingerprint") != checkpoint.get("request_fingerprint")
        or response.get("response_sha256") != checkpoint.get("response_sha256")
        or not isinstance(response.get("payloads"), list)
    ):
        raise RuntimeError("Persisted annotation response failed its provenance/identity checks.")
    return response["payloads"]

def _count_persisted_evidence(db: Session, analysis_id: UUID) -> int:
    """Count durable evidence rows for an analysis, including prior attempts.

    Evidence rows and their batch-success checkpoint are committed separately.
    After worker loss between those commits, retry deduplicates the persisted rows;
    the per-attempt creation counter is therefore not a reliable existence signal.
    """
    return int(
        db.scalar(select(func.count(Evidence.id)).where(Evidence.analysis_id == analysis_id))
        or 0
    )


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
    if max_order >= STEP_ORDER["build_evidence"]:
        parent_evidence_step = parent_steps.get("build_evidence")
        child_evidence_step = child_steps.get("build_evidence")
        if parent_evidence_step and child_evidence_step:
            from backend.app.domain.clinical_input_snapshot import (
                inherit_reused_case_clinical_input_snapshot,
            )

            try:
                inherit_reused_case_clinical_input_snapshot(
                    parent_evidence_step, child_evidence_step
                )
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
            db.add(child_evidence_step)

    artifact_id_map: dict[str, str] = {}

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
            copied_normalized = Artifact(
                id=uuid4(), analysis_id=analysis.id, case_id=analysis.case_id,
                artifact_type=parent_normalized.artifact_type, filename=parent_normalized.filename,
                media_type=parent_normalized.media_type, size_bytes=parent_normalized.size_bytes,
                sha256=parent_normalized.sha256, storage_uri=parent_normalized.storage_uri,
                genome_build=parent_normalized.genome_build, specimen_id=parent_normalized.specimen_id,
                paired_artifact_id=parent_normalized.paired_artifact_id,
                validation_status=parent_normalized.validation_status,
                metadata_json={**(parent_normalized.metadata_json or {}), "reused_from_analysis_id": str(parent_id)},
                created_at=parent_normalized.created_at,
            )
            db.add(copied_normalized)
            artifact_id_map[str(parent_normalized.id)] = str(copied_normalized.id)
        elif parent_normalized:
            child_normalized = _existing_normalized_artifact(db, analysis.id)
            artifact_id_map[str(parent_normalized.id)] = str(child_normalized.id)

        # Workflow step records are copied before their artifact rows. Remap
        # every analysis-scoped artifact they reference into the child analysis;
        # case-scoped source inputs remain shared and keep their original IDs.
        referenced_ids: set[UUID] = set()
        for step_id, order in WORKFLOW_STEPS:
            if order > max_order:
                continue
            source = parent_steps.get(step_id)
            if source is None or source.status != StepStatus.SUCCEEDED:
                continue
            for references in (source.input_artifacts or [], source.output_artifacts or []):
                for reference in references:
                    raw_id = reference.get("artifact_id") if isinstance(reference, dict) else reference
                    try:
                        referenced_ids.add(UUID(str(raw_id)))
                    except (TypeError, ValueError):
                        continue
        for partition in db.scalars(select(AnalysisPartition).where(
            AnalysisPartition.analysis_id == parent_id,
            AnalysisPartition.step_id.in_([
                name for name, order in WORKFLOW_STEPS if order <= max_order
            ]),
        )).all():
            if partition.input_artifact_id is not None:
                referenced_ids.add(partition.input_artifact_id)

        pending_artifact_ids = list(referenced_ids)
        while pending_artifact_ids:
            referenced_id = pending_artifact_ids.pop()
            referenced_artifact = db.get(Artifact, referenced_id)
            if referenced_artifact is None or referenced_artifact.case_id != analysis.case_id:
                raise RuntimeError("Reused workflow step references an artifact outside its case")
            if referenced_artifact.analysis_id not in {None, parent_id}:
                raise RuntimeError(
                    "Reused workflow step references an artifact outside its parent analysis"
                )
            paired_id = referenced_artifact.paired_artifact_id
            if paired_id is not None and paired_id not in referenced_ids:
                referenced_ids.add(paired_id)
                pending_artifact_ids.append(paired_id)

        for source_id in referenced_ids:
            key = str(source_id)
            if key in artifact_id_map:
                continue
            source_artifact = db.get(Artifact, source_id)
            if source_artifact is None or source_artifact.case_id != analysis.case_id:
                raise RuntimeError("Reused workflow step references an artifact outside its case")
            if source_artifact.analysis_id is None:
                continue
            if source_artifact.analysis_id != parent_id:
                raise RuntimeError(
                    "Reused workflow step references an artifact outside its parent analysis"
                )
            copied_artifact = Artifact(
                id=uuid4(), analysis_id=analysis.id, case_id=source_artifact.case_id,
                artifact_type=source_artifact.artifact_type,
                filename=source_artifact.filename, media_type=source_artifact.media_type,
                size_bytes=source_artifact.size_bytes, sha256=source_artifact.sha256,
                storage_uri=source_artifact.storage_uri, genome_build=source_artifact.genome_build,
                specimen_id=source_artifact.specimen_id,
                paired_artifact_id=source_artifact.paired_artifact_id,
                validation_status=source_artifact.validation_status,
                metadata_json={
                    **(source_artifact.metadata_json or {}),
                    "reused_from_analysis_id": str(parent_id),
                },
                created_at=source_artifact.created_at,
            )
            db.add(copied_artifact)
            artifact_id_map[key] = str(copied_artifact.id)

        db.flush()

        def remap_artifact_metadata(value):
            if isinstance(value, dict):
                result = {}
                for key, item in value.items():
                    if key in {"artifact_id", "indexed_artifact_id", "paired_artifact_id"}:
                        result[key] = artifact_id_map.get(str(item), item)
                    else:
                        result[key] = remap_artifact_metadata(item)
                return result
            if isinstance(value, list):
                return [remap_artifact_metadata(item) for item in value]
            return value

        for _source_id, copied_id in artifact_id_map.items():
            copied_artifact = db.get(Artifact, UUID(copied_id))
            if copied_artifact is None:
                raise RuntimeError("Reused child artifact was not persisted")
            if copied_artifact.paired_artifact_id is not None:
                paired_id = artifact_id_map.get(str(copied_artifact.paired_artifact_id))
                if paired_id is not None:
                    copied_artifact.paired_artifact_id = UUID(paired_id)
            copied_artifact.metadata_json = remap_artifact_metadata(
                copied_artifact.metadata_json or {}
            )
            db.add(copied_artifact)

        def remap_references(references):
            remapped = []
            for reference in references or []:
                if isinstance(reference, dict):
                    item = dict(reference)
                    if item.get("artifact_id") is not None:
                        item["artifact_id"] = artifact_id_map.get(
                            str(item["artifact_id"]), str(item["artifact_id"])
                        )
                    remapped.append(item)
                elif isinstance(reference, str):
                    remapped.append(artifact_id_map.get(reference, reference))
                else:
                    remapped.append(reference)
            return remapped

        for step_id, order in WORKFLOW_STEPS:
            if order > max_order:
                continue
            target = child_steps.get(step_id)
            if target is not None and target.status == StepStatus.SUCCEEDED:
                target.input_artifacts = remap_references(target.input_artifacts)
                target.output_artifacts = remap_references(target.output_artifacts)
                db.add(target)

        for partition in db.scalars(select(AnalysisPartition).where(
            AnalysisPartition.analysis_id == analysis.id,
            AnalysisPartition.step_id.in_([
                name for name, order in WORKFLOW_STEPS if order <= max_order
            ]),
        )).all():
            if partition.input_artifact_id is not None:
                mapped = artifact_id_map.get(str(partition.input_artifact_id))
                if mapped is not None:
                    partition.input_artifact_id = UUID(mapped)
                    db.add(partition)

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
                    input_artifact_id=UUID(artifact_id_map[str(src.input_artifact_id)])
                    if src.input_artifact_id is not None
                    and str(src.input_artifact_id) in artifact_id_map
                    else src.input_artifact_id,
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
    started_resource_executions = db.scalars(
        select(ResourceExecutionRecord)
        .where(
            ResourceExecutionRecord.analysis_id == analysis_id,
            ResourceExecutionRecord.status == "STARTED",
        )
        .with_for_update()
    ).all()

    if not running_steps and not running_partitions and not started_resource_executions:
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

    # A worker can die after an external call or durable checkpoint without
    # finalizing its execution row. Close that attempt as interrupted so a
    # later successful replay does not leave an indefinitely STARTED record.
    for execution in started_resource_executions:
        execution.status = "INTERRUPTED"
        execution.error_code = "WORKER_INTERRUPTED"
        execution.error_message = "Worker stopped before finalizing the resource execution record."
        execution.completed_at = recovery_time
        db.add(execution)

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
            "recovered_resource_executions": len(started_resource_executions),
            "next_step": running_steps[0].step_id if running_steps else None,
        },
    )
    db.commit()
    return True


def _materialize_artifact_for_worker(
    db: Session, artifact: Artifact, temporary_paths: list[Path]
) -> Path:
    """Resolve an immutable artifact URI to a worker-local file for tools.

    Scientific tools such as bcftools and VEP require filesystem paths. Cloud
    artifact URIs must therefore be downloaded to a worker-local temporary
    file rather than incorrectly interpreted as a local path.
    """
    uri = str(artifact.storage_uri or "")
    case = db.get(Case, artifact.case_id)
    if case is None:
        raise RuntimeError(f"Artifact {artifact.id} is not linked to an existing case.")
    try:
        store = artifact_store_for_uri(
            db, organization_id=case.organization_id, storage_uri=uri
        )
    except StorageProfileError as exc:
        raise RuntimeError(
            f"Artifact {artifact.id} storage URI is not assigned to its organization."
        ) from exc
    if uri.startswith("gs://"):
        suffix = "".join(Path(artifact.filename).suffixes) or ".bin"
        with NamedTemporaryFile(
            prefix="siraloom-artifact-",
            suffix=suffix,
            delete=False,
        ) as handle:
            local_path = Path(handle.name)
        try:
            store.download_to_file(
                uri,
                local_path,
                expected_sha256=artifact.sha256,
                expected_size_bytes=artifact.size_bytes,
            )
            verify_artifact_file(
                local_path,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
            )
        except Exception:
            local_path.unlink(missing_ok=True)
            raise
        temporary_paths.append(local_path)
        return local_path

    if not isinstance(store, ArtifactStore):
        raise RuntimeError(f"Artifact {artifact.id} storage adapter does not match its URI.")
    local_path = store.local_path(uri)
    if not local_path.is_file():
        raise RuntimeError(
            f"Artifact {artifact.id} is not available on this worker: {uri}"
        )
    verify_artifact_file(
        local_path,
        sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
    )
    return local_path


def _persist_annotation_batch_rows(
    db: Session,
    *,
    analysis: Analysis,
    provider,
    annotation_resource: Resource,
    variant_ids: dict[str, UUID],
    existing_rows: list[Annotation],
    payloads: list[dict],
    batch_key: str,
) -> tuple[int, int]:
    """Validate and idempotently persist one provider batch's annotation rows.

    This helper persists provider-returned observations only; it does not alter
    scientific interpretation. The response artifact is checkpointed before
    this call, allowing a retry to replay the exact payload. Row writes commit
    before the batch success checkpoint, so retries must recognize existing
    observations and avoid duplicates.
    """
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
            raise GeneBeError(f"Invalid annotation response record in batch {batch_key}") from exc
        if payload_key in payloads_by_key:
            raise GeneBeError(f"Duplicate provider result for canonical variant {payload_key}")
        payloads_by_key[payload_key] = payload

    expected_batch = set(variant_ids)
    if payloads_by_key.keys() != expected_batch:
        missing = expected_batch - payloads_by_key.keys()
        extra = payloads_by_key.keys() - expected_batch
        raise GeneBeError(
            f"Provider result set does not match batch {batch_key}; missing={len(missing)}, extra={len(extra)}"
        )

    existing_by_variant = {str(row.variant_id): row for row in existing_rows}
    new_count = 0
    for canonical, row_id in variant_ids.items():
        if str(row_id) in existing_by_variant:
            continue
        payload = payloads_by_key[canonical]
        provenance = dict(payload.pop("_siraloom_annotation_provenance", {}) or {})
        normalized = normalize_annotation_payload(provider.provider_id, payload)
        db.add(Annotation(
            id=__import__("uuid").uuid4(),
            variant_id=row_id,
            analysis_id=analysis.id,
            provider_name=provider.provider_id,
            provider_version=provider.provider_version,
            resource_id=annotation_resource.id,
            resource_name=annotation_resource.name,
            resource_version=annotation_resource.version,
            request_fingerprint=provenance.get("request_fingerprint"),
            response_sha256=provenance.get("response_sha256"),
            request_metadata={
                "endpoint": provenance.get("endpoint"),
                "genome": provenance.get("genome"),
                "provider": provenance.get("provider"),
                "provider_version": provenance.get("provider_version"),
                "annotation_options": provenance.get("annotation_options"),
                "runtime_check": provenance.get("runtime_check"),
            },
            observed_at=(
                datetime.fromisoformat(provenance["observed_at"])
                if provenance.get("observed_at") else None
            ),
            retry_count=int(provenance.get("retry_count", 0) or 0),
            payload={"raw": payload, "normalized": normalized},
        ))
        new_count += 1
    db.commit()
    return new_count, len(payloads_by_key)


def _persist_terminal_provenance(
    db: Session,
    *,
    artifacts: ArtifactStore,
    analysis: Analysis,
    provenance_step: WorkflowStep,
    audit: AuditService,
) -> Artifact:
    """Atomically persist terminal provenance and mark the analysis successful.

    A deterministic artifact identity makes a retry overwrite any orphaned
    filesystem object left by a failed database transaction instead of
    creating duplicate provenance artifacts.
    """
    import json

    provenance_artifact_id = uuid5(analysis.id, "siraloom:terminal-provenance-manifest")

    # Stage the successful terminal-step state before rendering the manifest so
    # the manifest describes the intended terminal state. Nothing is committed
    # until the artifact, resource snapshots, audit event, and analysis status
    # are all ready.
    now = _now()
    provenance_step.status = StepStatus.SUCCEEDED
    provenance_step.updated_at = now
    provenance_step.completed_at = now
    provenance_step.last_heartbeat = now
    provenance_step.error_code = None
    provenance_step.error_message = None
    provenance_step.output_artifacts = [str(provenance_artifact_id)]
    provenance_step.metadata_json = {
        **(provenance_step.metadata_json or {}),
        "provenance_artifact_id": str(provenance_artifact_id),
        "next_step": "analysis_complete",
    }
    db.add(provenance_step)

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
        provenance_artifact = _put_idempotent_stage_artifact(
            artifacts,
            artifact_id=provenance_artifact_id,
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

    snapshot_analysis_resources(db, analysis, commit=False)
    analysis.status = AnalysisStatus.SUCCEEDED
    analysis.completed_at = _now()
    db.add(analysis)
    audit.record(
        event_type="PROVENANCE_EXPORT_COMPLETED",
        case_id=analysis.case_id,
        analysis_id=analysis.id,
        actor_type="SYSTEM",
        actor_id="provenance",
        output_artifacts=[{"artifact_id": str(provenance_artifact.id), "sha256": provenance_artifact.sha256}],
        payload={"next_step": "analysis_complete"},
    )
    # Close the linked candidate in the same transaction as the terminal
    # provenance artifact and SUCCEEDED transition. This also reconciles a
    # candidate returned to PENDING after a queue error when its child still
    # reached successful completion.
    mark_reanalysis_completed(db, analysis)
    db.commit()
    return provenance_artifact


def run_variant_analysis(analysis_id: UUID) -> None:
    from backend.app.infrastructure.db.session import SessionLocal

    db = SessionLocal()
    temporary_artifact_paths: list[Path] = []
    try:
        analysis = db.get(Analysis, analysis_id)
        if not analysis:
            raise RuntimeError(f"Analysis not found: {analysis_id}")

        case = db.get(Case, analysis.case_id)
        if case is None:
            raise RuntimeError(f"Analysis case not found: {analysis.case_id}")
        try:
            artifacts = artifact_store_for_organization(
                db, organization_id=case.organization_id
            )
        except StorageProfileError as exc:
            raise RuntimeError(str(exc)) from exc
        audit = AuditService(db)
        ctx = WorkflowContext(db=db, artifacts=artifacts, audit=audit)
        ensure_steps(db, analysis_id)
        _apply_reanalysis_reuse(db, analysis)

        input_artifact_id = analysis.configuration["input_artifact_id"]
        input_artifact = db.get(Artifact, UUID(str(input_artifact_id)))
        if not input_artifact:
            raise RuntimeError("Input artifact not found")
        if input_artifact.case_id != analysis.case_id:
            raise RuntimeError("Analysis input artifact belongs to a different case")
        # The public analysis-creation path accepts only validated primary VCFs.
        # Keep the historical SOURCE_VCF worker path for pre-ingestion analyses;
        # those inputs are checked by the strict on-disk validator below.
        if input_artifact.artifact_type == "VCF":
            try:
                validate_analysis_input_artifact(input_artifact, analysis.reference_build)
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc
        elif input_artifact.artifact_type != "SOURCE_VCF":
            raise RuntimeError("Analysis input artifact is not a primary VCF")
        elif input_artifact.validation_status == "INVALID":
            raise RuntimeError("Analysis input VCF failed ingestion validation")
        input_path = _materialize_artifact_for_worker(
            db, input_artifact, temporary_artifact_paths
        )

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
        profile_bound_analysis = bool((analysis.configuration or {}).get("resource_profile_id"))
        partition_size = min(max(1, int(analysis.configuration.get("partition_size", 500) or 500)), 1000)

        if normalization_step.status != StepStatus.SUCCEEDED:
            mark_step(db, normalization_step, StepStatus.RUNNING)
            profile: dict[str, int] = {}
            routing: dict = {}
            routed_artifacts: list[Artifact] = []
            exclusion_manifest_artifacts: list[Artifact] = []
            validated_reference_package: dict | None = None
            routing_contig_lengths_resolved = False

            def persist_exclusion_manifest(*, contig_lengths_resolved: bool) -> None:
                manifest_path = routing.get("exclusion_manifest_path")
                if not manifest_path:
                    return
                source_path = Path(manifest_path)
                manifest_sha256 = sha256_file(source_path)
                artifact_id = uuid5(
                    analysis.id,
                    f"siraloom:normalization:exclusion-manifest:v1:{manifest_sha256}",
                )
                if any(item.id == artifact_id for item in exclusion_manifest_artifacts):
                    return
                artifact = _put_idempotent_stage_artifact(
                    artifacts,
                    artifact_id=artifact_id,
                    db=db,
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    source_path=source_path,
                    filename="excluded-source-records.jsonl",
                    artifact_type="VCF_EXCLUSION_MANIFEST",
                    media_type="application/x-ndjson",
                    genome_build=reference_build,
                    metadata={
                        "schema_version": "1",
                        "routing_version": routing["routing_version"],
                        "source_artifact_id": str(input_artifact.id),
                        "source_sha256": input_artifact.sha256,
                        "record_count": routing["exclusion_manifest_records"],
                        "source_record_index_base": 1,
                        "source_record_index_definition": "1-based ordinal among non-header VCF records",
                        "source_record_hash": "SHA-256 of decoded UTF-8 VCF data line without line terminator",
                        "reference_contig_lengths_resolved": contig_lengths_resolved,
                    },
                )
                if all(item.id != artifact.id for item in exclusion_manifest_artifacts):
                    exclusion_manifest_artifacts.append(artifact)

            def set_routed_reference_validation(
                status: str,
                reason_code: str,
                *,
                reference_package: dict | None = None,
                reference_profile: dict | None = None,
            ) -> None:
                for artifact in routed_artifacts:
                    metadata = dict(artifact.metadata_json or {})
                    artifact_status = status
                    artifact_reason_code = reason_code
                    if metadata.get("review_reason_code") == "VCF_TELOMERE_COORDINATE_UNSUPPORTED":
                        artifact_status = "NOT_VALIDATED_UNSUPPORTED_COORDINATE"
                        artifact_reason_code = "VCF_TELOMERE_COORDINATE_UNSUPPORTED"
                    preserve_prior_validation = _check_routed_artifact_validation_replay(
                        metadata,
                        status=artifact_status,
                        reference_package=reference_package,
                        active_reference_package=validated_reference_package,
                        reference_profile=reference_profile,
                    )
                    if preserve_prior_validation:
                        # The prior successful validation remains provenance for
                        # these immutable source bytes. The current attempt's blocked
                        # state is recorded on the workflow step.
                        continue
                    metadata.update({
                        "reference_validation_status": artifact_status,
                        "reference_validation_reason_code": artifact_reason_code,
                    })
                    if reference_package is not None:
                        metadata.update({
                            "reference_package_id": reference_package.get("resource_id"),
                            "reference_package_version": reference_package.get("version"),
                            "reference_fasta_sha256": reference_package.get("fasta_sha256"),
                        })
                    if reference_profile is not None:
                        metadata["source_reference_allele_profile"] = reference_profile
                    artifact.metadata_json = metadata
                    db.add(artifact)

            def finish_no_sequence_review(*, reference_validated: bool) -> None:
                if not reference_validated:
                    set_routed_reference_validation(
                        "NOT_RUN",
                        "NO_SEQUENCE_VARIANTS_ELIGIBLE_FOR_REFERENCE_NORMALIZATION",
                    )
                specialized_review_count = (
                    routing["gvcf_reference_blocks"]
                    + routing["gvcf_unresolved_variant_records"]
                    + routing["structural_variant_records"]
                    + routing["spanning_deletion_records"]
                    + routing["telomere_records"]
                    + routing["telomere_after_contig_records"]
                )
                routed_count = specialized_review_count + routing["reference_only_records"]
                if specialized_review_count:
                    reason = (
                        "The source contains preserved GVCF, structural, spanning-deletion, or telomere "
                        "records requiring a specialized review path; no sequence-resolved variant records "
                        "were eligible for ordinary normalization. Original records remain in the source "
                        "artifact and routed artifacts."
                    )
                    if routing["reference_only_records"]:
                        reason += (
                            f" {routing['reference_only_records']} reference-only ALT='.' record(s) "
                            "were retained in the source and excluded from variant analysis."
                        )
                    telomere_only = (
                        routing["telomere_records"] + routing["telomere_after_contig_records"]
                        == specialized_review_count
                    )
                    next_step = "VCF_TELOMERE_COORDINATE_REVIEW" if telomere_only else "GVCF_OR_STRUCTURAL_VARIANT_REVIEW"
                    review_reason_codes = sorted({
                        item.metadata_json["review_reason_code"]
                        for item in routed_artifacts
                    })
                    if routing["reference_only_records"]:
                        review_reason_codes.append("REFERENCE_ONLY_RECORDS_EXCLUDED")
                else:
                    reason = (
                        "The source contains no alternate alleles (all records have ALT='.'). "
                        "This is not a negative clinical result. Review the upstream callset and analysis "
                        "scope; the original VCF remains preserved."
                    )
                    next_step = "UPSTREAM_VARIANT_CALLSET_REVIEW"
                    review_reason_codes = ["NO_VARIANT_ALLELES_PROVIDED"]
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.REQUIRES_REVIEW,
                    error_code="NO_SEQUENCE_VARIANTS_TO_NORMALIZE",
                    error_message=reason,
                    metadata={
                        "next_step": next_step,
                        "routing": {key: value for key, value in routing.items() if not key.endswith("_path")},
                        "routed_artifact_ids": [str(item.id) for item in routed_artifacts],
                        "exclusion_manifest_artifact_ids": [str(item.id) for item in exclusion_manifest_artifacts],
                        "review_reason_codes": review_reason_codes,
                        "human_action_required": True,
                    },
                )
                analysis.status = AnalysisStatus.REQUIRES_REVIEW
                analysis.completed_at = None
                db.commit()
                audit.record(
                    event_type="VCF_RECORDS_ROUTED_TO_REVIEW",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="siraloom-vcf-router",
                    input_artifacts=[{"artifact_id": str(input_artifact.id), "sha256": input_artifact.sha256}],
                    output_artifacts=[{"artifact_id": str(item.id), "sha256": item.sha256} for item in (*routed_artifacts, *exclusion_manifest_artifacts)],
                    reason=reason,
                    payload={
                        "error_code": "NO_SEQUENCE_VARIANTS_TO_NORMALIZE",
                        "routed_record_count": routed_count,
                        "review_reason_codes": review_reason_codes,
                        "routing": {key: value for key, value in routing.items() if not key.endswith("_path")},
                    },
                )
                db.commit()

            try:
                profile = classify_records(input_path)
                routing_dir = Path(tempfile.mkdtemp(prefix=f"siraloom-vcf-routing-{analysis.id}-"))
                temporary_artifact_paths.append(routing_dir)
                routing = route_vcf_records(input_path, routing_dir, reference_contig_lengths={})
                routed_artifact_specs = (
                    (
                        "gvcf_blocks_path",
                        "GVCF_REFERENCE_BLOCKS",
                        "gvcf-reference-blocks.vcf",
                        "GVCF_REFERENCE_CONFIDENCE_ANALYSIS_UNSUPPORTED",
                    ),
                    (
                        "gvcf_unresolved_path",
                        "UNRESOLVED_GVCF_VARIANTS",
                        "gvcf-unresolved-variants.vcf",
                        "GVCF_VARIANT_ALLELE_UNRESOLVED",
                    ),
                    (
                        "structural_path",
                        "STRUCTURAL_VARIANT_RECORDS",
                        "structural-variants.vcf",
                        "STRUCTURAL_VARIANT_INTERPRETATION_UNSUPPORTED",
                    ),
                    (
                        "spanning_deletions_path",
                        "SPANNING_DELETION_RECORDS",
                        "spanning-deletion-records.vcf",
                        "SPANNING_DELETION_NOT_INTERPRETED",
                    ),
                    (
                        "telomere_path",
                        "TELOMERE_COORDINATE_RECORDS",
                        "telomere-records.vcf",
                        "VCF_TELOMERE_COORDINATE_UNSUPPORTED",
                    ),
                    (
                        "telomere_after_contig_path",
                        "TELOMERE_AFTER_CONTIG_RECORDS",
                        "telomere-after-contig-records.vcf",
                        "VCF_TELOMERE_COORDINATE_UNSUPPORTED",
                    ),
                )
                for path_key, artifact_type, filename, review_reason_code in routed_artifact_specs:
                    routed_path = routing.get(path_key)
                    if not routed_path:
                        continue
                    routed_artifacts.append(_put_idempotent_stage_artifact(
                        artifacts,
                        artifact_id=uuid5(analysis.id, f"siraloom:normalization:routed:{artifact_type.lower()}:v1"),
                        db=db,
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        source_path=Path(routed_path),
                        filename=filename,
                        artifact_type=artifact_type,
                        media_type="text/vcf",
                        genome_build=reference_build,
                        metadata={
                            "routing_version": routing["routing_version"],
                            "source_artifact_id": str(input_artifact.id),
                            "source_sha256": input_artifact.sha256,
                            "record_count": routing[{
                                "GVCF_REFERENCE_BLOCKS": "gvcf_reference_blocks",
                                "UNRESOLVED_GVCF_VARIANTS": "gvcf_unresolved_variant_records",
                                "STRUCTURAL_VARIANT_RECORDS": "structural_variant_records",
                                "SPANNING_DELETION_RECORDS": "spanning_deletion_records",
                                "TELOMERE_COORDINATE_RECORDS": "telomere_records",
                                "TELOMERE_AFTER_CONTIG_RECORDS": "telomere_after_contig_records",
                            }[artifact_type]],
                            "interpretation_status": "NOT_ANALYZED",
                            "review_status": "REQUIRES_SPECIALIZED_REVIEW",
                            "review_reason_code": review_reason_code,
                            "reference_validation_status": "PENDING",
                        },
                    ))
                normalization_step.input_artifacts = [str(input_artifact.id)]
                normalization_step.output_artifacts = [
                    *(str(item.id) for item in routed_artifacts),
                    *(str(item.id) for item in exclusion_manifest_artifacts),
                ]
                db.add(normalization_step)
                db.commit()

                if not routing["sequence_records"]:
                    persist_exclusion_manifest(contig_lengths_resolved=False)
                    normalization_step.output_artifacts = [
                        *(str(item.id) for item in routed_artifacts),
                        *(str(item.id) for item in exclusion_manifest_artifacts),
                    ]
                    db.add(normalization_step)
                    finish_no_sequence_review(reference_validated=False)
                    return

                case = db.get(Case, analysis.case_id)
                if case is None:
                    raise ReferencePackageError(
                        "Analysis case was not found while resolving the organization-approved reference package.",
                        code="CASE_NOT_FOUND",
                    )
                profile_runtime_reference = None
                if profile_bound_analysis:
                    try:
                        profile_runtime_reference = resolve_profile_runtime_resource(
                            db,
                            analysis_id=analysis.id,
                            capability="REFERENCE_PACKAGE",
                        )
                    except ProfileRuntimeResourceError as exc:
                        raise ReferencePackageError(str(exc), code=exc.code) from exc
                    requested_reference = profile_runtime_reference.resource
                    reference_resource_id = str(requested_reference.id)
                    resolution = SimpleNamespace(
                        resource=requested_reference,
                        used_fallback=False,
                        requested_resource_id=requested_reference.id,
                        fallback_resource_id=None,
                        decision=decide_step_outcome(
                            "normalize",
                            OutcomeKind.SUCCESS,
                            code="PROFILE_RESOURCE_SELECTED",
                            message="Reference package is bound to the exact resource selected during analysis preflight.",
                        ),
                    )
                else:
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
                    set_routed_reference_validation(
                        "NOT_RUN",
                        resolution.decision.code or "REFERENCE_PACKAGE_UNAVAILABLE",
                    )
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
                validated_reference_package = reference_package
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
                    normalized_contract_location = str(
                        local_path_from_uri(contract_location) or Path(contract_location).resolve()
                    )
                    normalized_reference_location = str(reference_fasta_path.resolve())
                    if normalized_contract_location != normalized_reference_location:
                        raise ResourceExecutionError(
                            "Qualified reference execution location does not match the "
                            f"validated FASTA location: {contract_location!r} != "
                            f"{str(reference_fasta_path)!r}."
                        )

                reference_contigs = {item["name"] for item in reference_package["contigs"]}
                reference_contig_lengths = {
                    item["name"]: int(item["length"])
                    for item in reference_package["contigs"]
                }

                # The header may omit contig lengths. Re-route once the
                # organization-approved reference is resolved so POS=N+1 is
                # recognized from the selected FASTA and cannot reach BCFtools.
                routing = route_vcf_records(
                    input_path,
                    routing_dir,
                    reference_contig_lengths=reference_contig_lengths,
                )
                routing_contig_lengths_resolved = True
                persist_exclusion_manifest(contig_lengths_resolved=True)
                telomere_after_path = routing.get("telomere_after_contig_path")
                if telomere_after_path:
                    telomere_after_id = uuid5(
                        analysis.id,
                        "siraloom:normalization:routed:telomere_after_contig_records:v1",
                    )
                    if not any(item.id == telomere_after_id for item in routed_artifacts):
                        routed_artifacts.append(_put_idempotent_stage_artifact(
                            artifacts,
                            artifact_id=telomere_after_id,
                            db=db,
                            case_id=analysis.case_id,
                            analysis_id=analysis.id,
                            source_path=Path(telomere_after_path),
                            filename="telomere-after-contig-records.vcf",
                            artifact_type="TELOMERE_AFTER_CONTIG_RECORDS",
                            media_type="text/vcf",
                            genome_build=reference_build,
                            metadata={
                                "routing_version": routing["routing_version"],
                                "source_artifact_id": str(input_artifact.id),
                                "source_sha256": input_artifact.sha256,
                                "record_count": routing["telomere_after_contig_records"],
                                "interpretation_status": "NOT_ANALYZED",
                                "review_status": "REQUIRES_SPECIALIZED_REVIEW",
                                "review_reason_code": "VCF_TELOMERE_COORDINATE_UNSUPPORTED",
                                "reference_validation_status": "PENDING",
                            },
                        ))
                    normalization_step.output_artifacts = [
                        *(str(item.id) for item in routed_artifacts),
                        *(str(item.id) for item in exclusion_manifest_artifacts),
                    ]
                    db.add(normalization_step)
                    db.commit()

                # Re-validate against the selected package so build/contig compatibility
                # is established before bcftools is allowed to transform the VCF.
                package_profile = validate_vcf_strict(
                    str(input_path),
                    reference_contigs=reference_contigs,
                )
                reference_allele_profile = validate_vcf_reference_alleles(
                    str(input_path),
                    reference_fasta_path,
                )
                set_routed_reference_validation(
                    "PASS",
                    "SELECTED_REFERENCE_CHECKS_PASSED",
                    reference_package=reference_package,
                    reference_profile=reference_allele_profile,
                )
                if not routing["sequence_records"]:
                    finish_no_sequence_review(reference_validated=True)
                    return
            except UnsupportedVariantError as exc:
                persist_exclusion_manifest(contig_lengths_resolved=routing_contig_lengths_resolved)
                set_routed_reference_validation("FAILED", exc.code)
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.BLOCKED,
                    error_code=exc.code,
                    error_message=str(exc),
                    metadata={
                        "next_step": "SUPPORTED_INPUT_REQUIRED",
                        "input_profile": profile,
                    },
                )
                analysis.status = AnalysisStatus.BLOCKED
                analysis.completed_at = None
                db.commit()
                audit.record(
                    event_type="NORMALIZATION_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="siraloom-normalizer",
                    input_artifacts=[
                        {"artifact_id": str(input_artifact.id), "sha256": input_artifact.sha256}
                    ],
                    reason=str(exc),
                    payload={
                        "error_code": exc.code,
                        "next_step": "SUPPORTED_INPUT_REQUIRED",
                        "input_profile": profile,
                    },
                )
                db.commit()
                return
            except ReferencePackageError as exc:
                persist_exclusion_manifest(contig_lengths_resolved=routing_contig_lengths_resolved)
                set_routed_reference_validation("NOT_RUN", exc.code)
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
                persist_exclusion_manifest(contig_lengths_resolved=routing_contig_lengths_resolved)
                set_routed_reference_validation("FAILED", exc.code)
                reference_mismatch = exc.code.startswith((
                    "VCF_REFERENCE_",
                    "VCF_BREAKEND_REFERENCE_",
                ))
                next_step = (
                    "REFERENCE_OR_INPUT_REVIEW"
                    if reference_mismatch
                    else "VALID_VCF_REQUIRED"
                )
                mark_step(
                    db,
                    normalization_step,
                    StepStatus.BLOCKED,
                    error_code=exc.code,
                    error_message=str(exc),
                    metadata={"next_step": next_step},
                )
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(
                    event_type="NORMALIZATION_BLOCKED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="vcf-validator",
                    input_artifacts=[{"artifact_id": str(input_artifact.id), "sha256": input_artifact.sha256}],
                    output_artifacts=[{"artifact_id": str(item.id), "sha256": item.sha256} for item in (*routed_artifacts, *exclusion_manifest_artifacts)],
                    reason=str(exc),
                    payload={
                        "error_code": exc.code,
                        "reference_build": reference_build,
                        "next_step": next_step,
                        "routing": {key: value for key, value in routing.items() if not key.endswith("_path")},
                    },
                )
                db.commit()
                return
            except ResourceExecutionError as exc:
                persist_exclusion_manifest(contig_lengths_resolved=routing_contig_lengths_resolved)
                set_routed_reference_validation(
                    "NOT_RUN",
                    "REFERENCE_EXECUTION_CONTRACT_INVALID",
                )
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

                request_material = {
                    "input_artifact_sha256": input_artifact.sha256,
                    "reference_package_checksum": reference_package["package_checksum"],
                    "reference_fasta_sha256": reference_package["fasta_sha256"],
                    "bcftools_version": settings.bcftools_version,
                    "execution_contract_hash": reference_execution.contract_hash,
                    "normalization_version": "4.0",
                    "source_record_mapping_tag": "SIRALOOM_ORIG",
                    "source_record_mapping_policy": "BCFTOOLS_OLD_REC_TAG_SOURCE_ALT_INDEX",
                    "record_routing": {
                        key: value for key, value in routing.items() if not key.endswith("_path")
                    },
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
                        routing["sequence_path"],
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

                normalized_artifact = _put_idempotent_stage_artifact(
                    artifacts,
                    artifact_id=uuid5(analysis.id, "siraloom:normalization:normalized-vcf:v4"),
                    db=db, case_id=analysis.case_id, analysis_id=analysis.id, source_path=temp_path,
                    filename="normalized.vcf.gz",
                    artifact_type="NORMALIZED_VCF", media_type="application/gzip",
                    genome_build=reference_build,
                    metadata={
                        "normalization_version": "4.0",
                        "source_record_mapping_tag": normalization_stats["source_record_mapping_tag"],
                        "source_record_mapping_policy": normalization_stats["source_record_mapping_policy"],
                        "source_artifact_id": str(input_artifact.id),
                        "source_sha256": input_artifact.sha256,
                        "record_count": routing["sequence_records"],
                        "source_record_count": profile["records"],
                        "routing": {key: value for key, value in routing.items() if not key.endswith("_path")},
                        "routed_artifact_ids": [str(item.id) for item in routed_artifacts],
                        "streaming": True,
                        "reference_source": "PINNED_REFERENCE_PACKAGE",
                        "reference_package_id": reference_package["resource_id"],
                        "reference_package_version": reference_package["version"],
                        "reference_package_checksum": reference_package["package_checksum"],
                        "reference_fasta_sha256": reference_package["fasta_sha256"],
                        "reference_fai_sha256": reference_package["fai_sha256"],
                        "reference_contigs_sha256": reference_package["contigs_sha256"],
                        "source_reference_allele_profile": reference_allele_profile,
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
                index_artifact = _put_idempotent_stage_artifact(
                    artifacts,
                    artifact_id=uuid5(analysis.id, "siraloom:normalization:normalized-vcf-index:v4"),
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
                normalization_step.output_artifacts = [
                    str(normalized_artifact.id), str(index_artifact.id),
                    *(str(item.id) for item in routed_artifacts),
                    *(str(item.id) for item in exclusion_manifest_artifacts),
                ]
                fallback_metadata = {
                    "requested_resource_id": str(resolution.requested_resource_id),
                    "selected_resource_id": str(selected_reference_resource.id),
                    "fallback_used": resolution.used_fallback,
                    "decision_action": resolution.decision.action.value,
                }
                mark_step(db, normalization_step, StepStatus.SUCCEEDED, metadata={"normalization": "REFERENCE_AWARE_SEQUENCE_VARIANTS", "resource_resolution": fallback_metadata, "record_count": routing["sequence_records"], "source_record_count": profile["records"], "routing": {key: value for key, value in routing.items() if not key.endswith("_path")}, "routed_artifact_ids": [str(item.id) for item in routed_artifacts], "exclusion_manifest_artifact_ids": [str(item.id) for item in exclusion_manifest_artifacts], "streaming": True, "partition_size": partition_size, "reference_source": "PINNED_REFERENCE_PACKAGE", "reference_package_id": reference_package["resource_id"], "reference_package_version": reference_package["version"], "reference_package_checksum": reference_package["package_checksum"], "reference_fasta_sha256": reference_package["fasta_sha256"], "reference_fai_sha256": reference_package["fai_sha256"], "reference_contigs_sha256": reference_package["contigs_sha256"], "reference_contig_policy": reference_package["contig_policy"], "reference_package_profile": package_profile, "source_reference_allele_profile": reference_allele_profile, "normalization_tool": normalization_stats["tool"], "normalization_tool_version": normalization_stats["tool_version"], "normalization_expected_tool_version": normalization_stats["expected_tool_version"], "normalization_command": normalization_stats["command"], "execution_contract": reference_execution.snapshot, "execution_contract_hash": reference_execution.contract_hash, "input_profile": profile})
                audit.record(event_type="NORMALIZATION_COMPLETED", case_id=analysis.case_id, analysis_id=analysis.id, actor_type="SYSTEM", actor_id="siraloom-normalizer", input_artifacts=[{"artifact_id": str(input_artifact.id), "sha256": input_artifact.sha256}], output_artifacts=[{"artifact_id": str(normalized_artifact.id), "sha256": normalized_artifact.sha256}, *[{"artifact_id": str(item.id), "sha256": item.sha256} for item in (*routed_artifacts, *exclusion_manifest_artifacts)]], workflow={"step": "normalize", "version": "3.0"}, payload={"record_count": routing["sequence_records"], "source_record_count": profile["records"], "routing": {key: value for key, value in routing.items() if not key.endswith("_path")}, "routed_artifact_ids": [str(item.id) for item in routed_artifacts], "exclusion_manifest_artifact_ids": [str(item.id) for item in exclusion_manifest_artifacts], "streaming": True, "reference_source": "PINNED_REFERENCE_PACKAGE", "reference_package_id": reference_package["resource_id"], "reference_package_version": reference_package["version"], "reference_package_checksum": reference_package["package_checksum"], "reference_fasta_sha256": reference_package["fasta_sha256"], "reference_fai_sha256": reference_package["fai_sha256"], "reference_contigs_sha256": reference_package["contigs_sha256"], "source_reference_allele_profile": reference_allele_profile, "normalization_tool": normalization_stats["tool"], "normalization_tool_version": normalization_stats["tool_version"], "normalization_command": normalization_stats["command"], "execution_contract": reference_execution.snapshot, "execution_contract_hash": reference_execution.contract_hash, "input_profile": profile})
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
            except (SQLAlchemyError, OSError) as exc:
                # Database and artifact-storage failures are operationally retryable.
                # Preserve the normalization checkpoint and let the bounded Celery
                # retry policy re-enter this stage instead of terminally failing it.
                _schedule_transient_step_retry(
                    db,
                    analysis_id=analysis.id,
                    step_id="normalize",
                    error_code="NORMALIZATION_PERSISTENCE_RETRYING",
                    error_message=str(exc),
                    event_type="NORMALIZATION_RETRY_SCHEDULED",
                    actor_id="siraloom-normalizer",
                    next_step="normalize",
                )
                raise TransientWorkflowError(
                    "Normalization persistence or artifact storage failed; retrying from the durable stage checkpoint.",
                    countdown=10,
                    max_retries=3,
                    error_code="NORMALIZATION_RETRY_EXHAUSTED",
                ) from exc
            except Exception as exc:
                # Unexpected non-operational failures remain explicit terminal errors.
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

        normalized_path = _materialize_artifact_for_worker(
            db, normalized_artifact, temporary_artifact_paths
        )
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
        normalization_exclusions: dict[str, int] = {}
        for start, batch in _iter_variant_batches(
            normalized_path,
            reference_build,
            partition_size,
            exclusion_stats=normalization_exclusions,
        ):
            end = start + len(batch)
            partition_key = _batch_key(start, end)
            part = db.scalar(select(AnalysisPartition).where(AnalysisPartition.analysis_id == analysis.id, AnalysisPartition.step_id == "normalize", AnalysisPartition.partition_key == partition_key))
            if part is None:
                part = AnalysisPartition(id=__import__("uuid").uuid4(), analysis_id=analysis.id, step_id="normalize", partition_key=partition_key, ordinal=ordinal, record_start=start, record_end=end, variant_count=len(batch), status="READY", input_artifact_id=normalized_artifact.id, metadata_json={"genome_build": reference_build})
                db.add(part)
            else:
                # A resumed workflow reparses the immutable normalized artifact
                # to rebuild its in-memory batch cursor, but completed durable
                # partitions must remain terminal and must not become schedulable
                # again after a human review gate.
                if part.status != "SUCCEEDED":
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
            part.metadata_json = _normalized_partition_metadata(rows, batch)
            total_variants += len(batch)
            ordinal += 1
            db.commit()

        normalization_step.metadata_json = {
            **(normalization_step.metadata_json or {}),
            "partition_count": ordinal,
            "record_count": total_variants,
            "partition_size": partition_size,
            "streaming": True,
            "normalized_allele_record_count": normalization_exclusions.get(
                "normalized_allele_records", 0
            ),
            "excluded_reference_only_genotype_allele_count": normalization_exclusions.get(
                "reference_only_genotype_alleles", 0
            ),
        }
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
                profile_runtime_annotation = None
                if profile_bound_analysis:
                    try:
                        profile_runtime_annotation = resolve_profile_runtime_resource(
                            db,
                            analysis_id=analysis.id,
                            capability="ANNOTATION_ENGINE",
                        )
                    except ProfileRuntimeResourceError as exc:
                        raise ResourceConsumptionError(exc.code, str(exc)) from exc
                    candidates = [SimpleNamespace(
                        resource=profile_runtime_annotation.resource,
                        execution=profile_runtime_annotation.execution,
                    )]
                    deployment = dict(((analysis.configuration or {}).get("resource_plan") or {}).get("deployment") or {})
                    plan = SimpleNamespace(
                        profile_type=deployment.get("profile_type", "LABORATORY"),
                        profile_version=deployment.get("profile_version", "1"),
                        unavailable_optional=[],
                    )
                else:
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
                if profile_bound_analysis and requested_annotation_resource_id and str(
                    requested_annotation_resource_id
                ) != str(candidates[0].resource.id):
                    raise ResourceConsumptionError(
                        "RESOURCE_PLAN_CONFLICT",
                        "annotation_resource_id conflicts with the immutable preflight-selected annotation resource.",
                    )
                if requested_annotation_resource_id:
                    for candidate in candidates:
                        if str(candidate.resource.id) == str(requested_annotation_resource_id):
                            selected = candidate
                            break
                if selected is None:
                    selected = candidates[0]

                annotation_resource = selected.resource
                annotation_execution = (
                    selected.execution
                    if profile_bound_analysis
                    else resolve_resource_execution(db, resource=annotation_resource)
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

                if profile_bound_analysis:
                    resolution = SimpleNamespace(
                        resource=annotation_resource,
                        used_fallback=False,
                        requested_resource_id=annotation_resource.id,
                        fallback_resource_id=None,
                        decision=decide_step_outcome(
                            "annotate",
                            OutcomeKind.SUCCESS,
                            code="PROFILE_RESOURCE_SELECTED",
                            message="Annotation is bound to the exact resource selected during analysis preflight.",
                        ),
                    )
                else:
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
                if not profile_bound_analysis:
                    annotation_execution = resolve_resource_execution(
                        db,
                        resource=annotation_resource,
                    )
                    implementation = registry.require(
                        provider_id=annotation_execution.contract.provider_id,
                        provider_version=annotation_execution.contract.provider_version,
                    )
                    provider = implementation.factory(annotation_execution.contract)
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
                        payloads = _load_annotation_response_checkpoint(
                            db,
                            step=annotation_step,
                            start=start,
                            end=end,
                            analysis=analysis,
                            resource=annotation_resource,
                            provider_id=provider.provider_id,
                            provider_version=provider.provider_version,
                            temporary_paths=temporary_artifact_paths,
                        )
                        if payloads is None:
                            payloads = provider.annotate(batch, {"genome": genome})
                            scheduler.heartbeat(partition.id, worker_id, lease_token)
                            _ensure_annotation_request_fingerprint(
                                payloads,
                                analysis=analysis,
                                start=start,
                                end=end,
                                resource=annotation_resource,
                                provider_id=provider.provider_id,
                                provider_version=provider.provider_version,
                            )
                            sample = next((item.get("_siraloom_annotation_provenance", {}) for item in payloads if isinstance(item, dict)), {})
                            _persist_annotation_response_checkpoint(
                                db,
                                artifacts,
                                analysis=analysis,
                                step=annotation_step,
                                start=start,
                                end=end,
                                payloads=payloads,
                                resource=annotation_resource,
                                provider_id=provider.provider_id,
                                provider_version=provider.provider_version,
                            )
                            # The response artifact and replay checkpoint are the
                            # durable evidence that the provider execution completed.
                            # Do not mark the execution successful before both exist.
                            complete_resource_execution(db, execution_record, status="SUCCEEDED", request_fingerprint=sample.get("request_fingerprint"), response_sha256=sample.get("response_sha256"))
                            db.commit()
                        else:
                            sample = next((item.get("_siraloom_annotation_provenance", {}) for item in payloads if isinstance(item, dict)), {})
                            complete_resource_execution(db, execution_record, status="SUCCEEDED", request_fingerprint=sample.get("request_fingerprint"), response_sha256=sample.get("response_sha256"))
                            db.commit()
                            scheduler.heartbeat(partition.id, worker_id, lease_token)
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

                    new_count, returned_rows = _persist_annotation_batch_rows(
                        db,
                        analysis=analysis,
                        provider=provider,
                        annotation_resource=annotation_resource,
                        variant_ids=variant_ids,
                        existing_rows=existing_rows,
                        payloads=payloads,
                        batch_key=key,
                    )
                    _save_batch_checkpoint(
                        db, annotation_step, start, end, status="SUCCEEDED", attempt=attempt,
                        metadata={"provider": provider.provider_id, "new_annotation_rows": new_count, "returned_rows": returned_rows},
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
            except TransientWorkflowError:
                raise
            except PartitionCapacityError as exc:
                # Capacity contention is transient: do not terminally fail a
                # scientifically valid analysis just because another partition
                # currently owns the deployment's CPU/RAM envelope. Keep the
                # checkpoint durable and let Celery retry this analysis later.
                _save_batch_checkpoint(
                    db,
                    annotation_step,
                    start,
                    end,
                    status="RETRYING",
                    attempt=int(_batch_checkpoint(annotation_step, start, end).get("attempt", 0)),
                    metadata={"wait_reason": "CAPACITY_UNAVAILABLE", "error": str(exc)},
                )
                mark_step(
                    db,
                    annotation_step,
                    StepStatus.RETRYING,
                    error_code="ANNOTATION_WAITING_FOR_CAPACITY",
                    error_message=str(exc),
                    metadata={"next_step": "annotate", "retry_policy": "bounded_capacity_wait"},
                )
                db.commit()
                audit.record(
                    event_type="ANNOTATION_WAITING_FOR_CAPACITY",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="partition-scheduler",
                    reason=str(exc),
                    payload={
                        "error_code": "ANNOTATION_WAITING_FOR_CAPACITY",
                        "next_step": "annotate",
                        "retry_delay_seconds": 60,
                        "max_retries": 20,
                    },
                )
                db.commit()
                raise TransientWorkflowError(
                    str(exc),
                    countdown=60,
                    max_retries=20,
                    error_code="ANNOTATION_CAPACITY_RETRY_EXHAUSTED",
                ) from exc
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

                profile_runtime_population = None
                if profile_bound_analysis:
                    try:
                        profile_runtime_population = resolve_profile_runtime_resource(
                            db,
                            analysis_id=analysis.id,
                            capability="POPULATION",
                        )
                    except ProfileRuntimeResourceError as exc:
                        raise ResourceConsumptionError(exc.code, str(exc)) from exc
                    resource_plan_snapshot = dict(
                        (analysis.configuration or {}).get("resource_plan") or {}
                    )
                    deployment = dict(resource_plan_snapshot.get("deployment") or {})
                    plan = SimpleNamespace(
                        profile_type=deployment.get("profile_type", "LABORATORY"),
                        profile_version=deployment.get(
                            "profile_version",
                            resource_plan_snapshot.get("profile_version", "1"),
                        ),
                        unavailable_optional=resource_plan_snapshot.get(
                            "unavailable_optional", []
                        ),
                    )
                    population_candidates = [SimpleNamespace(
                        resource=profile_runtime_population.resource,
                        execution=profile_runtime_population.execution,
                    )]
                else:
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
                    execution = (
                        candidate.execution
                        if profile_bound_analysis
                        else resolve_resource_execution(db, resource=resource)
                    )
                    implementation = registry.resolve(
                        provider_id=execution.contract.provider_id,
                        provider_version=execution.contract.provider_version,
                    )
                    if implementation is None:
                        if profile_bound_analysis:
                            raise ResourceConsumptionError(
                                "POPULATION_ADAPTER_UNSUPPORTED",
                                f"Preflight-selected population provider {execution.contract.provider_id!r} has no runtime adapter.",
                            )
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
                        batch_key = (
                            f"{provider.provider_id}:{variant.chromosome}:"
                            f"{variant.position}:{variant.reference}:{variant.alternate}"
                        )
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
                        if _succeeded_population_execution(
                            db,
                            analysis_id=analysis.id,
                            resource_id=resource.id,
                            batch_key=batch_key,
                        ):
                            continue
                        execution_record = start_resource_execution(
                            db,
                            analysis_id=analysis.id,
                            step_id="population",
                            attempt=population_step.attempt,
                            resolved=execution,
                            requested_resource_id=resource.id,
                            fallback_resource_id=None,
                            batch_key=batch_key,
                            metadata={
                                "provider": provider.provider_id,
                                "resource_id": str(resource.id),
                            },
                        )
                        db.commit()
                        try:
                            obs_list = query_variant(variant)
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

                secondary_count = 0
                secondary_limitations: list[dict] = []
                if (analysis.configuration or {}).get("resource_profile_id"):
                    try:
                        secondary_runtime_resources = resolve_profile_runtime_resources(
                            db,
                            analysis_id=analysis.id,
                            capability="POPULATION_SECONDARY",
                        )
                    except ProfileRuntimeResourceError as exc:
                        raise ResourceConsumptionError(exc.code, str(exc)) from exc

                    for secondary_runtime in secondary_runtime_resources:
                        secondary_resource = secondary_runtime.resource
                        secondary_execution = secondary_runtime.execution
                        provider_name = secondary_resource.provider.strip().upper()
                        try:
                            secondary_provider = LocalTabixSecondaryPopulationProvider.from_execution_contract(
                                secondary_execution.contract
                            )
                        except SecondaryPopulationProviderError as exc:
                            secondary_limitations.append({
                                "resource_id": str(secondary_resource.id),
                                "provider": secondary_resource.provider,
                                "code": "SECONDARY_POPULATION_ADAPTER_UNSUPPORTED",
                                "message": str(exc),
                            })
                            record_workflow_decision(
                                db,
                                analysis_id=analysis.id,
                                step_id="population",
                                attempt=population_step.attempt,
                                outcome=OutcomeKind.NO_DATA,
                                decision=decide_step_outcome(
                                    "population",
                                    OutcomeKind.NO_DATA,
                                    code="SECONDARY_POPULATION_ADAPTER_UNSUPPORTED",
                                    message=(
                                        f"Optional secondary population resource {secondary_resource.provider!r} "
                                        "could not be executed; primary gnomAD population context remains authoritative."
                                    ),
                                ),
                                resource_id=secondary_resource.id,
                                metadata={
                                    "population_role": "SECONDARY",
                                    "provider": secondary_resource.provider,
                                    "qualification_id": str(secondary_execution.qualification_id),
                                    "contract_hash": secondary_execution.contract_hash,
                                    "error": str(exc),
                                },
                            )
                            db.commit()
                            continue

                        record_workflow_decision(
                            db,
                            analysis_id=analysis.id,
                            step_id="population",
                            attempt=population_step.attempt,
                            outcome=OutcomeKind.SUCCESS,
                            decision=decide_step_outcome(
                                "population",
                                OutcomeKind.SUCCESS,
                                code="PROFILE_SECONDARY_RESOURCE_SELECTED",
                                message=(
                                    f"Optional secondary population resource {secondary_resource.provider!r} "
                                    "is bound to the exact resource selected during analysis preflight."
                                ),
                            ),
                            resource_id=secondary_resource.id,
                            metadata={
                                "population_role": "SECONDARY",
                                "provider": secondary_resource.provider,
                                "provider_version": secondary_resource.version,
                                "qualification_id": str(secondary_execution.qualification_id),
                                "contract_hash": secondary_execution.contract_hash,
                            },
                        )
                        db.commit()

                        for variant in iter_normalized_vcf(normalized_path, reference_build):
                            batch_key = (
                                f"secondary:{provider_name}:{variant.chromosome}:{variant.position}:"
                                f"{variant.reference}:{variant.alternate}"
                            )
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
                                raise RuntimeError("Canonical variant row missing during secondary population processing")
                            if _succeeded_population_execution(
                                db,
                                analysis_id=analysis.id,
                                resource_id=secondary_resource.id,
                                batch_key=batch_key,
                            ):
                                continue
                            execution_record = start_resource_execution(
                                db,
                                analysis_id=analysis.id,
                                step_id="population",
                                attempt=population_step.attempt,
                                resolved=secondary_execution,
                                requested_resource_id=str(secondary_resource.id),
                                fallback_resource_id=None,
                                batch_key=batch_key,
                                metadata={
                                    "provider": secondary_provider.provider_id,
                                    "population_role": "SECONDARY",
                                    "dataset": secondary_execution.contract.dataset,
                                },
                            )
                            db.commit()
                            try:
                                observations, query_provenance = (
                                    secondary_provider.query_variant_with_provenance(variant)
                                )
                            except SecondaryPopulationProviderError as exc:
                                complete_resource_execution(
                                    db,
                                    execution_record,
                                    status="FAILED",
                                    error_code="SECONDARY_POPULATION_PROVIDER_ERROR",
                                    error_message=str(exc),
                                )
                                db.commit()
                                secondary_limitations.append({
                                    "resource_id": str(secondary_resource.id),
                                    "provider": secondary_resource.provider,
                                    "code": "SECONDARY_POPULATION_PROVIDER_ERROR",
                                    "message": str(exc),
                                })
                                continue
                            for obs in observations:
                                existing = db.scalar(
                                    select(PopulationObservation).where(
                                        PopulationObservation.analysis_id == analysis.id,
                                        PopulationObservation.variant_id == row.id,
                                        PopulationObservation.resource_id == secondary_resource.id,
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
                                        resource_id=secondary_resource.id,
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
                                secondary_count += 1
                            complete_resource_execution(
                                db,
                                execution_record,
                                status="SUCCEEDED",
                                request_fingerprint=query_provenance["request_fingerprint"],
                                response_sha256=query_provenance["response_sha256"],
                            )
                            db.commit()

                annotated_variant_ids = set(db.scalars(
                    select(Annotation.variant_id)
                    .where(Annotation.analysis_id == analysis.id)
                    .distinct()
                ).all())
                population_variant_ids = set(db.scalars(
                    select(PopulationObservation.variant_id)
                    .where(
                        PopulationObservation.analysis_id == analysis.id,
                        PopulationObservation.availability == "AVAILABLE",
                        PopulationObservation.allele_frequency.is_not(None),
                        PopulationObservation.allele_number.is_not(None),
                    )
                    .distinct()
                ).all())
                variants_without_population = sorted(
                    str(variant_id)
                    for variant_id in annotated_variant_ids - population_variant_ids
                )
                population_metadata = {
                    "executed_resources": executed_resources,
                    "profile_type": plan.profile_type,
                    "profile_version": plan.profile_version,
                    "gene_be_global_observations": created,
                    "direct_population_observations": direct_count,
                    "optional_resources_not_selected": len(plan.unavailable_optional),
                    "secondary_population_observations": secondary_count,
                    "secondary_population_limitations": secondary_limitations,
                    "annotated_variants": len(annotated_variant_ids),
                    "variants_without_population_observations": variants_without_population,
                }
                if variants_without_population:
                    _apply_scientific_limitation(
                        db,
                        population_step,
                        outcome=OutcomeKind.INSUFFICIENT_EVIDENCE,
                        code="POPULATION_OBSERVATIONS_MISSING",
                        message=(
                            "Population observations are unavailable for one or more annotated variants. "
                            "Missing frequency data must not be interpreted as zero; classification requires human review."
                        ),
                        metadata={
                            **population_metadata,
                            "next_step": "build_evidence",
                            "population_data_available": bool(population_variant_ids),
                        },
                    )
                else:
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
                # Population absence/qualification gaps are scientific limitations:
                # do not use an unapproved resource, but continue without its data so
                # evidence and ACMG can route the affected variants to human review.
                _apply_scientific_limitation(
                    db,
                    population_step,
                    outcome=OutcomeKind.INSUFFICIENT_EVIDENCE,
                    code=exc.code,
                    message=str(exc),
                    metadata={
                        "next_step": "build_evidence",
                        "resource_limitation": True,
                        "automatic_fallback": False,
                        "population_data_available": False,
                    },
                )
                audit.record(
                    event_type="POPULATION_RESOURCE_LIMITATION",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="resource-registry",
                    reason=str(exc),
                    payload={
                        "error_code": exc.code,
                        "next_step": "build_evidence",
                        "automatic_fallback": False,
                    },
                )
                db.commit()
            except GnomADProviderError as exc:
                if exc.retryable:
                    _schedule_transient_step_retry(
                        db,
                        analysis_id=analysis.id,
                        step_id="population",
                        error_code="POPULATION_PROVIDER_TRANSIENT",
                        error_message=str(exc),
                        event_type="POPULATION_RETRY_SCHEDULED",
                        actor_id="gnomad",
                        next_step="population",
                    )
                    raise TransientWorkflowError(
                        str(exc),
                        countdown=10,
                        max_retries=3,
                        error_code="POPULATION_PROVIDER_RETRY_EXHAUSTED",
                    ) from exc
                # Permanent provider responses (for example a rejected request or
                # unusable response) must not be treated as zero allele frequency.
                # Continue with an explicit limitation; ACMG will require review if
                # a criterion depends on the unavailable population evidence.
                _apply_scientific_limitation(
                    db,
                    population_step,
                    outcome=OutcomeKind.INSUFFICIENT_EVIDENCE,
                    code="GNOMAD_PROVIDER_UNAVAILABLE",
                    message=str(exc),
                    metadata={
                        "next_step": "build_evidence",
                        "population_data_available": False,
                        "provider": "gnomAD",
                        "retryable": False,
                    },
                )
                audit.record(
                    event_type="POPULATION_PROVIDER_LIMITATION",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id="gnomad",
                    reason=str(exc),
                    payload={
                        "error_code": "GNOMAD_PROVIDER_UNAVAILABLE",
                        "next_step": "build_evidence",
                        "population_data_available": False,
                    },
                )
                db.commit()
            except OSError as exc:
                _schedule_transient_step_retry(
                    db,
                    analysis_id=analysis.id,
                    step_id="population",
                    error_code="POPULATION_STORAGE_RETRYING",
                    error_message=str(exc),
                    event_type="POPULATION_STORAGE_RETRY_SCHEDULED",
                    actor_id="population-engine",
                    next_step="population",
                )
                raise TransientWorkflowError(
                    "Population stage filesystem/storage operation failed; retrying from the durable population checkpoint.",
                    countdown=10,
                    max_retries=3,
                    error_code="POPULATION_STORAGE_RETRY_EXHAUSTED",
                ) from exc
            except SQLAlchemyError as exc:
                _schedule_transient_step_retry(
                    db,
                    analysis_id=analysis.id,
                    step_id="population",
                    error_code="POPULATION_PERSISTENCE_RETRYING",
                    error_message=str(exc),
                    event_type="POPULATION_PERSISTENCE_RETRY_SCHEDULED",
                    actor_id="gnomad",
                    next_step="population",
                )
                raise TransientWorkflowError(
                    "Population observation persistence failed; retrying from the durable population checkpoint.",
                    countdown=10,
                    max_retries=3,
                    error_code="POPULATION_PERSISTENCE_RETRY_EXHAUSTED",
                ) from exc
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
                from backend.app.domain.evidence import evidence_fingerprint
                from backend.app.evidence.engine import EvidenceContext, EvidenceEngine
                engine = EvidenceEngine()
                total_annotation_rows = db.scalar(select(func.count(Annotation.id)).where(Annotation.analysis_id == analysis.id)) or 0

                # ClinVar is consumed here as direct clinical-database evidence,
                # not as an annotation-stage side effect. The analysis must pin a
                # registered resource version; runtime execution then resolves the
                # exact qualified contract and reads only the staged authoritative
                # release through the governed adapter.
                clinvar_resource = None
                clinvar_provider = None
                clinvar_execution = None
                clinvar_execution_metadata = None
                clinvar_limitations: list[dict[str, object]] = []
                provider_limitations: list[dict[str, object]] = []
                configured_clinvar_id = (analysis.configuration or {}).get("clinvar_resource_id")
                clinvar_profile_managed = profile_bound_analysis

                if clinvar_profile_managed:
                    selected_clinvar = [
                        item for item in ((analysis.configuration or {}).get("resource_plan") or {}).get("selected", [])
                        if item.get("capability") == "CLINICAL_DATABASE"
                    ]
                    if selected_clinvar:
                        try:
                            resolved_clinvar = resolve_profile_runtime_resource(
                                db,
                                analysis_id=analysis.id,
                                capability="CLINICAL_DATABASE",
                            )
                            clinvar_resource = resolved_clinvar.resource
                            clinvar_execution = resolved_clinvar.execution
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
                        except (ProfileRuntimeResourceError, ResourceExecutionError, ClinVarProviderError) as exc:
                            clinvar_limitations.append({
                                "code": getattr(exc, "code", None) or "CLINVAR_RESOURCE_UNAVAILABLE",
                                "message": str(exc),
                                "resource_capability": "CLINICAL_DATABASE",
                            })
                    # An absent optional CLINICAL_DATABASE selection means the
                    # lab has explicitly chosen not to use ClinVar in this profile.
                else:
                    # Legacy, non-profile analyses retain the explicit resource
                    # ID path and old deployment capability discovery.
                    if configured_clinvar_id:
                        case_for_resources = db.get(Case, analysis.case_id)
                        if case_for_resources is None:
                            raise ResourceConsumptionError(
                                "CASE_NOT_FOUND",
                                "The analysis case was not found while resolving its ClinVar resource.",
                            )
                        clinvar_resource = _require_registered_resource(
                            db,
                            resource_id=configured_clinvar_id,
                            organization_id=case_for_resources.organization_id,
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
                hpo_resource = None
                hpo_execution = None
                hpo_ontology = None
                hpo_resource_metadata = None
                hpoa_resource = None
                hpoa_execution = None
                hpoa_provider = None
                hpoa_resource_metadata = None
                case_for_clingen = db.get(Case, analysis.case_id)
                if case_for_clingen is not None:
                    if profile_bound_analysis:
                        try:
                            vp_runtime = resolve_profile_runtime_resources(
                                db,
                                analysis_id=analysis.id,
                                capability="CLINGEN_VARIANT_ASSERTION",
                                provider_id=ClinGenVariantPathogenicityProvider.provider_id,
                            )
                            vp_candidates = [
                                (item.resource, item.execution) for item in vp_runtime
                            ]
                        except ProfileRuntimeResourceError as exc:
                            vp_candidates = []
                            provider_limitations.append({
                                "code": exc.code,
                                "message": str(exc),
                                "resource_capability": "CLINGEN_VARIANT_ASSERTION",
                            })
                    else:
                        vp_plan = build_resource_execution_plan(db, organization_id=case_for_clingen.organization_id, requirements=(CapabilityRequirement(ResourceCapability.CLINICAL_VARIANT),))
                        vp_candidates = [
                            (item.resource, resolve_resource_execution(db, resource=item.resource))
                            for item in vp_plan.for_capability(ResourceCapability.CLINICAL_VARIANT)
                            if item.resource.provider == ClinGenVariantPathogenicityProvider.provider_id
                        ]
                    if vp_candidates:
                        if len(vp_candidates) != 1:
                            raise ResourceExecutionError(
                                "The analysis resource plan selected multiple ClinGen variant assertion resources."
                            )
                        clingen_vp_resource, clingen_vp_execution = vp_candidates[0]
                        clingen_vp_provider = ClinGenVariantPathogenicityProvider.from_execution_contract(resolved=clingen_vp_execution)
                        clingen_vp_metadata = {**clingen_vp_execution.snapshot, "resource_name": clingen_vp_resource.name, "resource_checksum": clingen_vp_resource.checksum}

                    if profile_bound_analysis:
                        try:
                            gdv_runtime = resolve_profile_runtime_resources(
                                db,
                                analysis_id=analysis.id,
                                capability="CLINGEN_GENE_DISEASE_VALIDITY",
                                provider_id=ClinGenGeneDiseaseValidityProvider.provider_id,
                            )
                            gdv_candidates = [
                                (item.resource, item.execution) for item in gdv_runtime
                            ]
                        except ProfileRuntimeResourceError as exc:
                            gdv_candidates = []
                            provider_limitations.append({
                                "code": exc.code,
                                "message": str(exc),
                                "resource_capability": "CLINGEN_GENE_DISEASE_VALIDITY",
                            })
                    else:
                        gdv_plan = build_resource_execution_plan(db, organization_id=case_for_clingen.organization_id, requirements=(CapabilityRequirement(ResourceCapability.GENE_DISEASE),))
                        gdv_candidates = [
                            (item.resource, resolve_resource_execution(db, resource=item.resource))
                            for item in gdv_plan.for_capability(ResourceCapability.GENE_DISEASE)
                            if item.resource.provider == ClinGenGeneDiseaseValidityProvider.provider_id
                        ]
                    if gdv_candidates:
                        if len(gdv_candidates) != 1:
                            raise ResourceExecutionError(
                                "The analysis resource plan selected multiple ClinGen gene-disease resources."
                            )
                        clingen_gdv_resource, clingen_gdv_execution = gdv_candidates[0]
                        clingen_gdv_provider = ClinGenGeneDiseaseValidityProvider.from_execution_contract(resolved=clingen_gdv_execution)
                        clingen_gdv_metadata = {**clingen_gdv_execution.snapshot, "resource_name": clingen_gdv_resource.name, "resource_checksum": clingen_gdv_resource.checksum}
                    try:
                        if profile_bound_analysis:
                            hpo_runtime = resolve_profile_runtime_resources(
                                db,
                                analysis_id=analysis.id,
                                capability="PHENOTYPE_ONTOLOGY",
                            )
                            hpo_candidates = [
                                (item.resource, item.execution) for item in hpo_runtime
                                if item.resource.provider == "HPO"
                            ]
                            if hpo_runtime and not hpo_candidates:
                                raise ResourceExecutionError(
                                    "The pinned phenotype resource has no executable HPO OBO adapter."
                                )
                        else:
                            hpo_plan = build_resource_execution_plan(
                                db,
                                organization_id=case_for_clingen.organization_id,
                                requirements=(CapabilityRequirement(ResourceCapability.PHENOTYPE),),
                            )
                            planned_hpo = [
                                item for item in hpo_plan.for_capability(ResourceCapability.PHENOTYPE)
                                if item.resource.provider == "HPO"
                            ]
                            hpo_candidates = [
                                (
                                    item.resource,
                                    resolve_resource_execution(db, resource=item.resource),
                                )
                                for item in planned_hpo
                            ]
                        if hpo_candidates:
                            if len(hpo_candidates) != 1:
                                raise ResourceExecutionError(
                                    "The analysis plan selected multiple HPO ontology resources."
                                )
                            hpo_resource, hpo_execution = hpo_candidates[0]
                            contract_checksum = str(
                                (hpo_execution.contract.toolchain or {}).get("sha256")
                                or (hpo_execution.contract.toolchain or {}).get("checksum")
                                or ""
                            ).lower()
                            if contract_checksum.startswith("sha256:"):
                                contract_checksum = contract_checksum.partition(":")[2]
                            resource_checksum = str(hpo_resource.checksum or "").lower()
                            if resource_checksum.startswith("sha256:"):
                                resource_checksum = resource_checksum.partition(":")[2]
                            if not resource_checksum or contract_checksum != resource_checksum:
                                raise ResourceExecutionError(
                                    "HPO resource checksum must be present and match the qualified execution contract."
                                )
                            implementation = register_builtin_providers().require(
                                provider_id="HPO",
                                provider_version=hpo_execution.contract.provider_version,
                            )
                            hpo_ontology = implementation.factory(hpo_execution.contract)
                            if hpo_resource.version != hpo_ontology.release:
                                raise ResourceExecutionError(
                                    "HPO resource version does not match the release declared by its OBO artifact."
                                )
                            hpo_resource_metadata = {
                                "resource_id": str(hpo_resource.id),
                                "resource_name": hpo_resource.name,
                                "resource_version": hpo_resource.version,
                                "resource_checksum": hpo_resource.checksum,
                                "qualification_id": str(hpo_execution.qualification_id),
                                "qualification_version": hpo_execution.qualification_version,
                                "contract_hash": hpo_execution.contract_hash,
                                "ontology_release": hpo_ontology.release,
                            }
                    except (
                        ProfileRuntimeResourceError,
                        ResourceExecutionError,
                        ProviderRegistryError,
                        HPOOntologyError,
                    ) as exc:
                        if hpo_resource is not None and hpo_execution is not None:
                            failed_execution = start_resource_execution(
                                db,
                                analysis_id=analysis.id,
                                step_id="build_evidence",
                                attempt=max(1, int(evidence_step.attempt or 0)),
                                batch_key="ontology-load",
                                resolved=hpo_execution,
                                requested_resource_id=hpo_resource.id,
                                fallback_resource_id=None,
                                metadata={
                                    "execution_kind": "HPO_ONTOLOGY_RESOURCE_VALIDATION",
                                    "resource_name": hpo_resource.name,
                                    "resource_version": hpo_resource.version,
                                    "resource_checksum": hpo_resource.checksum,
                                },
                            )
                            complete_resource_execution(
                                db,
                                failed_execution,
                                status="FAILED",
                                error_code="HPO_ONTOLOGY_RESOURCE_INVALID",
                                error_message=str(exc),
                            )
                        provider_limitations.append({
                            "code": "HPO_ONTOLOGY_RESOURCE_UNAVAILABLE",
                            "message": str(exc),
                            "resource_capability": "PHENOTYPE_ONTOLOGY",
                        })
                        hpo_resource = hpo_execution = hpo_ontology = None
                        hpo_resource_metadata = None
                    try:
                        if profile_bound_analysis:
                            hpoa_runtime = resolve_profile_runtime_resources(
                                db,
                                analysis_id=analysis.id,
                                capability="DISEASE_PHENOTYPE_ASSOCIATION",
                            )
                            hpoa_candidates = [
                                (item.resource, item.execution)
                                for item in hpoa_runtime
                                if item.resource.provider == "HPOA"
                            ]
                            if hpoa_runtime and not hpoa_candidates:
                                raise ResourceExecutionError(
                                    "The pinned disease-phenotype resource has no executable HPOA adapter."
                                )
                        else:
                            hpoa_plan = build_resource_execution_plan(
                                db,
                                organization_id=case_for_clingen.organization_id,
                                requirements=(
                                    CapabilityRequirement(ResourceCapability.DISEASE_PHENOTYPE),
                                ),
                            )
                            planned_hpoa = [
                                item for item in hpoa_plan.for_capability(
                                    ResourceCapability.DISEASE_PHENOTYPE
                                )
                                if item.resource.provider == "HPOA"
                            ]
                            hpoa_candidates = [
                                (
                                    item.resource,
                                    resolve_resource_execution(db, resource=item.resource),
                                )
                                for item in planned_hpoa
                            ]
                        if hpoa_candidates:
                            if len(hpoa_candidates) != 1:
                                raise ResourceExecutionError(
                                    "The analysis plan selected multiple HPOA disease-phenotype resources."
                                )
                            hpoa_resource, hpoa_execution = hpoa_candidates[0]
                            if (
                                hpoa_resource.organization_id
                                != case_for_clingen.organization_id
                            ):
                                raise ResourceExecutionError(
                                    "HPOA must be an organization-bound laboratory resource."
                                )
                            if not str(hpoa_resource.license_text or "").strip():
                                raise ResourceExecutionError(
                                    "HPOA execution requires the laboratory's documented license permission."
                                )
                            contract_checksum = str(
                                (hpoa_execution.contract.toolchain or {}).get("sha256")
                                or (hpoa_execution.contract.toolchain or {}).get("checksum")
                                or ""
                            ).lower()
                            resource_checksum = str(hpoa_resource.checksum or "").lower()
                            if contract_checksum.startswith("sha256:"):
                                contract_checksum = contract_checksum.partition(":")[2]
                            if resource_checksum.startswith("sha256:"):
                                resource_checksum = resource_checksum.partition(":")[2]
                            if not resource_checksum or contract_checksum != resource_checksum:
                                raise ResourceExecutionError(
                                    "HPOA checksum must match the approved resource and execution contract."
                                )
                            implementation = register_builtin_providers().require(
                                provider_id="HPOA",
                                provider_version=hpoa_execution.contract.provider_version,
                            )
                            hpoa_provider = implementation.factory(hpoa_execution.contract)
                            if hpoa_resource.version != hpoa_provider.release:
                                raise ResourceExecutionError(
                                    "HPOA resource version does not match the release declared by its file."
                                )
                            contract_hpo_release = str(
                                (hpoa_execution.contract.toolchain or {}).get("hpo_release") or ""
                            )
                            if hpoa_provider.hpo_release != contract_hpo_release:
                                raise ResourceExecutionError(
                                    "HPOA file ontology release does not match its qualified resource contract."
                                )
                            hpoa_resource_metadata = {
                                "resource_id": str(hpoa_resource.id),
                                "resource_name": hpoa_resource.name,
                                "resource_version": hpoa_resource.version,
                                "resource_checksum": hpoa_resource.checksum,
                                "qualification_id": str(hpoa_execution.qualification_id),
                                "qualification_version": hpoa_execution.qualification_version,
                                "contract_hash": hpoa_execution.contract_hash,
                                "hpoa_release": hpoa_provider.release,
                                "hpo_release": hpoa_provider.hpo_release,
                            }
                    except (
                        ProfileRuntimeResourceError,
                        ResourceExecutionError,
                        ProviderRegistryError,
                        HPOAError,
                    ) as exc:
                        if hpoa_resource is not None and hpoa_execution is not None:
                            failed_execution = start_resource_execution(
                                db,
                                analysis_id=analysis.id,
                                step_id="build_evidence",
                                attempt=max(1, int(evidence_step.attempt or 0)),
                                batch_key="hpoa-load",
                                resolved=hpoa_execution,
                                requested_resource_id=hpoa_resource.id,
                                fallback_resource_id=None,
                                metadata={
                                    "execution_kind": "HPOA_RESOURCE_VALIDATION",
                                    "resource_name": hpoa_resource.name,
                                    "resource_version": hpoa_resource.version,
                                    "resource_checksum": hpoa_resource.checksum,
                                },
                            )
                            complete_resource_execution(
                                db,
                                failed_execution,
                                status="FAILED",
                                error_code="HPOA_RESOURCE_INVALID",
                                error_message=str(exc),
                            )
                        provider_limitations.append({
                            "code": "HPOA_RESOURCE_UNAVAILABLE",
                            "message": str(exc),
                            "resource_capability": "DISEASE_PHENOTYPE_ASSOCIATION",
                        })
                        hpoa_resource = hpoa_execution = hpoa_provider = None
                        hpoa_resource_metadata = None
                from backend.app.domain.clinical_input_snapshot import (
                    capture_or_reuse_case_clinical_input_snapshot,
                )

                try:
                    clinical_input_snapshot = capture_or_reuse_case_clinical_input_snapshot(
                        db, analysis, evidence_step
                    )
                except ValueError as exc:
                    raise RuntimeError(str(exc)) from exc

                case_hpo_terms = [
                    {
                        "hpo_id": row["hpo_id"],
                        "label": row.get("label"),
                        "present": row.get("present"),
                        "phenotype_status": row["phenotype_status"],
                    }
                    for row in clinical_input_snapshot["phenotype_observations"]
                ]
                gene_disease_records = clinical_input_snapshot["gene_disease_evidence"]
                literature_records = clinical_input_snapshot["literature_evidence"]
                hpoa_disease_annotations: dict[str, tuple] = {}
                hpoa_provenance = None
                if hpoa_provider is not None and hpoa_resource is not None and hpoa_execution is not None:
                    disease_ids = sorted({
                        str(item.get("disease_id") or item.get("disease_identifier") or "").strip()
                        for item in gene_disease_records
                        if isinstance(item, dict)
                        and str(item.get("disease_id") or item.get("disease_identifier") or "").strip()
                    })
                    if disease_ids:
                        hpoa_disease_annotations = {
                            disease_id: hpoa_provider.query_disease(disease_id)
                            for disease_id in disease_ids
                        }
                        hpoa_request = {
                            "analysis_id": str(analysis.id),
                            "resource_id": str(hpoa_execution.resource_id),
                            "resource_version": hpoa_execution.resource_version,
                            "contract_hash": hpoa_execution.contract_hash,
                            "disease_ids": disease_ids,
                        }
                        hpoa_request_fingerprint = hashlib.sha256(
                            json.dumps(hpoa_request, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest()
                        hpoa_response_material = {
                            disease_id: [asdict(item) for item in annotations]
                            for disease_id, annotations in hpoa_disease_annotations.items()
                        }
                        hpoa_response_sha256 = hashlib.sha256(
                            json.dumps(
                                hpoa_response_material,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest()
                        hpoa_provenance = {
                            **(hpoa_resource_metadata or {}),
                            "request_fingerprint": hpoa_request_fingerprint,
                            "response_sha256": hpoa_response_sha256,
                        }
                        if not _succeeded_evidence_execution(
                            db,
                            analysis_id=analysis.id,
                            resource_id=hpoa_execution.resource_id,
                            batch_key="disease-annotations",
                            request_fingerprint=hpoa_request_fingerprint,
                            execution_kind="HPOA_DISEASE_ANNOTATION_QUERY",
                        ):
                            hpoa_execution_row = start_resource_execution(
                                db,
                                analysis_id=analysis.id,
                                step_id="build_evidence",
                                attempt=max(1, int(evidence_step.attempt or 0)),
                                batch_key="disease-annotations",
                                resolved=hpoa_execution,
                                requested_resource_id=hpoa_resource.id,
                                fallback_resource_id=None,
                                metadata={
                                    "execution_kind": "HPOA_DISEASE_ANNOTATION_QUERY",
                                    "disease_count": len(disease_ids),
                                    "input_sha256": hpoa_request_fingerprint,
                                    "output_sha256": hpoa_response_sha256,
                                    "hpoa_release": hpoa_provider.release,
                                    "hpo_release": hpoa_provider.hpo_release,
                                },
                            )
                            complete_resource_execution(
                                db,
                                hpoa_execution_row,
                                status=(
                                    "SUCCESS"
                                    if any(hpoa_disease_annotations.values())
                                    else "NO_DATA"
                                ),
                                request_fingerprint=hpoa_request_fingerprint,
                                response_sha256=hpoa_response_sha256,
                            )

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
                    hpo_provenance = None
                    if hpo_resource is not None and hpo_execution is not None and hpo_ontology is not None:
                        disease_terms = [
                            str(term.get("hpo_id") or term.get("id") or "") if isinstance(term, dict) else str(term)
                            for item in gene_disease_records
                            for term in (item.get("hpo_terms") or item.get("associated_hpo_terms") or [])
                        ]
                        hpo_request = {
                            "analysis_id": str(analysis.id),
                            "resource_id": str(hpo_execution.resource_id),
                            "resource_version": hpo_execution.resource_version,
                            "contract_hash": hpo_execution.contract_hash,
                            "patient_terms": sorted(
                                [
                                    {
                                        "hpo_id": str(term.get("hpo_id") or ""),
                                        "phenotype_status": str(
                                            term.get("phenotype_status")
                                            or ("PRESENT" if term.get("present", True) else "ABSENT")
                                        ),
                                    }
                                    for term in case_hpo_terms
                                ],
                                key=lambda term: (term["hpo_id"], term["phenotype_status"]),
                            ),
                            "disease_terms": sorted(disease_terms),
                        }
                        hpo_request_fingerprint = hashlib.sha256(
                            json.dumps(hpo_request, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest()
                        resolved_terms = sorted(
                            {term["hpo_id"] for term in hpo_request["patient_terms"]}
                            | set(disease_terms)
                        )
                        hpo_output = {}
                        for term in resolved_terms:
                            resolution = hpo_ontology.resolve(term)
                            hpo_output[term] = {
                                "resolution": resolution.status,
                                "canonical_id": resolution.canonical_id,
                                "label": resolution.label,
                                "replacement_candidates": list(resolution.replacement_candidates),
                                "consider": list(resolution.consider),
                                "ambiguous_candidates": list(resolution.ambiguous_candidates),
                                "ancestors": sorted(hpo_ontology.ancestors(term)),
                            }
                        hpo_response_sha256 = hashlib.sha256(
                            json.dumps(hpo_output, sort_keys=True, separators=(",", ":")).encode()
                        ).hexdigest()
                        if not _succeeded_evidence_execution(
                            db,
                            analysis_id=analysis.id,
                            resource_id=hpo_execution.resource_id,
                            batch_key=key,
                            request_fingerprint=hpo_request_fingerprint,
                            execution_kind="HPO_ONTOLOGY_TERM_RESOLUTION",
                        ):
                            hpo_execution_row = start_resource_execution(
                                db,
                                analysis_id=analysis.id,
                                step_id="build_evidence",
                                attempt=attempt,
                                batch_key=key,
                                resolved=hpo_execution,
                                requested_resource_id=hpo_resource.id,
                                fallback_resource_id=None,
                                metadata={
                                    "execution_kind": "HPO_ONTOLOGY_TERM_RESOLUTION",
                                    "patient_term_count": len(case_hpo_terms),
                                    "disease_term_count": len(disease_terms),
                                    "input_sha256": hpo_request_fingerprint,
                                    "output_sha256": hpo_response_sha256,
                                    "ontology_release": hpo_ontology.release,
                                    "ontology_sha256": hpo_ontology.sha256,
                                },
                            )
                            complete_resource_execution(
                                db,
                                hpo_execution_row,
                                status="SUCCESS",
                                request_fingerprint=hpo_request_fingerprint,
                                response_sha256=hpo_response_sha256,
                            )
                        hpo_provenance = {
                            **(hpo_resource_metadata or {}),
                            "resource_id": str(hpo_resource.id),
                            "resource_version": hpo_resource.version,
                            "request_fingerprint": hpo_request_fingerprint,
                            "response_sha256": hpo_response_sha256,
                        }
                    annotations = db.scalars(select(Annotation).where(Annotation.analysis_id == analysis.id).order_by(Annotation.created_at, Annotation.id).offset(start_i).limit(end_i - start_i)).all()
                    variant_ids_for_batch = [a.variant_id for a in annotations]
                    population_rows = db.scalars(select(PopulationObservation).where(PopulationObservation.analysis_id == analysis.id, PopulationObservation.variant_id.in_(variant_ids_for_batch))).all() if variant_ids_for_batch else []
                    resource_rows = _require_population_resource_rows(
                        db,
                        analysis_id=analysis.id,
                        organization_id=case.organization_id,
                        observations=population_rows,
                    )
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
                            hpo_ontology=hpo_ontology,
                            hpo_provenance=hpo_provenance,
                        ))
                        if hpoa_provenance is not None:
                            records.extend(engine.build_hpoa_disease_phenotype_evidence(
                                variant_id=row.id,
                                gene=gene_symbol,
                                gene_disease_records=gene_disease_records,
                                annotations_by_disease=hpoa_disease_annotations,
                                provenance=hpoa_provenance,
                                patient_hpo_terms=case_hpo_terms,
                                hpo_ontology=hpo_ontology,
                            ))

                        gene = gene_symbol or ((normalized.get("gene") or {}).get("symbol")) or normalized.get("gene_symbol")
                        hgvs_values: list[str] = []
                        for consequence in normalized.get("hgvs_consequences") or []:
                            if isinstance(consequence, str):
                                hgvs_values.append(consequence)
                            elif isinstance(consequence, dict):
                                hgvs_values.extend(
                                    value
                                    for key in ("hgvs", "hgvsc", "hgvsp")
                                    if isinstance((value := consequence.get(key)), str)
                                    and value.strip()
                                )
                        raw_hgvs = normalized.get("hgvs")
                        if isinstance(raw_hgvs, str) and raw_hgvs.strip():
                            hgvs_values.append(raw_hgvs)
                        elif isinstance(raw_hgvs, dict):
                            hgvs_values.extend(
                                value
                                for key in ("c", "p", "hgvsc", "hgvsp")
                                if isinstance((value := raw_hgvs.get(key)), str)
                                and value.strip()
                            )
                        hgvs_values = list(dict.fromkeys(hgvs_values))
                        if clingen_vp_provider is not None and clingen_vp_resource is not None and clingen_vp_execution is not None and gene:
                            query_material = {"analysis_id": str(analysis.id), "variant_id": str(row.id), "gene": gene, "hgvs": hgvs_values, "resource_id": str(clingen_vp_execution.resource_id), "resource_version": clingen_vp_execution.resource_version, "contract_hash": clingen_vp_execution.contract_hash}
                            request_fingerprint = hashlib.sha256(json.dumps(query_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                            if not _succeeded_evidence_execution(
                                db,
                                analysis_id=analysis.id,
                                resource_id=clingen_vp_execution.resource_id,
                                batch_key=key,
                                request_fingerprint=request_fingerprint,
                                execution_kind="CLINGEN_VARIANT_PATHOGENICITY_QUERY",
                            ):
                                execution_row = start_resource_execution(db, analysis_id=analysis.id, step_id="build_evidence", attempt=attempt, batch_key=key, resolved=clingen_vp_execution, requested_resource_id=clingen_vp_resource.id, fallback_resource_id=None, metadata={"execution_kind": "CLINGEN_VARIANT_PATHOGENICITY_QUERY", "query": query_material})
                                try:
                                    assertions = clingen_vp_provider.query_variant(gene=gene, hgvs=hgvs_values)
                                    response_material = [{"source_record_id": x.source_record_id, "record_sha256": x.record_sha256} for x in assertions]
                                    response_sha256 = hashlib.sha256(json.dumps(response_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                                    complete_resource_execution(db, execution_row, status="SUCCESS" if assertions else "NO_DATA", request_fingerprint=request_fingerprint, response_sha256=response_sha256)
                                    records.extend(engine.build_from_clingen_variant_assertions(variant_id=row.id, assertions=assertions, resource_id=clingen_vp_execution.resource_id, resource_name=clingen_vp_resource.name, resource_version=clingen_vp_execution.resource_version, request_fingerprint=request_fingerprint, execution_metadata={**clingen_vp_metadata, "query": query_material, "response_sha256": response_sha256}))
                                except ClinGenVariantPathogenicityError as exc:
                                    complete_resource_execution(db, execution_row, status="FAILED", request_fingerprint=request_fingerprint, error_code="CLINGEN_VARIANT_PATHOGENICITY_QUERY_FAILED", error_message=str(exc))
                                    provider_limitations.append({
                                        "code": "CLINGEN_VARIANT_PATHOGENICITY_QUERY_FAILED",
                                        "message": str(exc),
                                        "resource_capability": "CLINGEN_VARIANT_ASSERTION",
                                        "variant_id": str(row.id),
                                    })

                        if clingen_gdv_provider is not None and clingen_gdv_resource is not None and clingen_gdv_execution is not None and gene:
                            query_material = {"analysis_id": str(analysis.id), "variant_id": str(row.id), "gene": gene, "resource_id": str(clingen_gdv_execution.resource_id), "resource_version": clingen_gdv_execution.resource_version, "contract_hash": clingen_gdv_execution.contract_hash}
                            request_fingerprint = hashlib.sha256(json.dumps(query_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                            if not _succeeded_evidence_execution(
                                db,
                                analysis_id=analysis.id,
                                resource_id=clingen_gdv_execution.resource_id,
                                batch_key=key,
                                request_fingerprint=request_fingerprint,
                                execution_kind="CLINGEN_GENE_DISEASE_VALIDITY_QUERY",
                            ):
                                execution_row = start_resource_execution(db, analysis_id=analysis.id, step_id="build_evidence", attempt=attempt, batch_key=key, resolved=clingen_gdv_execution, requested_resource_id=clingen_gdv_resource.id, fallback_resource_id=None, metadata={"execution_kind": "CLINGEN_GENE_DISEASE_VALIDITY_QUERY", "query": query_material})
                                try:
                                    assertions = clingen_gdv_provider.query_gene(gene=gene)
                                    response_material = [{"source_record_id": x.source_record_id, "record_sha256": x.record_sha256} for x in assertions]
                                    response_sha256 = hashlib.sha256(json.dumps(response_material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                                    complete_resource_execution(db, execution_row, status="SUCCESS" if assertions else "NO_DATA", request_fingerprint=request_fingerprint, response_sha256=response_sha256)
                                    records.extend(engine.build_from_clingen_gene_disease_assertions(variant_id=row.id, assertions=assertions, resource_id=clingen_gdv_execution.resource_id, resource_name=clingen_gdv_resource.name, resource_version=clingen_gdv_execution.resource_version, request_fingerprint=request_fingerprint, execution_metadata={**clingen_gdv_metadata, "query": query_material, "response_sha256": response_sha256}))
                                except ClinGenGeneDiseaseValidityError as exc:
                                    complete_resource_execution(db, execution_row, status="FAILED", request_fingerprint=request_fingerprint, error_code="CLINGEN_GENE_DISEASE_VALIDITY_QUERY_FAILED", error_message=str(exc))
                                    provider_limitations.append({
                                        "code": "CLINGEN_GENE_DISEASE_VALIDITY_QUERY_FAILED",
                                        "message": str(exc),
                                        "resource_capability": "CLINGEN_GENE_DISEASE_VALIDITY",
                                        "variant_id": str(row.id),
                                    })
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
                            if not _succeeded_evidence_execution(
                                db,
                                analysis_id=analysis.id,
                                resource_id=clinvar_execution.resource_id,
                                batch_key=key,
                                request_fingerprint=request_fingerprint,
                                execution_kind="CLINVAR_VARIANT_QUERY",
                            ):
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
                                            resource_version=clinvar_execution.resource_version,
                                            request_fingerprint=request_fingerprint,
                                            execution_metadata={
                                                **clinvar_execution_metadata,
                                                "query": query_material,
                                                "response_sha256": response_sha256,
                                            },
                                        )
                                    )
                                except ClinVarProviderError as exc:
                                    complete_resource_execution(
                                        db,
                                        execution_row,
                                        status="FAILED",
                                        request_fingerprint=request_fingerprint,
                                        error_code="CLINVAR_QUERY_FAILED",
                                        error_message=str(exc),
                                    )
                                    provider_limitations.append({
                                        "code": "CLINVAR_QUERY_FAILED",
                                        "message": str(exc),
                                        "resource_capability": "CLINICAL_DATABASE",
                                        "variant_id": str(row.id),
                                    })

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
                # A prior attempt may have committed evidence rows and then died
                # before checkpointing the batch as SUCCEEDED. On retry, those
                # rows are deduplicated, so this attempt's created counter can be
                # zero even though durable evidence exists. Base the scientific
                # outcome on persisted state, not this attempt's insertion count.
                persisted_evidence_count = _count_persisted_evidence(db, analysis.id)
                evidence_step.input_artifacts = [str(normalized_artifact.id)] if normalized_artifact else []
                evidence_metadata = {
                    "engine": engine.engine_id,
                    "engine_version": engine.engine_version,
                    "created_evidence": created,
                    "persisted_evidence": persisted_evidence_count,
                    "optional_resource_limitations": clinvar_limitations,
                    "provider_limitations": provider_limitations,
                }
                if persisted_evidence_count == 0 or provider_limitations:
                    limitation_message = (
                        "Evidence collection completed with one or more source-provider limitations. "
                        "Any resulting criterion proposals require human review."
                        if provider_limitations
                        else
                        "Evidence collection completed, but no reportable evidence records were "
                        "established from the available annotation, population, phenotype, gene-disease, "
                        "or literature context."
                    )
                    _apply_scientific_limitation(
                        db,
                        evidence_step,
                        outcome=OutcomeKind.INSUFFICIENT_EVIDENCE,
                        code=(
                            "EVIDENCE_SOURCE_LIMITATION_REQUIRES_REVIEW"
                            if provider_limitations
                            else "EVIDENCE_INSUFFICIENT"
                        ),
                        message=limitation_message,
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
                    payload={
                        "created_evidence": created,
                        "persisted_evidence": persisted_evidence_count,
                        "engine_version": engine.engine_version,
                    },
                )
                db.commit()
            except (ResourceConsumptionError, ResourceExecutionError, ClinVarProviderError) as exc:
                code = getattr(exc, "code", None) or "EVIDENCE_RESOURCE_UNAVAILABLE"
                # Do not consume an unqualified source or fail the whole analysis
                # because a clinical evidence provider is unavailable. Preserve any
                # evidence already persisted, record the gap, and force ACMG review.
                _apply_scientific_limitation(
                    db,
                    evidence_step,
                    outcome=OutcomeKind.INSUFFICIENT_EVIDENCE,
                    code=code,
                    message=str(exc),
                    metadata={
                        "next_step": "acmg_assessment",
                        "resource_limitation": True,
                        "automatic_fallback": False,
                        "partial_evidence_build": True,
                    },
                )
                audit.record(
                    event_type="EVIDENCE_RESOURCE_LIMITATION",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id="evidence-resource",
                    reason=str(exc),
                    payload={
                        "error_code": code,
                        "next_step": "acmg_assessment",
                        "automatic_fallback": False,
                        "partial_evidence_build": True,
                    },
                )
                db.commit()
            except OSError as exc:
                _schedule_transient_step_retry(
                    db,
                    analysis_id=analysis.id,
                    step_id="build_evidence",
                    error_code="EVIDENCE_INFRASTRUCTURE_RETRYING",
                    error_message=str(exc),
                    event_type="EVIDENCE_INFRASTRUCTURE_RETRY_SCHEDULED",
                    actor_id="siraloom-evidence",
                    next_step="build_evidence",
                )
                raise TransientWorkflowError(
                    "Evidence stage filesystem/storage operation failed; retrying from the durable evidence checkpoint.",
                    countdown=10,
                    max_retries=3,
                    error_code="EVIDENCE_INFRASTRUCTURE_RETRY_EXHAUSTED",
                ) from exc
            except SQLAlchemyError as exc:
                _schedule_transient_step_retry(
                    db,
                    analysis_id=analysis.id,
                    step_id="build_evidence",
                    error_code="EVIDENCE_PERSISTENCE_RETRYING",
                    error_message=str(exc),
                    event_type="EVIDENCE_PERSISTENCE_RETRY_SCHEDULED",
                    actor_id="siraloom-evidence",
                    next_step="build_evidence",
                )
                raise TransientWorkflowError(
                    "Evidence persistence failed; retrying from the durable evidence checkpoint.",
                    countdown=10,
                    max_retries=3,
                    error_code="EVIDENCE_PERSISTENCE_RETRY_EXHAUSTED",
                ) from exc
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
        if (
            acmg_step.status == StepStatus.REQUIRES_REVIEW
            and _manual_acmg_review_complete(db, analysis.id)
        ):
            annotated_variant_ids = set(db.scalars(
                select(Annotation.variant_id)
                .where(Annotation.analysis_id == analysis.id)
                .distinct()
            ).all())
            latest_classifications = _latest_classifications_by_variant(db, analysis.id)
            manual_classification_count = sum(
                1
                for variant_id in annotated_variant_ids
                if (
                    latest_classifications.get(variant_id) is not None
                    and (latest_classifications[variant_id].metadata_json or {}).get("decision_mode") == "MANUAL"
                )
            )
            mark_step(
                db,
                acmg_step,
                StepStatus.SUCCEEDED,
                metadata={
                    "assessed_variants": len(annotated_variant_ids),
                    "classification_automation": "MANUAL_REVIEWED",
                    "manual_classification_count": manual_classification_count,
                    "reconciled_after_review": True,
                    "next_step": "review",
                },
            )
            audit.record(
                event_type="ACMG_MANUAL_CLASSIFICATION_RECONCILED",
                case_id=analysis.case_id,
                analysis_id=analysis.id,
                actor_type="SYSTEM",
                actor_id="siraloom-acmg-specification-engine",
                reason="All annotated variants have final approved classifications; variants without automated ACMG criteria were explicitly reviewed and classified manually.",
                payload={
                    "annotated_variants": len(annotated_variant_ids),
                    "manual_classification_count": manual_classification_count,
                },
            )
            db.commit()

        population_step_for_acmg = _step(db, analysis.id, "population")
        evidence_step_for_acmg = _step(db, analysis.id, "build_evidence")
        population_scientific_gap = bool(
            (population_step_for_acmg.metadata_json or {}).get("scientific_limitation")
        )
        evidence_scientific_gap = bool(
            (evidence_step_for_acmg.metadata_json or {}).get("scientific_limitation")
        )

        if acmg_step.status != StepStatus.SUCCEEDED:
            mark_step(db, acmg_step, StepStatus.RUNNING)
            try:
                from backend.app.acmg.assessment_service import ACMGSpecificationAssessmentService
                # Case is imported at module scope; do not shadow it locally.

                case = db.get(Case, analysis.case_id)
                case_context = case.clinical_context if case else {}
                disease = analysis.configuration.get("disease") or case_context.get("disease")
                assessment_service = ACMGSpecificationAssessmentService()
                acmg_runtime_resource = None
                if profile_bound_analysis:
                    try:
                        profile_runtime_acmg = resolve_profile_runtime_resource(
                            db,
                            analysis_id=analysis.id,
                            capability="ACMG_RULE_SPECIFICATION",
                        )
                    except ProfileRuntimeResourceError as exc:
                        raise ResourceConsumptionError(exc.code, str(exc)) from exc
                    acmg_runtime_resource = profile_runtime_acmg.resource
                    if acmg_runtime_resource.provider.strip().upper() != "CLINGEN":
                        raise ResourceConsumptionError(
                            "ACMG_ADAPTER_UNSUPPORTED",
                            f"Governed ACMG specification provider {acmg_runtime_resource.provider!r} is not supported.",
                        )
                    acmg_metadata = dict(acmg_runtime_resource.metadata_json or {})
                    if not str(acmg_metadata.get("specification_id") or "").strip() or not str(
                        acmg_metadata.get("specification_version") or ""
                    ).strip():
                        raise ResourceConsumptionError(
                            "ACMG_SPECIFICATION_IDENTITY_MISSING",
                            "Qualified ClinGen ACMG resource must declare specification_id and specification_version in resource metadata.",
                        )
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
                        # Assessments persist across retries, but local counters do not.
                        # Restore review/blocking outcomes from the durable checkpoint so
                        # a partial manual review cannot incorrectly mark ACMG succeeded.
                        batch_review, batch_blocked = _completed_acmg_batch_outcome_counts(
                            acmg_step, start_i, end_i
                        )
                        review_variants += batch_review
                        blocked_variants += batch_blocked
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
                        population_resource_rows = _require_population_resource_rows(
                            db,
                            analysis_id=analysis.id,
                            organization_id=case.organization_id,
                            observations=population_rows_for_variant,
                        )
                        result = assessment_service.assess_variant(
                            db,
                            analysis=analysis,
                            variant=variant_row,
                            annotation=ann,
                            population_rows=population_rows_for_variant,
                            resource_rows=population_resource_rows,
                            gene=gene,
                            disease=disease,
                            specification_resource=acmg_runtime_resource,
                        )
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

                if (
                    assessed == 0
                    or review_variants > 0
                    or blocked_variants > 0
                    or population_scientific_gap
                    or evidence_scientific_gap
                ):
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
                    elif population_scientific_gap or evidence_scientific_gap:
                        review_code = "SCIENTIFIC_EVIDENCE_GAP_REQUIRES_REVIEW"
                        review_message = (
                            "Population or evidence collection recorded a scientific limitation. "
                            "Any automated criterion proposals remain provisional; an authorized "
                            "reviewer must inspect the missing-source context before classification "
                            "can be approved."
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
                            "population_scientific_gap": population_scientific_gap,
                            "evidence_scientific_gap": evidence_scientific_gap,
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
            except ResourceConsumptionError as exc:
                # Missing/unapproved ClinGen rules are a scientific governance gap,
                # not a terminal pipeline failure. Route the case to an authorized
                # human for manual classification or resource remediation; the
                # workflow can reconcile the manual decision on redelivery.
                _route_step_to_human_review(
                    db,
                    analysis_id=analysis.id,
                    step_id="acmg_assessment",
                    error_code=exc.code,
                    error_message=str(exc),
                    event_type="ACMG_RESOURCE_REQUIRES_REVIEW",
                    actor_id="acmg-resource",
                    next_step="review",
                    payload={"automatic_fallback": False, "resource_gap": True},
                )
                return
            except OSError as exc:
                _schedule_transient_step_retry(
                    db,
                    analysis_id=analysis.id,
                    step_id="acmg_assessment",
                    error_code="ACMG_INFRASTRUCTURE_RETRYING",
                    error_message=str(exc),
                    event_type="ACMG_INFRASTRUCTURE_RETRY_SCHEDULED",
                    actor_id="siraloom-acmg-specification-engine",
                    next_step="acmg_assessment",
                )
                raise TransientWorkflowError(
                    "ACMG stage filesystem/storage operation failed; retrying without fabricating a classification.",
                    countdown=10,
                    max_retries=3,
                    error_code="ACMG_INFRASTRUCTURE_RETRY_EXHAUSTED",
                ) from exc
            except SQLAlchemyError as exc:
                _schedule_transient_step_retry(
                    db,
                    analysis_id=analysis.id,
                    step_id="acmg_assessment",
                    error_code="ACMG_PERSISTENCE_RETRYING",
                    error_message=str(exc),
                    event_type="ACMG_PERSISTENCE_RETRY_SCHEDULED",
                    actor_id="siraloom-acmg-specification-engine",
                    next_step="acmg_assessment",
                )
                raise TransientWorkflowError(
                    "ACMG assessment persistence failed; retrying without fabricating a classification.",
                    countdown=10,
                    max_retries=3,
                    error_code="ACMG_PERSISTENCE_RETRY_EXHAUSTED",
                ) from exc
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
                from backend.app.reporting.reportability import (
                    evaluate_analysis,
                    final_reportability_state,
                )

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
            except SQLAlchemyError as exc:
                _schedule_transient_step_retry(
                    db,
                    analysis_id=analysis.id,
                    step_id="reportability",
                    error_code="REPORTABILITY_PERSISTENCE_RETRYING",
                    error_message=str(exc),
                    event_type="REPORTABILITY_PERSISTENCE_RETRY_SCHEDULED",
                    actor_id="workflow",
                    next_step="reportability",
                )
                raise TransientWorkflowError(
                    "Reportability persistence failed; retrying without creating a report.",
                    countdown=10,
                    max_retries=3,
                    error_code="REPORTABILITY_PERSISTENCE_RETRY_EXHAUSTED",
                ) from exc
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
                # Serialize report inputs against analysis-level decisions and
                # mutations before taking the case-wide report-version lock.
                # Keep the same Analysis -> Case lock order as the report API
                # and sign-out path so a draft cannot snapshot mixed state.
                analysis_for_report = db.get(
                    Analysis,
                    analysis.id,
                    with_for_update=True,
                )
                if analysis_for_report is None:
                    raise RuntimeError("Report analysis is missing during draft generation")
                db.refresh(analysis_for_report, with_for_update=True)
                analysis = analysis_for_report
                # Match the API's case-scoped lock: report versions are unique
                # across every analysis for a case and report type. Without
                # this lock, concurrent worker runs can allocate the same next
                # version before either report row commits.
                case_for_report = db.get(
                    Case,
                    analysis.case_id,
                    with_for_update=True,
                )
                if case_for_report is None:
                    raise RuntimeError("Report case is missing during version allocation")
                db.refresh(case_for_report, with_for_update=True)
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
                        artifact = _put_idempotent_stage_artifact(
                            artifacts,
                            artifact_id=uuid5(
                                analysis.id,
                                f"siraloom:report-pdf:draft:v1:{version}",
                            ),
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
                _schedule_transient_step_retry(
                    db,
                    analysis_id=analysis.id,
                    step_id="report",
                    error_code="REPORT_GENERATION_RETRYING",
                    error_message=str(exc),
                    event_type="REPORT_GENERATION_RETRY_SCHEDULED",
                    actor_id="reporting",
                    next_step="report",
                )
                raise TransientWorkflowError(
                    "Report generation failed; retrying from the durable report checkpoint.",
                    countdown=10,
                    max_retries=3,
                    error_code="REPORT_GENERATION_RETRY_EXHAUSTED",
                ) from exc

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
                _persist_terminal_provenance(
                    db,
                    artifacts=artifacts,
                    analysis=analysis,
                    provenance_step=provenance_step,
                    audit=audit,
                )
            except Exception as exc:
                # Provenance storage/database failures are retried through the
                # same bounded Celery retry path as other transient workflow
                # failures. Do not terminally fail the analysis on the first
                # failure after the clinical report has already been signed out.
                db.rollback()
                analysis = db.get(Analysis, analysis_id)
                provenance_step = _step(db, analysis_id, "export_provenance")
                if analysis is not None:
                    analysis.status = AnalysisStatus.RUNNING
                    analysis.completed_at = None
                mark_step(
                    db,
                    provenance_step,
                    StepStatus.RETRYING,
                    error_code="PROVENANCE_EXPORT_RETRYING",
                    error_message=str(exc),
                    metadata={
                        "next_step": "export_provenance",
                        "retry_policy": "bounded_transient_retry",
                    },
                )
                audit.record(
                    event_type="PROVENANCE_EXPORT_RETRY_SCHEDULED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="provenance",
                    reason=str(exc),
                    payload={
                        "error_code": "PROVENANCE_EXPORT_RETRYING",
                        "next_step": "export_provenance",
                        "max_retries": 3,
                    },
                )
                db.commit()
                raise TransientWorkflowError(
                    str(exc),
                    countdown=10,
                    max_retries=3,
                    error_code="PROVENANCE_EXPORT_RETRY_EXHAUSTED",
                ) from exc

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
        for temporary_path in temporary_artifact_paths:
            try:
                if temporary_path.is_dir():
                    shutil.rmtree(temporary_path, ignore_errors=True)
                else:
                    temporary_path.unlink(missing_ok=True)
            except OSError:
                # Cleanup failure must not mask the scientific workflow outcome.
                pass


def _latest_classifications_by_variant(db: Session, analysis_id: UUID) -> dict[UUID, Classification]:
    """Return the latest immutable classification version for each variant."""
    rows = db.scalars(
        select(Classification)
        .where(Classification.analysis_id == analysis_id)
        .order_by(Classification.variant_id, Classification.version.desc())
    )
    latest: dict[UUID, Classification] = {}
    for row in rows:
        latest.setdefault(row.variant_id, row)
    return latest


def _manifest_variant_membership(db: Session, analysis_id: UUID) -> set[UUID] | None:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        return None
    return get_analysis_variant_ids(analysis, db)


def _manual_acmg_review_complete(db: Session, analysis_id: UUID) -> bool:
    """Whether every annotated variant has a final, approved classification and any
    variant without persisted ACMG criteria was explicitly classified manually.
    """
    annotated_variant_ids = set(db.scalars(
        select(Annotation.variant_id)
        .where(Annotation.analysis_id == analysis_id)
        .distinct()
    ).all())
    manifest_variant_ids = _manifest_variant_membership(db, analysis_id)
    if manifest_variant_ids is not None:
        if annotated_variant_ids != manifest_variant_ids:
            return False
        annotated_variant_ids = manifest_variant_ids
    if not annotated_variant_ids:
        return False

    latest = _latest_classifications_by_variant(db, analysis_id)
    if not annotated_variant_ids.issubset(latest):
        return False

    variants_with_criteria = set(db.scalars(
        select(ACMGAssessment.variant_id)
        .where(ACMGAssessment.analysis_id == analysis_id)
        .distinct()
    ).all())

    for variant_id in annotated_variant_ids:
        classification = latest[variant_id]
        if classification.state != "FINAL" or classification.review_status != "APPROVED":
            return False
        if variant_id not in variants_with_criteria:
            if (classification.metadata_json or {}).get("decision_mode") != "MANUAL":
                return False
    return True


def _classification_review_gate_ready(db: Session, analysis_id: UUID) -> bool:
    """Require a final approved classification for every variant annotated in this analysis."""
    annotated_variant_ids = set(db.scalars(
        select(Annotation.variant_id)
        .where(Annotation.analysis_id == analysis_id)
        .distinct()
    ).all())
    manifest_variant_ids = _manifest_variant_membership(db, analysis_id)
    if manifest_variant_ids is not None:
        if annotated_variant_ids != manifest_variant_ids:
            return False
        annotated_variant_ids = manifest_variant_ids
    if not annotated_variant_ids:
        return False

    latest = _latest_classifications_by_variant(db, analysis_id)
    if not annotated_variant_ids.issubset(latest):
        return False

    return all(
        latest[variant_id].state == "FINAL"
        and latest[variant_id].review_status == "APPROVED"
        for variant_id in annotated_variant_ids
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

    manifest_variant_ids = _manifest_variant_membership(db, analysis_id)
    if manifest_variant_ids is not None and set(latest) != manifest_variant_ids:
        return False
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

def _iter_variant_batches(
    path: Path,
    genome_build: str,
    batch_size: int,
    *,
    exclusion_stats: dict[str, int] | None = None,
):
    """Yield (zero-based record start, bounded list) from a normalized VCF."""
    batch: list[CanonicalVariant] = []
    start = 0
    for variant in iter_normalized_vcf(
        path, genome_build, exclusion_stats=exclusion_stats
    ):
        batch.append(variant)
        if len(batch) >= batch_size:
            yield start, batch
            start += len(batch)
            batch = []
    if batch:
        yield start, batch


def _normalized_partition_metadata(
    variant_ids: list[UUID],
    variants: list[CanonicalVariant],
) -> dict:
    """Persist analysis-scoped calls beside canonical IDs in each normalize partition."""
    if len(variant_ids) != len(variants):
        raise ValueError("Normalized partition variant IDs and calls must have equal lengths")
    sample_calls = []
    for variant_id, variant in zip(variant_ids, variants):
        call = dict(variant.sample_call or {})
        sample_calls.append({
            "variant_id": str(variant_id),
            "status": call.get("status", "GENOTYPE_UNAVAILABLE"),
            "sample_name": call.get("sample_name"),
            "genotype": call.get("genotype"),
            "zygosity": call.get("zygosity", "UNKNOWN"),
            "phase": call.get("phase", "UNSPECIFIED"),
            "phase_set": call.get("phase_set"),
            "format_values": call.get("format_values", {}),
        })
    return {
        "schema_version": 3,
        "genome_build": variants[0].genome_build if variants else None,
        "variant_ids": [str(value) for value in variant_ids],
        "sample_calls": sample_calls,
        "source_record_mappings": [
            {
                "variant_id": str(variant_id),
                "source_chromosome": getattr(variant, "original_chromosome", None),
                "source_position": getattr(variant, "original_position", None),
                "source_reference": getattr(variant, "original_reference", None),
                "source_alternate": getattr(variant, "original_alternate", None),
                "source_alt_index": getattr(variant, "original_alt_index", None),
            }
            for variant_id, variant in zip(variant_ids, variants)
            if getattr(variant, "original_position", None) is not None
        ],
    }


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
    organization_id: UUID | None = None,
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
    if (
        organization_id is not None
        and row.organization_id is not None
        and row.organization_id != organization_id
    ):
        raise ResourceConsumptionError(
            "RESOURCE_TENANT_MISMATCH",
            f"Organization-scoped resource {rid} does not belong to the analysis organization.",
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


def _check_routed_artifact_validation_replay(
    metadata: dict,
    *,
    status: str,
    reference_package: dict | None,
    active_reference_package: dict | None,
    reference_profile: dict | None,
) -> bool:
    """Check a replay against prior successful validation provenance.

    Returns whether an earlier successful validation should be retained because
    the current attempt could not rerun validation. A new reference identity or
    source profile must never silently replace the one already recorded.
    """
    if metadata.get("reference_validation_status") != "PASS":
        return False

    current_package = reference_package or active_reference_package
    if current_package is None:
        if status == "PASS":
            raise RuntimeError(
                "A routed artifact cannot be marked reference-validated without a resolved package."
            )
        return status in {"PENDING", "NOT_RUN"}

    prior_identity = (
        metadata.get("reference_package_id"),
        metadata.get("reference_package_version"),
        metadata.get("reference_fasta_sha256"),
    )
    current_identity = (
        current_package.get("resource_id"),
        current_package.get("version"),
        current_package.get("fasta_sha256"),
    )
    if prior_identity != current_identity:
        raise RuntimeError(
            "A previously reference-validated routed artifact cannot be reused with "
            "a different reference package identity."
        )

    if status == "PASS" and reference_profile is not None:
        if metadata.get("source_reference_allele_profile") != reference_profile:
            raise RuntimeError(
                "A previously reference-validated routed artifact produced a different "
                "source allele profile on replay."
            )
    return status in {"PENDING", "NOT_RUN"}


def _put_idempotent_stage_artifact(
    store,
    *,
    artifact_id: UUID,
    db: Session,
    case_id: UUID,
    analysis_id: UUID | None,
    source_path: Path,
    filename: str,
    artifact_type: str,
    media_type: str | None,
    genome_build: str | None,
    metadata: dict | None = None,
    specimen_id: UUID | None = None,
    paired_artifact_id: UUID | None = None,
    validation_status: str = "PENDING",
) -> Artifact:
    """Persist or reuse a deterministic workflow artifact after worker redelivery.

    The same analysis/stage/output receives the same artifact ID. If the DB row
    already exists, verify its immutable content and provenance instead of
    creating a duplicate row or overwriting a different artifact.
    """
    source = Path(source_path)
    if not source.is_file():
        raise FileNotFoundError(f"Artifact source file does not exist: {source}")
    expected_type = artifact_type.value if hasattr(artifact_type, "value") else str(artifact_type)
    expected_metadata = dict(metadata or {})
    existing = db.get(Artifact, artifact_id)
    if existing is not None:
        existing_metadata = dict(existing.metadata_json or {})
        # The recorded command includes worker-local temporary paths. Those can
        # legitimately differ after redelivery, while the scientific resource
        # and normalization provenance must remain identical.
        expected_metadata.pop("normalization_command", None)
        existing_metadata.pop("normalization_command", None)
        routed_validation_keys = {
            "reference_validation_status",
            "reference_validation_reason_code",
            "reference_package_id",
            "reference_package_version",
            "reference_fasta_sha256",
            "source_reference_allele_profile",
        }
        if expected_type in {
            "GVCF_REFERENCE_BLOCKS",
            "UNRESOLVED_GVCF_VARIANTS",
            "STRUCTURAL_VARIANT_RECORDS",
            "SPANNING_DELETION_RECORDS",
            "TELOMERE_COORDINATE_RECORDS",
            "TELOMERE_AFTER_CONTIG_RECORDS",
        }:
            existing_validation = {
                key: existing_metadata.pop(key)
                for key in routed_validation_keys
                if key in existing_metadata
            }
            for key in routed_validation_keys:
                expected_metadata.pop(key, None)
            if existing_validation:
                status = existing_validation.get("reference_validation_status")
                if status not in {
                    "PENDING", "PASS", "FAILED", "NOT_RUN",
                    "NOT_VALIDATED_UNSUPPORTED_COORDINATE",
                }:
                    raise RuntimeError(
                        f"Routed artifact {artifact_id} has invalid reference validation provenance."
                    )
                package_fields = {
                    "reference_package_id",
                    "reference_package_version",
                    "reference_fasta_sha256",
                }
                present_package_fields = package_fields.intersection(existing_validation)
                if present_package_fields and present_package_fields != package_fields:
                    raise RuntimeError(
                        f"Routed artifact {artifact_id} has incomplete reference package provenance."
                    )
                profile = existing_validation.get("source_reference_allele_profile")
                if profile is not None and not isinstance(profile, dict):
                    raise RuntimeError(
                        f"Routed artifact {artifact_id} has invalid reference allele profile provenance."
                    )
        if (
            existing.case_id != case_id
            or existing.analysis_id != analysis_id
            or existing.artifact_type != expected_type
            or existing.filename != Path(filename).name.strip()
            or existing.media_type != media_type
            or existing.genome_build != genome_build
            or existing.specimen_id != specimen_id
            or existing.validation_status != validation_status
            or existing_metadata != expected_metadata
        ):
            raise RuntimeError(
                f"Deterministic artifact identity {artifact_id} is already bound to different workflow provenance."
            )
        source_sha256 = sha256_file(source)
        if existing.sha256 != source_sha256 or existing.size_bytes != source.stat().st_size:
            raise RuntimeError(
                f"Deterministic artifact identity {artifact_id} produced different bytes on replay."
            )
        if not store.exists(existing.storage_uri):
            raise RuntimeError(
                f"Persisted artifact {artifact_id} is missing from its configured storage backend."
            )
        return existing

    return store.put_file(
        db=db,
        case_id=case_id,
        analysis_id=analysis_id,
        source_path=source,
        filename=filename,
        artifact_type=artifact_type,
        media_type=media_type,
        genome_build=genome_build,
        metadata=expected_metadata,
        specimen_id=specimen_id,
        paired_artifact_id=paired_artifact_id,
        validation_status=validation_status,
        artifact_id=artifact_id,
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
