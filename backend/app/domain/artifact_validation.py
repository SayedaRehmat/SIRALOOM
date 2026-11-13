"""Durable worker-side validation for uploaded VCF and TBI/CSI artifacts.

The API persists bytes and a PENDING artifact record. This module is the only
place that classifies an uploaded artifact using BCFtools/HTSlib.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.domain.artifact_integrity import verify_artifact_file
from backend.app.domain.case_intake import case_status_after_vcf_upload
from backend.app.domain.enums import ArtifactType
from backend.app.domain.execution_context import (
    ExecutionEnvironmentAssignmentError,
    persistent_execution_for_case,
)
from backend.app.domain.ingestion import (
    VCFValidationUnavailable,
    normalize_build,
    validate_index,
    validate_specimen_sample_identity,
    validate_vcf,
)
from backend.app.domain.storage_profiles import artifact_store_for_uri
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Artifact, Case, Specimen
from backend.app.infrastructure.db.session import SessionLocal


def _copy_verified_artifact(db: Session, case: Case, artifact: Artifact, destination: Path) -> None:
    store = artifact_store_for_uri(
        db,
        organization_id=case.organization_id,
        storage_uri=artifact.storage_uri,
    )
    if callable(getattr(store, "download_to_file", None)):
        store.download_to_file(
            artifact.storage_uri,
            destination,
            expected_sha256=artifact.sha256,
            expected_size_bytes=artifact.size_bytes,
        )
        verify_artifact_file(destination, sha256=artifact.sha256, size_bytes=artifact.size_bytes)
        return
    source = store.local_path(artifact.storage_uri)
    verify_artifact_file(source, sha256=artifact.sha256, size_bytes=artifact.size_bytes)
    shutil.copyfile(source, destination)
    verify_artifact_file(destination, sha256=artifact.sha256, size_bytes=artifact.size_bytes)


def _validation_payload(result) -> dict:
    return {
        "status": result.status,
        "fileformat": result.fileformat,
        "record_count": result.record_count,
        "sample_count": len(result.sample_names),
        "sample_names": result.sample_names,
        "detected_build": result.detected_build,
        "errors": result.errors,
        "warnings": result.warnings,
        "error_code": result.error_code,
        **(result.metadata or {}),
    }


def _refresh_case_intake(db: Session, case: Case) -> None:
    rows = db.execute(
        select(Artifact.validation_status, Artifact.metadata_json).where(
            Artifact.case_id == case.id,
            Artifact.artifact_type == ArtifactType.VCF,
        )
    ).all()
    has_valid_vcf = any(status == "VALID" for status, _metadata in rows)
    has_pending_vcf = any(status == "PENDING" for status, _metadata in rows)
    if case.status in {
        "DRAFT", "SPECIMEN_REGISTERED", "ARTIFACT_UPLOADED",
        "VALIDATING", "READY_FOR_ANALYSIS", "INVALID",
    } and has_valid_vcf:
        case.status = "READY_FOR_ANALYSIS"
        return
    if case.status in {
        "DRAFT", "SPECIMEN_REGISTERED", "ARTIFACT_UPLOADED",
        "VALIDATING", "READY_FOR_ANALYSIS", "INVALID",
    } and has_pending_vcf:
        case.status = "VALIDATING"
        return
    case.status = case_status_after_vcf_upload(
        case.status,
        has_valid_vcf=has_valid_vcf,
        has_vcf=bool(rows),
        has_site_only_vcf=any(
            status == "VALID_SITE_ONLY"
            or (
                isinstance(metadata, dict)
                and metadata.get("workflow_eligibility") == "SITE_LEVEL_ONLY"
            )
            for status, metadata in rows
        ),
    )


def validate_persisted_artifact(artifact_id: UUID) -> dict:
    """Validate one persisted artifact; database state is authoritative/idempotent."""
    db = SessionLocal()
    try:
        artifact = db.get(Artifact, artifact_id, with_for_update=True)
        if artifact is None:
            return {"artifact_id": str(artifact_id), "status": "NOT_FOUND"}
        if artifact.validation_status != "PENDING":
            return {
                "artifact_id": str(artifact_id),
                "status": artifact.validation_status,
                "idempotent": True,
            }
        case = db.get(Case, artifact.case_id)
        if case is None or case.organization_id is None:
            raise RuntimeError("Artifact case/tenant identity is unavailable for validation.")
        try:
            persistent_execution = persistent_execution_for_case(
                db,
                case=case,
                worker_id=f"artifact-validation:{artifact.id}",
            )
        except ExecutionEnvironmentAssignmentError as exc:
            from backend.app.domain.ingestion import VCFValidationUnavailable
            raise VCFValidationUnavailable(str(exc)) from exc

        metadata = dict(artifact.metadata_json or {})
        ingestion = dict(metadata.get("ingestion") or {})
        kind = ingestion.get("file_kind")
        if kind not in {"VCF", "TBI", "CSI"}:
            raise RuntimeError(f"Unsupported persisted artifact validation kind: {kind!r}")

        scratch_root = Path(settings.worker_scratch_root).expanduser()
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="siraloom-artifact-validation-",
            dir=scratch_root,
        ) as tmp:
            root = Path(tmp)
            artifact_path = root / Path(artifact.filename).name
            _copy_verified_artifact(db, case, artifact, artifact_path)

            if kind == "VCF":
                result = validate_vcf(
                    artifact_path,
                    persistent_execution=persistent_execution,
                    workflow_id=f"vcf-intake:{artifact.id}",
                )
                specimen = db.get(Specimen, artifact.specimen_id) if artifact.specimen_id else None
                if result.sample_names and specimen is None:
                    from backend.app.domain.ingestion import ValidationResult
                    result = ValidationResult(
                        "INVALID", result.file_kind, result.record_count, result.sample_names,
                        result.detected_build,
                        [*result.errors, "A sample-bearing VCF must be linked to a specimen with an explicit VCF sample-name mapping."],
                        result.warnings, result.fileformat, result.metadata, "VCF_SPECIMEN_REQUIRED",
                    )
                elif specimen is not None:
                    result = validate_specimen_sample_identity(
                        result, (specimen.metadata_json or {}).get("vcf_sample_name")
                    )
                requested_build = normalize_build(artifact.genome_build)
                if result.detected_build and result.detected_build != requested_build:
                    from backend.app.domain.ingestion import ValidationResult
                    result = ValidationResult(
                        "INVALID", result.file_kind, result.record_count, result.sample_names,
                        result.detected_build,
                        [*result.errors, f"VCF header indicates {result.detected_build}, but the selected genome build is {requested_build}."],
                        result.warnings, result.fileformat, result.metadata,
                        "VCF_REFERENCE_DECLARATION_MISMATCH",
                    )
                metadata["validation"] = _validation_payload(result)
                if result.status == "VALID" and not result.sample_names:
                    metadata["workflow_eligibility"] = "SITE_LEVEL_ONLY"
                    artifact.validation_status = "VALID_SITE_ONLY"
                elif result.status == "VALID":
                    metadata["workflow_eligibility"] = "SAMPLE_LEVEL"
                    artifact.validation_status = "VALID"
                else:
                    metadata["workflow_eligibility"] = "INELIGIBLE"
                    artifact.validation_status = result.status
                event_type = (
                    "ARTIFACT_VALIDATION_COMPLETED"
                    if result.status == "VALID"
                    else "ARTIFACT_VALIDATION_FAILED"
                )
                validation_status = result.status
            else:
                primary = db.get(Artifact, artifact.paired_artifact_id) if artifact.paired_artifact_id else None
                if primary is None or primary.case_id != artifact.case_id or primary.artifact_type != ArtifactType.VCF:
                    raise RuntimeError("Paired primary VCF is missing or does not belong to this case.")
                primary_path = root / Path(primary.filename).name
                _copy_verified_artifact(db, case, primary, primary_path)
                suffix = ".tbi" if kind == "TBI" else ".csi"
                index_path = Path(str(primary_path) + suffix)
                shutil.copyfile(artifact_path, index_path)
                result = validate_index(
                    index_path,
                    primary.filename,
                    primary_path=primary_path,
                    expected_bcftools_version=settings.bcftools_version,
                    persistent_execution=persistent_execution,
                    workflow_id=f"vcf-index:{artifact.id}",
                )
                metadata["validation"] = {
                    "status": result.status,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    **(result.metadata or {}),
                }
                artifact.validation_status = result.status
                primary_metadata = dict(primary.metadata_json or {})
                primary_metadata["index"] = {
                    "artifact_id": str(artifact.id),
                    "status": result.status,
                    "type": kind,
                    "concordance": (result.metadata or {}).get(
                        "index_concordance", {"status": "NOT_CHECKED"}
                    ),
                }
                primary.metadata_json = primary_metadata
                event_type = (
                    "ARTIFACT_VALIDATION_COMPLETED"
                    if result.status == "VALID"
                    else "ARTIFACT_VALIDATION_FAILED"
                )
                validation_status = result.status

        artifact.metadata_json = metadata
        db.add(artifact)
        db.add(case)
        if kind == "VCF":
            # Lock only after this artifact's validation result is staged, so
            # independent VCF validation can run concurrently. The lock must
            # precede the aggregate status query in _refresh_case_intake().
            case = db.scalar(
                select(Case)
                .where(Case.id == artifact.case_id)
                .with_for_update(key_share=True)
                .execution_options(populate_existing=True)
            )
            if case is None:
                raise RuntimeError("Artifact case disappeared during validation.")
            _refresh_case_intake(db, case)
        AuditService(db).record(
            event_type=event_type,
            case_id=artifact.case_id,
            analysis_id=None,
            actor_type="SYSTEM",
            actor_id="artifact-validation-worker",
            subject_type="ARTIFACT",
            subject_id=str(artifact.id),
            operation="VALIDATE",
            after_state={
                "artifact_validation_status": artifact.validation_status,
                "case_status": case.status,
            },
            reason="Durable artifact intake validation",
            input_artifacts=[{"artifact_id": str(artifact.id), "sha256": artifact.sha256}],
            payload={
                "file_kind": kind,
                "validation": metadata["validation"],
                "toolchain_profile_id": settings.bcftools_profile_id,
                "bcftools_version": settings.bcftools_version,
                "htslib_version": settings.htslib_version,
            },
        )
        db.commit()
        return {
            "artifact_id": str(artifact.id),
            "status": artifact.validation_status,
            "validation_status": validation_status,
        }
    except VCFValidationUnavailable:
        db.rollback()
        raise
    except OSError as exc:
        db.rollback()
        raise VCFValidationUnavailable(
            f"Artifact validation storage or worker scratch I/O is temporarily unavailable: {exc}"
        ) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
