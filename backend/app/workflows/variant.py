from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.adapters.annotation.genebe import GeneBeError, GeneBeProvider
from backend.app.adapters.annotation.genebe_normalizer import normalize_gene_be_variant
from backend.app.adapters.population.gnomad import GnomADGraphQLProvider, GnomADProviderError, PopulationObservationData
from backend.app.config import settings
from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.normalization import NormalizationError, iter_normalized_vcf, normalize_vcf_file
from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid, normalize_build
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.audit.service import AuditService
from backend.app.partition_scheduler import PartitionCapacityError, PartitionScheduler, configure_partition
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
)

WORKFLOW_STEPS = [
    ("validate_input", 1),
    ("normalize", 2),
    ("annotate", 3),
    ("population", 4),
    ("build_evidence", 5),
    ("acmg_assessment", 6),
    ("review", 7),
    ("report", 8),
    ("export_provenance", 9),
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
    db.commit()


def _completed_batch_keys(step: WorkflowStep) -> set[str]:
    batches = (step.metadata_json or {}).get("batches") or {}
    return {k for k, v in batches.items() if (v or {}).get("status") == "SUCCEEDED"}

def _chunk_ranges(length: int, size: int = 250):
    size = max(1, size)
    for start in range(0, length, size):
        yield start, min(length, start + size)


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
        configure_partition(part, "STANDARD")
        db.add(part)
    db.commit()


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
                from backend.app.domain.vcf import parse_vcf
                count = sum(1 for _ in parse_vcf(str(input_path)))
                if count == 0:
                    raise ValueError("VCF contains no variant records")
                validation_step.input_artifacts = [str(input_artifact.id)]
                validation_step.output_artifacts = [str(input_artifact.id)]
                mark_step(db, validation_step, StepStatus.SUCCEEDED, metadata={"variant_count": count, "validation": "PASS"})
                audit.record(
                    event_type="ARTIFACT_VALIDATED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SYSTEM",
                    actor_id="vcf-validator",
                    subject_type="ARTIFACT",
                    subject_id=str(input_artifact.id),
                    input_artifacts=[{"artifact_id": str(input_artifact.id), "sha256": input_artifact.sha256}],
                )
                db.commit()
            except Exception as exc:
                mark_step(db, validation_step, StepStatus.FAILED, error_code="VCF_INVALID", error_message=str(exc))
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
        partition_size = min(max(1, int(analysis.configuration.get("partition_size", 500) or 500)), 1000)

        if normalization_step.status != StepStatus.SUCCEEDED:
            mark_step(db, normalization_step, StepStatus.RUNNING)
            reference_fasta = analysis.configuration.get("reference_fasta") or settings.reference_fasta
            reference_fai = analysis.configuration.get("reference_fai") or settings.reference_fai
            if not reference_fasta:
                mark_step(db, normalization_step, StepStatus.BLOCKED, error_code="REFERENCE_NOT_CONFIGURED", error_message="A validated reference FASTA is required for reference-aware normalization.")
                analysis.status = AnalysisStatus.BLOCKED
                db.commit()
                audit.record(event_type="WORKFLOW_BLOCKED", case_id=analysis.case_id, analysis_id=analysis.id, actor_type="SYSTEM", actor_id="normalization", reason="Reference FASTA is not configured")
                db.commit()
                return

            temp_path: Path | None = None
            try:
                suffix = ".vcf.gz" if input_path.name.endswith(".gz") else ".vcf"
                with NamedTemporaryFile(prefix="siraloom-normalized-", suffix=suffix, delete=False) as temp:
                    temp_path = Path(temp.name)
                from backend.app.domain.reference import FastaReference
                with FastaReference(reference_fasta, reference_fai) as reference:
                    result = normalize_vcf_file(input_path, temp_path, genome_build=reference_build, reference=reference, collect_variants=False)
                normalized_artifact = artifacts.put_file(
                    db=db, case_id=analysis.case_id, analysis_id=analysis.id, source_path=temp_path,
                    filename="normalized.vcf.gz" if temp_path.suffix == ".gz" else "normalized.vcf",
                    artifact_type="NORMALIZED_VCF", media_type="application/gzip" if temp_path.suffix == ".gz" else "text/vcf",
                    genome_build=reference_build, metadata={"normalization_version": "1.0", "record_count": result["record_count"], "changed_count": result["changed_count"], "streaming": True},
                )
                normalization_step.input_artifacts = [str(input_artifact.id)]
                normalization_step.output_artifacts = [str(normalized_artifact.id)]
                mark_step(db, normalization_step, StepStatus.SUCCEEDED, metadata={"normalization": "REFERENCE_AWARE", "record_count": result["record_count"], "changed_count": result["changed_count"], "streaming": True, "partition_size": partition_size})
                audit.record(event_type="NORMALIZATION_COMPLETED", case_id=analysis.case_id, analysis_id=analysis.id, actor_type="SYSTEM", actor_id="siraloom-normalizer", input_artifacts=[{"artifact_id": str(input_artifact.id), "sha256": input_artifact.sha256}], output_artifacts=[{"artifact_id": str(normalized_artifact.id), "sha256": normalized_artifact.sha256}], workflow={"step": "normalize", "version": "1.1"}, payload={"record_count": result["record_count"], "changed_count": result["changed_count"], "streaming": True})
                db.commit()
            except NormalizationError as exc:
                mark_step(db, normalization_step, StepStatus.FAILED, error_code="NORMALIZATION_FAILED", error_message=str(exc))
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

        # 3. GeneBe annotation provider (development/research path).
        # Each batch is durably checkpointed in workflow_steps.metadata_json.
        # Annotation rows are committed before the batch checkpoint is marked
        # successful, so a worker crash can safely resume by inspecting persisted rows.
        annotation_step = _step(db, analysis.id, "annotate")
        provider = GeneBeProvider()
        if annotation_step.status != StepStatus.SUCCEEDED:
            mark_step(db, annotation_step, StepStatus.RUNNING)
            try:
                if not settings.genebe_enabled:
                    mark_step(
                        db,
                        annotation_step,
                        StepStatus.BLOCKED,
                        error_code="ANNOTATION_PROVIDER_DISABLED",
                        error_message="GeneBe development provider is disabled and no alternative Phase 1 provider is configured.",
                    )
                    analysis.status = AnalysisStatus.BLOCKED
                    db.commit()
                    audit.record(
                        event_type="WORKFLOW_BLOCKED",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SYSTEM",
                        actor_id="annotation",
                        reason="No Phase 1 annotation provider enabled",
                    )
                    db.commit()
                    return

                batch_limit = min(max(1, settings.genebe_max_batch), 1000)
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
                    variant_ids = {
                        canonical_key(v.genome_build, v.chromosome, v.position, v.reference, v.alternate): stable_variant_uuid(canonical_key(v.genome_build, v.chromosome, v.position, v.reference, v.alternate))
                        for v in batch
                    }
                    key = _batch_key(start, end)
                    existing_rows = db.scalars(
                        select(Annotation).where(
                            Annotation.analysis_id == analysis.id,
                            Annotation.provider_name == provider.provider_id,
                            Annotation.variant_id.in_(list(variant_ids.values())),
                        )
                    ).all()
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
                            scheduler.succeed(partition.id, worker_id, metadata={"provider": provider.provider_id, "recovered_existing_rows": True})
                        continue
                    if all(k in existing_keys for k in variant_ids):
                        _save_batch_checkpoint(
                            db, annotation_step, start, end, status="SUCCEEDED",
                            attempt=int(checkpoint.get("attempt", 0)),
                            metadata={"provider": provider.provider_id, "recovered_existing_rows": True, "variant_count": len(batch)},
                        )
                        if partition.status == "RUNNING" and partition.lease_owner == worker_id:
                            scheduler.succeed(partition.id, worker_id, metadata={"provider": provider.provider_id, "recovered_existing_rows": True})
                        continue

                    attempt = int(checkpoint.get("attempt", 0)) + 1
                    _save_batch_checkpoint(
                        db, annotation_step, start, end, status="RUNNING", attempt=attempt,
                        metadata={"provider": provider.provider_id, "variant_count": len(batch)},
                    )
                    try:
                        scheduler.heartbeat(partition.id, worker_id)
                        payloads = provider.annotate(batch, {"genome": genome})
                        scheduler.heartbeat(partition.id, worker_id)
                    except GeneBeError as exc:
                        if exc.retryable:
                            if partition.status == "RUNNING" and partition.lease_owner == worker_id:
                                scheduler.fail(partition.id, worker_id, error_code="ANNOTATION_PROVIDER_TRANSIENT", error_message=str(exc))
                            _save_batch_checkpoint(
                                db, annotation_step, start, end, status="RETRYING", attempt=attempt,
                                metadata={"error": str(exc)},
                            )
                            mark_step(db, annotation_step, StepStatus.RETRYING, error_code="ANNOTATION_PROVIDER_TRANSIENT", error_message=str(exc))
                            raise TransientWorkflowError(str(exc), countdown=min(60, 5 * attempt)) from exc
                        if partition.status == "RUNNING" and partition.lease_owner == worker_id:
                            scheduler.fail(partition.id, worker_id, error_code="ANNOTATION_PROVIDER_ERROR", error_message=str(exc))
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
                        normalized = normalize_gene_be_variant(payload)
                        db.add(
                            Annotation(
                                id=__import__("uuid").uuid4(),
                                variant_id=row_id,
                                analysis_id=analysis.id,
                                provider_name=provider.provider_id,
                                provider_version=provider.provider_version,
                                resource_name="GeneBe",
                                resource_version=None,
                                payload={"raw": payload, "normalized": normalized},
                            )
                        )
                        new_count += 1
                    db.commit()
                    _save_batch_checkpoint(
                        db, annotation_step, start, end, status="SUCCEEDED", attempt=attempt,
                        metadata={"provider": provider.provider_id, "new_annotation_rows": new_count, "returned_rows": len(payloads_by_key)},
                    )
                    if partition.status == "RUNNING" and partition.lease_owner == worker_id:
                        scheduler.succeed(partition.id, worker_id, metadata={"provider": provider.provider_id, "variant_count": len(batch)})
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

        # 4. Population observations: GeneBe-derived global + optional direct gnomAD MID/global.
        population_step = _step(db, analysis.id, "population")
        if population_step.status != StepStatus.SUCCEEDED:
            mark_step(db, population_step, StepStatus.RUNNING)
            try:
                geneBe_resource = _get_or_create_resource(
                    db,
                    name="gnomAD total via GeneBe",
                    provider="GeneBe",
                    resource_type="POPULATION_FREQUENCY",
                    version=settings.genebe_gnomad_resource_version,
                    genome_build=normalize_build(analysis.reference_build),
                    access_method="API_PROVIDER_DERIVED",
                    status="AVAILABLE",
                    population_definition={"level": "GLOBAL", "code": "GLOBAL", "label": "Global"},
                )

                created = 0
                annotation_count = db.scalar(select(func.count(Annotation.id)).where(Annotation.analysis_id == analysis.id, Annotation.provider_name == "genebe")) or 0
                pop_batch_size = int(analysis.configuration.get("population_batch_size", partition_size) or partition_size)
                for pop_start, pop_end in _chunk_ranges(annotation_count, pop_batch_size):
                    annotations = db.scalars(select(Annotation).where(Annotation.analysis_id == analysis.id, Annotation.provider_name == "genebe").order_by(Annotation.created_at, Annotation.id).offset(pop_start).limit(pop_end - pop_start)).all()
                    for ann in annotations:
                        payload = ann.payload.get("normalized", {})
                        pop = payload.get("population", {})
                        if pop.get("reference_population_af") is None and pop.get("reference_population_ac") is None:
                            continue
                        existing = db.scalar(select(PopulationObservation).where(PopulationObservation.analysis_id == analysis.id, PopulationObservation.variant_id == ann.variant_id, PopulationObservation.resource_id == geneBe_resource.id, PopulationObservation.population_code == "GLOBAL"))
                        if existing:
                            continue
                        ac = _safe_int(pop.get("reference_population_ac"))
                        hom = _safe_int(pop.get("reference_population_hom"))
                        af = _safe_float(pop.get("reference_population_af"))
                        db.add(PopulationObservation(id=__import__("uuid").uuid4(), analysis_id=analysis.id, variant_id=ann.variant_id, resource_id=geneBe_resource.id, population_level="GLOBAL", population_code="GLOBAL", population_label="Global", allele_count=ac, allele_number=None, allele_frequency=af, homozygote_count=hom, availability="AVAILABLE", quality_status="PROVIDER_DERIVED"))
                        created += 1
                    db.commit()

                direct_count = 0
                if settings.gnomad_enabled:
                    if normalize_build(analysis.reference_build) != "GRCh38":
                        raise GnomADProviderError("Configured gnomAD v4 GraphQL dataset is supported here only for GRCh38")
                    gnomad = GnomADGraphQLProvider(
                        endpoint=settings.gnomad_graphql_endpoint,
                        dataset_id=settings.gnomad_dataset_id,
                        delay_seconds=settings.gnomad_graphql_delay_seconds,
                    )
                    resource = _get_or_create_resource(
                        db,
                        name="gnomAD GraphQL",
                        provider="gnomAD",
                        resource_type="POPULATION_FREQUENCY",
                        version=settings.gnomad_dataset_id,
                        genome_build=normalize_build(analysis.reference_build),
                        access_method="API",
                        status="AVAILABLE",
                        population_definition={"level": "ANCESTRY", "code": "MID", "label": "Middle Eastern"},
                    )
                    for variant in iter_normalized_vcf(normalized_path, reference_build):
                        obs_list = gnomad.query_variant(variant)
                        row = db.get(Variant, stable_variant_uuid(canonical_key(variant.genome_build, variant.chromosome, variant.position, variant.reference, variant.alternate)))
                        if row is None:
                            raise RuntimeError("Canonical variant row missing during population processing")
                        for obs in obs_list:
                            if obs.population_code != "MID":
                                continue
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
                                )
                            )
                            direct_count += 1
                    db.commit()

                mark_step(
                    db,
                    population_step,
                    StepStatus.SUCCEEDED,
                    metadata={"gene_be_global_observations": created, "direct_gnomad_observations": direct_count},
                )
                audit.record(
                    event_type="POPULATION_COMPLETED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id="population-engine",
                    payload={"gene_be_global_observations": created, "direct_gnomad_observations": direct_count},
                )
                db.commit()
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
                        for record in records:
                            fp = evidence_fingerprint(
                                variant_id=record.variant_id, analysis_id=analysis.id,
                                evidence_type=record.evidence_type, statement=record.statement,
                                direction=record.direction, source_name=record.source_name,
                                source_version=record.source_version, observation_ids=record.observation_ids,
                                payload=record.payload,
                            )
                            exists = db.scalar(select(Evidence).where(Evidence.analysis_id == analysis.id, Evidence.evidence_fingerprint == fp))
                            if exists:
                                continue
                            db.add(Evidence(
                                id=record.evidence_id, variant_id=record.variant_id, analysis_id=analysis.id,
                                evidence_type=record.evidence_type, statement=record.statement, direction=record.direction,
                                source_name=record.source_name, source_version=record.source_version, source_record_id=None,
                                observation_ids=[str(x) for x in record.observation_ids], payload=record.payload,
                                created_by_type="SYSTEM", created_by_id=engine.engine_id, evidence_fingerprint=fp,
                            ))
                            created += 1; batch_created += 1
                    db.commit()
                    _save_batch_checkpoint(db, evidence_step, start_i, end_i, status="SUCCEEDED", attempt=attempt, metadata={"created_evidence": batch_created})
                db.commit()
                evidence_step.input_artifacts = [str(normalized_artifact.id)] if normalized_artifact else []
                mark_step(db, evidence_step, StepStatus.SUCCEEDED, metadata={
                    "engine": engine.engine_id,
                    "engine_version": engine.engine_version,
                    "created_evidence": created,
                })
                audit.record(
                    event_type="EVIDENCE_COMPLETED",
                    case_id=analysis.case_id,
                    analysis_id=analysis.id,
                    actor_type="SERVICE",
                    actor_id=engine.engine_id,
                    payload={"created_evidence": created, "engine_version": engine.engine_version},
                )
                db.commit()
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
                    batch_blocked = 0
                    for ann in rows[start_i:end_i]:
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
                            assessment_service.persist(db, analysis=analysis, variant=variant_row, result=result)
                            assessed += 1; batch_assessed += 1
                            if result.status == "PROPOSED": proposed_variants += 1; batch_proposed += 1
                        else:
                            blocked_variants += 1; batch_blocked += 1
                    db.commit()
                    _save_batch_checkpoint(db, acmg_step, start_i, end_i, status="SUCCEEDED", attempt=attempt, metadata={"assessed": batch_assessed, "proposed": batch_proposed, "blocked": batch_blocked})

                if assessed == 0:
                    mark_step(
                        db, acmg_step, StepStatus.BLOCKED,
                        error_code="NO_AUTOMATABLE_CLINGEN_CONTEXT",
                        error_message=(
                            "No variant received a validated, applicable ClinGen specification with "
                            "supported structured criterion configuration. Human/configuration review is required."
                        ),
                        metadata={"disease_context_present": bool(disease), "blocked_variants": blocked_variants},
                    )
                    analysis.status = AnalysisStatus.BLOCKED
                    db.commit()
                    audit.record(
                        event_type="ACMG_ASSESSMENT_BLOCKED",
                        case_id=analysis.case_id,
                        analysis_id=analysis.id,
                        actor_type="SERVICE",
                        actor_id="siraloom-acmg-specification-engine",
                        reason="No safely automatable validated ClinGen specification/context",
                        payload={"assessed": assessed, "blocked_variants": blocked_variants},
                    )
                    db.commit()
                    return

                status = StepStatus.SUCCEEDED if proposed_variants == assessed else StepStatus.SUCCEEDED
                mark_step(db, acmg_step, status, metadata={
                    "assessed_variants": assessed,
                    "proposed_variants": proposed_variants,
                    "blocked_variants": blocked_variants,
                    "disease_context_present": bool(disease),
                })
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

        # Computational interpretation is complete; the case now requires human review.
        # Review/report/provenance are durable downstream states, not workflow failures.
        review_step = _step(db, analysis.id, "review")
        if review_step.status == StepStatus.PENDING:
            mark_step(
                db, review_step, StepStatus.REQUIRES_REVIEW,
                metadata={"reason": "Automated assessment completed; qualified human review required."},
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
            payload={"status": "REQUIRES_REVIEW"},
        )
        db.commit()
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


def _get_or_create_resource(
    db: Session,
    *,
    name: str,
    provider: str,
    resource_type: str,
    version: str,
    genome_build: str,
    access_method: str,
    status: str,
    population_definition: dict,
) -> Resource:
    row = db.scalar(
        select(Resource).where(
            Resource.name == name,
            Resource.provider == provider,
            Resource.version == version,
            Resource.genome_build == genome_build,
        )
    )
    if row:
        return row
    from uuid import uuid4
    row = Resource(
        id=uuid4(),
        name=name,
        provider=provider,
        resource_type=resource_type,
        version=version,
        genome_build=genome_build,
        access_method=access_method,
        license_text=None,
        checksum=None,
        location=None,
        status=status,
        population_definition=population_definition,
        metadata_json={},
    )
    db.add(row)
    db.flush()
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
