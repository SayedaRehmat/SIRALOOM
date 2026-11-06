from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from backend.app.application.entitlements import effective_max_upload_bytes
from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    get_accessible_artifact,
    require_case_permission,
    require_role,
)
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.config import settings
from backend.app.domain.artifact_integrity import (
    ArtifactIntegrityError,
    stage_verified_cloud_artifact,
    verify_artifact_file,
)
from backend.app.domain.case_intake import case_status_after_vcf_upload
from backend.app.domain.enums import ArtifactType
from backend.app.domain.ingestion import classify_filename, normalize_build
from backend.app.domain.storage_capacity import preflight_upload_capacity
from backend.app.domain.upload_idempotency import (
    idempotency_key_sha256,
    upload_request_fingerprint,
)
from backend.app.domain.storage_profiles import (
    StorageProfileError,
    artifact_storage_target_for_organization,
    artifact_store_for_organization,
    artifact_store_for_uri,
)
from backend.app.infrastructure.artifacts.compensation import compensate_uncommitted_artifact
from backend.app.infrastructure.artifacts.upload_intents import (
    UploadIdempotencyConflict,
    reserve_upload_intent,
)
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Artifact, Case, Specimen
from backend.app.infrastructure.db.session import SessionLocal, get_db

router = APIRouter(tags=["artifacts"])
MAX_BYTES = settings.max_artifact_upload_bytes


def _compensate_uncommitted_artifact(db: Session, store, artifact_id: UUID, storage_uri: str) -> None:
    """Delete stored bytes only when a fresh DB read proves the commit did not land."""
    compensate_uncommitted_artifact(
        db,
        store,
        artifact_id,
        storage_uri,
        verification_session_factory=SessionLocal,
    )


def _artifact_upload_response(artifact: Artifact, case: Case) -> dict:
    metadata = artifact.metadata_json or {}
    ingestion = metadata.get("ingestion") or {}
    return {
        "artifact_id": str(artifact.id),
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "artifact_type": artifact.artifact_type,
        "validation_status": artifact.validation_status,
        "case_status": case.status,
        "genome_build": artifact.genome_build,
        "specimen_id": str(artifact.specimen_id) if artifact.specimen_id else None,
        "paired_artifact_id": str(artifact.paired_artifact_id) if artifact.paired_artifact_id else None,
        "validation": metadata.get("validation") or {},
        "workflow_eligibility": metadata.get("workflow_eligibility"),
        "capacity_preflight": ingestion.get("capacity_preflight"),
    }


def _artifact_matches_upload_intent(
    artifact: Artifact, *, request_fingerprint: str
) -> bool:
    ingestion = (artifact.metadata_json or {}).get("ingestion") or {}
    return ingestion.get("upload_request_fingerprint") == request_fingerprint


def _store(db: Session, organization_id: UUID):
    try:
        return artifact_store_for_organization(db, organization_id=organization_id)
    except StorageProfileError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _safe_filename(filename: str) -> str:
    return Path(filename).name


def _refresh_case_vcf_intake_status(db: Session, case_id: UUID) -> tuple[Case, str]:
    """Recompute intake state under a case-row lock after a primary VCF insert."""
    case = db.scalar(
        select(Case)
        .where(Case.id == case_id)
        # PostgreSQL artifacts already hold a KEY SHARE lock on their parent
        # case through the foreign key. NO KEY UPDATE still serializes status
        # writers, while avoiding an UPDATE/KEY SHARE lock-upgrade deadlock
        # when two uploads have both inserted their artifact rows.
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    before_status = case.status
    vcf_rows = db.execute(
        select(Artifact.validation_status, Artifact.metadata_json).where(
            Artifact.case_id == case_id,
            Artifact.artifact_type == ArtifactType.VCF,
        )
    ).all()
    has_valid_vcf = any(status == "VALID" for status, _metadata in vcf_rows)
    has_pending_vcf = any(status == "PENDING" for status, _metadata in vcf_rows)
    if case.status in {
        "DRAFT", "SPECIMEN_REGISTERED", "ARTIFACT_UPLOADED",
        "VALIDATING", "READY_FOR_ANALYSIS", "INVALID",
    } and has_valid_vcf:
        case.status = "READY_FOR_ANALYSIS"
    elif case.status in {
        "DRAFT", "SPECIMEN_REGISTERED", "ARTIFACT_UPLOADED",
        "VALIDATING", "READY_FOR_ANALYSIS", "INVALID",
    } and has_pending_vcf:
        case.status = "VALIDATING"
    else:
        case.status = case_status_after_vcf_upload(
            case.status,
            has_valid_vcf=has_valid_vcf,
            has_vcf=bool(vcf_rows),
            has_site_only_vcf=any(
                status == "VALID_SITE_ONLY"
                or (
                    isinstance(metadata, dict)
                    and metadata.get("workflow_eligibility") == "SITE_LEVEL_ONLY"
                )
                for status, metadata in vcf_rows
            ),
        )
    return case, before_status


@router.get("/cases/{case_id}/artifacts")
def list_case_artifacts(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_permission(case, principal, db, "read")
    rows = db.scalars(select(Artifact).where(Artifact.case_id == case_id).order_by(Artifact.created_at.desc())).all()
    for artifact in rows:
        # Apply the same ownership and report-lineage checks used by downloads
        # before exposing artifact identifiers or hashes in the case dossier.
        get_accessible_artifact(artifact.id, db=db, principal=principal)
    return [
        {
            "artifact_id": str(a.id), "filename": a.filename, "artifact_type": a.artifact_type,
            "size_bytes": a.size_bytes, "sha256": a.sha256, "genome_build": a.genome_build,
            "specimen_id": str(a.specimen_id) if a.specimen_id else None,
            "paired_artifact_id": str(a.paired_artifact_id) if a.paired_artifact_id else None,
            "validation_status": a.validation_status, "metadata": a.metadata_json or {},
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.post("/cases/{case_id}/artifacts", status_code=201)
async def upload_artifact(
    case_id: UUID,
    response: Response,
    file: UploadFile = File(...),
    specimen_id: UUID | None = Form(default=None),
    genome_build: str | None = Form(default=None),
    paired_artifact_id: UUID | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    try:
        key_sha256 = idempotency_key_sha256(idempotency_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_IDEMPOTENCY_KEY", "message": str(exc)},
        ) from exc
    max_bytes = effective_max_upload_bytes(db, principal.organization_id, MAX_BYTES)

    filename = _safe_filename(file.filename or "")
    kind = classify_filename(filename)
    if kind == "UNSUPPORTED":
        raise HTTPException(status_code=400, detail="Unsupported input. Use .vcf, .vcf.gz, .vcf.bgz, .tbi, or .csi.")
    if kind in {"TBI", "CSI"} and paired_artifact_id is None:
        raise HTTPException(status_code=400, detail="An index file must be uploaded with paired_artifact_id referencing its primary VCF artifact.")

    primary = None
    if paired_artifact_id:
        primary = db.get(Artifact, paired_artifact_id)
        if not primary or primary.case_id != case_id:
            raise HTTPException(status_code=404, detail="Primary artifact not found in this case")
        if primary.artifact_type != ArtifactType.VCF:
            raise HTTPException(status_code=400, detail="An index can only be associated with a primary VCF artifact.")
        if not primary.filename.lower().endswith((".vcf", ".vcf.gz", ".vcf.bgz")):
            raise HTTPException(status_code=400, detail="The paired artifact is not a supported VCF input.")
        if specimen_id and primary.specimen_id and specimen_id != primary.specimen_id:
            raise HTTPException(status_code=400, detail="Index specimen does not match the primary VCF specimen.")
        specimen_id = primary.specimen_id
        genome_build = primary.genome_build

    specimen = None
    if specimen_id:
        specimen = db.get(Specimen, specimen_id)
        if not specimen or specimen.case_id != case_id:
            raise HTTPException(status_code=404, detail="Specimen not found in this case")

    requested_build = normalize_build(genome_build)
    if kind == "VCF" and requested_build not in {"GRCh37", "GRCh38"}:
        raise HTTPException(status_code=400, detail="Select genome_build explicitly as GRCh37 or GRCh38; SIRALOOM will not silently infer it.")

    try:
        file.file.seek(0, 2)
        incoming_size = int(file.file.tell())
        await file.seek(0)
    except Exception:
        incoming_size = int(file.size or 0)
        await file.seek(0)
    if incoming_size <= 0:
        await file.close()
        raise HTTPException(status_code=400, detail="The uploaded artifact is empty.")
    if incoming_size > max_bytes:
        await file.close()
        raise HTTPException(status_code=413, detail=f"Artifact exceeds maximum allowed size of {max_bytes} bytes")
    try:
        storage_backend, _target_id, storage_target = artifact_storage_target_for_organization(
            db, organization_id=case.organization_id
        )
    except StorageProfileError as exc:
        await file.close()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    capacity_preflight = preflight_upload_capacity(
        incoming_size,
        artifact_root=(storage_target if storage_backend == "LOCAL_FILESYSTEM" else None),
        artifact_backend_type=storage_backend,
    )
    if capacity_preflight.get("status") == "BLOCKED":
        await file.close()
        raise HTTPException(
            status_code=507,
            detail={
                "message": "Upload blocked by configured storage capacity preflight.",
                "capacity_preflight": capacity_preflight,
            },
        )

    try:
        staging_root = Path(settings.worker_scratch_root).expanduser()
        staging_root.mkdir(parents=True, exist_ok=True)
        staging_directory = tempfile.TemporaryDirectory(
            prefix="siraloom-ingest-", dir=staging_root
        )
    except OSError as exc:
        await file.close()
        raise HTTPException(
            status_code=507,
            detail={
                "code": "UPLOAD_STAGING_UNAVAILABLE",
                "message": "Configured upload staging storage is unavailable.",
            },
        ) from exc

    with staging_directory as tmp:
        staged = Path(tmp) / filename
        digest_size = 0
        try:
            with staged.open("wb") as out:
                while chunk := await file.read(8 * 1024 * 1024):
                    digest_size += len(chunk)
                    if digest_size > max_bytes:
                        raise HTTPException(status_code=413, detail=f"Artifact exceeds maximum allowed size of {max_bytes} bytes")
                    out.write(chunk)
        except OSError as exc:
            raise HTTPException(
                status_code=507,
                detail={
                    "code": "UPLOAD_STAGING_UNAVAILABLE",
                    "message": "Configured upload staging storage is unavailable.",
                },
            ) from exc
        finally:
            await file.close()

        if digest_size == 0:
            raise HTTPException(status_code=400, detail="The uploaded artifact is empty.")

        if kind == "VCF":
            artifact_type = ArtifactType.VCF
            build_for_artifact = requested_build
            validation_metadata = {
                "validation": {
                    "status": "PENDING",
                    "errors": [],
                    "warnings": [],
                    "message": "Persisted; awaiting isolated worker validation.",
                },
                "workflow_eligibility": "PENDING_VALIDATION",
                "ingestion": {
                    "file_kind": "VCF",
                    "original_filename": filename,
                    "capacity_preflight": capacity_preflight,
                },
            }
        else:
            if primary is None:
                raise HTTPException(status_code=400, detail="A primary VCF is required for index validation.")
            if primary.validation_status not in {"VALID", "VALID_SITE_ONLY"}:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "PRIMARY_VCF_NOT_VALIDATED",
                        "message": "The paired primary VCF must finish validation before its index can be uploaded.",
                        "retryable": True,
                    },
                )
            artifact_type = ArtifactType.VCF_INDEX_TBI if kind == "TBI" else ArtifactType.VCF_INDEX_CSI
            build_for_artifact = primary.genome_build
            validation_metadata = {
                "validation": {
                    "status": "PENDING",
                    "errors": [],
                    "warnings": [],
                    "message": "Persisted; awaiting isolated worker validation.",
                },
                "ingestion": {
                    "file_kind": kind,
                    "paired_primary_artifact_id": str(primary.id),
                    "capacity_preflight": capacity_preflight,
                },
            }
        artifact_validation_status = "PENDING"

        upload_intent = None
        request_fingerprint = None
        if key_sha256 is not None:
            with staged.open("rb") as source_handle:
                content_sha256 = hashlib.file_digest(source_handle, "sha256").hexdigest()
            request_fingerprint = upload_request_fingerprint(
                content_sha256=content_sha256,
                size_bytes=digest_size,
                filename=filename,
                artifact_type=(artifact_type.value if isinstance(artifact_type, ArtifactType) else str(artifact_type)),
                media_type=file.content_type,
                genome_build=build_for_artifact,
                specimen_id=specimen_id,
                paired_artifact_id=paired_artifact_id,
            )
            try:
                upload_intent, _created = reserve_upload_intent(
                    db,
                    organization_id=principal.organization_id,
                    case_id=case_id,
                    key_sha256=key_sha256,
                    request_fingerprint=request_fingerprint,
                )
            except UploadIdempotencyConflict as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "IDEMPOTENCY_KEY_REUSED",
                        "message": str(exc),
                    },
                ) from exc

            existing_artifact = db.get(Artifact, upload_intent.artifact_id)
            if existing_artifact is not None:
                if not _artifact_matches_upload_intent(
                    existing_artifact, request_fingerprint=request_fingerprint
                ):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "IDEMPOTENCY_ARTIFACT_MISMATCH",
                            "message": "The reserved artifact identity does not match this upload request.",
                        },
                    )
                if upload_intent.status != "COMMITTED":
                    upload_intent.status = "COMMITTED"
                    db.commit()
                db.refresh(case)
                response.status_code = 200
                return _artifact_upload_response(existing_artifact, case)

            if upload_intent.status == "COMMITTED":
                upload_intent.status = "RECOVERY_REQUIRED"
                db.commit()
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "UPLOAD_RECOVERY_REQUIRED",
                        "message": "The committed upload reservation has no matching artifact row; administrator reconciliation is required.",
                        "retryable": False,
                    },
                )

            if upload_intent.status == "RECOVERY_REQUIRED":
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "UPLOAD_RECOVERY_REQUIRED",
                        "message": "The prior upload reservation requires laboratory administrator reconciliation.",
                        "retryable": False,
                    },
                )
            validation_metadata["ingestion"]["upload_intent_id"] = str(upload_intent.id)
            validation_metadata["ingestion"]["upload_request_fingerprint"] = request_fingerprint

        store = _store(db, principal.organization_id)
        try:
            artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=None,
                source_path=staged,
                filename=filename,
                artifact_type=artifact_type,
                media_type=file.content_type,
                genome_build=build_for_artifact,
                metadata=validation_metadata,
                specimen_id=specimen_id,
                paired_artifact_id=paired_artifact_id,
                validation_status=artifact_validation_status,
                artifact_id=upload_intent.artifact_id if upload_intent is not None else None,
            )
        except Exception as exc:
            if upload_intent is None:
                raise
            if not isinstance(exc, (IntegrityError, FileExistsError)):
                raise
            db.rollback()
            existing_artifact = db.get(Artifact, upload_intent.artifact_id)
            if existing_artifact is None:
                if isinstance(exc, IntegrityError):
                    raise
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "IDEMPOTENT_UPLOAD_CONFLICT",
                        "message": "The reserved storage identity already contains different or unverifiable bytes.",
                    },
                ) from exc
            if not _artifact_matches_upload_intent(
                existing_artifact, request_fingerprint=request_fingerprint
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "IDEMPOTENT_UPLOAD_CONFLICT",
                        "message": "The durable artifact does not match the reserved upload request.",
                    },
                ) from exc
            db.refresh(case)
            response.status_code = 200
            return _artifact_upload_response(existing_artifact, case)

        try:
            from backend.app.domain.toolchain_profiles import resolve_registered_toolchain_profile
            from backend.app.infrastructure.db.models import ArtifactValidationDispatch

            profile = resolve_registered_toolchain_profile(settings.bcftools_profile_id)
            dispatch = ArtifactValidationDispatch(
                id=UUID(str(artifact.id)),
                artifact_id=artifact.id,
                organization_id=case.organization_id,
                case_id=case_id,
                status="PENDING",
                toolchain_profile_id=str(profile["id"]),
                toolchain_bcftools_version=str(profile["bcftools_version"]),
                toolchain_htslib_version=str(profile["htslib_version"]),
                toolchain_queue=str(profile["worker_queue"]),
                toolchain_snapshot={
                    "profile_id": profile["id"],
                    "bcftools_version": profile["bcftools_version"],
                    "htslib_version": profile["htslib_version"],
                    "platform": profile["platform"],
                    "worker_queue": profile["worker_queue"],
                    "lock_file": profile["lock_file"],
                    "lock_sha256": profile["lock_sha256"],
                    "qualification_scope": profile.get("qualification_scope"),
                },
            )
            db.add(dispatch)

            before_status = case.status
            if kind == "VCF":
                case, before_status = _refresh_case_vcf_intake_status(db, case_id)

            AuditService(db).record(
                event_type="ARTIFACT_VALIDATION_QUEUED",
                case_id=case_id,
                analysis_id=None,
                actor_type="HUMAN",
                actor_id=str(principal.user_id),
                subject_type="ARTIFACT",
                subject_id=str(artifact.id),
                operation="QUEUE_VALIDATION",
                before_state={"case_status": before_status},
                after_state={"case_status": case.status, "validation_status": "PENDING"},
                reason="Artifact bytes durably stored; scientific validation dispatched asynchronously.",
                input_artifacts=[{"artifact_id": str(artifact.id), "sha256": artifact.sha256}],
                payload={
                    "filename": filename,
                    "file_kind": kind,
                    "capacity_preflight": capacity_preflight,
                    "toolchain_profile_id": profile["id"],
                    "toolchain_bcftools_version": profile["bcftools_version"],
                    "toolchain_htslib_version": profile["htslib_version"],
                },
            )
            if upload_intent is not None:
                upload_intent.status = "COMMITTED"
            db.commit()
        except Exception:
            _compensate_uncommitted_artifact(db, store, artifact.id, artifact.storage_uri)
            raise

        return _artifact_upload_response(artifact, case)


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        artifact_uuid = UUID(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid artifact_id") from exc
    artifact = get_accessible_artifact(artifact_uuid, db, principal)
    try:
        store = artifact_store_for_uri(
            db,
            organization_id=principal.organization_id,
            storage_uri=artifact.storage_uri,
        )
    except StorageProfileError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if artifact.storage_uri.startswith("gs://"):
        if store.uri_for_artifact(
            case_id=artifact.case_id,
            artifact_id=artifact.id,
            filename=artifact.filename,
        ) != artifact.storage_uri:
            raise HTTPException(status_code=404, detail="Artifact not found")
        try:
            path = stage_verified_cloud_artifact(
                store,
                artifact,
                prefix="siraloom-artifact-download-",
            )
        except ArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="Artifact is unavailable or failed integrity verification.",
            ) from exc
        return FileResponse(
            path,
            media_type=artifact.media_type or "application/octet-stream",
            filename=Path(artifact.filename).name,
            headers={"X-Content-Type-Options": "nosniff"},
            background=BackgroundTask(path.unlink, missing_ok=True),
        )

    # The URI selects the historical backend; the active profile governs new
    # writes. Canonical identity, root containment and checksum are still
    # verified before bytes are returned.
    if store.uri_for_artifact(
        case_id=artifact.case_id,
        artifact_id=artifact.id,
        filename=artifact.filename,
    ) != artifact.storage_uri:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = store.local_path(artifact.storage_uri)
    try:
        verify_artifact_file(path, sha256=artifact.sha256, size_bytes=artifact.size_bytes)
    except (ArtifactIntegrityError, OSError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Artifact is unavailable or failed integrity verification.",
        ) from exc
    return FileResponse(
        path,
        media_type=artifact.media_type or "application/octet-stream",
        filename=Path(artifact.filename).name,
        headers={"X-Content-Type-Options": "nosniff"},
    )
