from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.application.entitlements import effective_max_upload_bytes
from backend.app.auth.authorization import CASE_WRITE_ROLES, require_role
from backend.app.auth.principal import Principal, get_current_principal, require_case_tenant
from backend.app.config import settings
from backend.app.domain.enums import ArtifactType, CaseStatus
from backend.app.domain.ingestion import classify_filename, normalize_build, validate_index, validate_vcf
from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Artifact, Case, Specimen
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["artifacts"])
MAX_BYTES = 512 * 1024 * 1024


def _store():
    return FirebaseArtifactStore(settings.firebase_storage_bucket) if settings.firebase_storage_enabled else ArtifactStore(settings.artifact_root)


def _safe_filename(filename: str) -> str:
    return Path(filename).name


@router.get("/cases/{case_id}/artifacts")
def list_case_artifacts(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_tenant(case, principal)
    rows = db.scalars(select(Artifact).where(Artifact.case_id == case_id).order_by(Artifact.created_at.desc())).all()
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
    file: UploadFile = File(...),
    specimen_id: UUID | None = Form(default=None),
    genome_build: str | None = Form(default=None),
    paired_artifact_id: UUID | None = Form(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_tenant(case, principal)
    require_role(principal, CASE_WRITE_ROLES)
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
    elif kind == "VCF":
        raise HTTPException(status_code=400, detail="A specimen_id is required for a primary VCF artifact.")

    requested_build = normalize_build(genome_build)
    if kind == "VCF" and requested_build not in {"GRCh37", "GRCh38"}:
        raise HTTPException(status_code=400, detail="Select genome_build explicitly as GRCh37 or GRCh38; SIRALOOM will not silently infer it.")

    with tempfile.TemporaryDirectory(prefix="siraloom-ingest-") as tmp:
        staged = Path(tmp) / filename
        digest_size = 0
        try:
            with staged.open("wb") as out:
                while chunk := await file.read(8 * 1024 * 1024):
                    digest_size += len(chunk)
                    if digest_size > max_bytes:
                        raise HTTPException(status_code=413, detail=f"Artifact exceeds maximum allowed size of {max_bytes} bytes")
                    out.write(chunk)
        finally:
            await file.close()

        if digest_size == 0:
            raise HTTPException(status_code=400, detail="The uploaded artifact is empty.")

        if kind == "VCF":
            result = validate_vcf(staged)
            if result.detected_build and result.detected_build != requested_build:
                result = type(result)("INVALID", result.file_kind, result.record_count, result.sample_names, result.detected_build, [f"VCF header indicates {result.detected_build}, but the selected genome build is {requested_build}."], result.warnings)
            artifact_type = ArtifactType.VCF
            validation_metadata = {
                "validation": {
                    "status": result.status, "record_count": result.record_count,
                    "sample_names": result.sample_names, "detected_build": result.detected_build,
                    "errors": result.errors, "warnings": result.warnings,
                },
                "ingestion": {"file_kind": "VCF", "original_filename": filename},
            }
            build_for_artifact = requested_build
        else:
            result = validate_index(staged, primary.filename)
            artifact_type = ArtifactType.VCF_INDEX_TBI if kind == "TBI" else ArtifactType.VCF_INDEX_CSI
            validation_metadata = {
                "validation": {"status": result.status, "errors": result.errors, "warnings": result.warnings},
                "ingestion": {"file_kind": kind, "paired_primary_artifact_id": str(primary.id)},
            }
            build_for_artifact = primary.genome_build

        store = _store()
        artifact = store.put_file(
            db=db, case_id=case_id, analysis_id=None, source_path=staged, filename=filename,
            artifact_type=artifact_type, media_type=file.content_type, genome_build=build_for_artifact,
            metadata=validation_metadata, specimen_id=specimen_id, paired_artifact_id=paired_artifact_id,
            validation_status=result.status,
        )

        if kind in {"TBI", "CSI"} and primary:
            primary.metadata_json = {**(primary.metadata_json or {}), "index": {"artifact_id": str(artifact.id), "status": result.status, "type": kind}}

        before_status = case.status
        if kind == "VCF":
            case.status = CaseStatus.READY_FOR_ANALYSIS if result.status == "VALID" else CaseStatus.INVALID
        elif result.status == "INVALID" and case.status == CaseStatus.READY_FOR_ANALYSIS:
            # An invalid optional index must not erase a valid primary VCF state.
            case.status = CaseStatus.READY_FOR_ANALYSIS
        elif primary and primary.validation_status == "VALID":
            case.status = CaseStatus.READY_FOR_ANALYSIS

        audit = AuditService(db)
        audit.record(
            event_type="ARTIFACT_VALIDATION_COMPLETED" if result.status == "VALID" else "ARTIFACT_VALIDATION_FAILED",
            case_id=case_id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id),
            subject_type="ARTIFACT", subject_id=str(artifact.id), operation="VALIDATE",
            before_state={"case_status": before_status},
            after_state={"case_status": case.status, "validation_status": result.status},
            reason="Variant artifact ingestion validation",
            output_artifacts=[{"artifact_id": str(artifact.id), "sha256": artifact.sha256}],
            payload={"filename": filename, "file_kind": kind, "validation": validation_metadata["validation"]},
        )
        db.commit()

        return {
            "artifact_id": str(artifact.id), "sha256": artifact.sha256, "size_bytes": artifact.size_bytes,
            "artifact_type": artifact.artifact_type, "validation_status": artifact.validation_status,
            "case_status": case.status, "genome_build": artifact.genome_build,
            "specimen_id": str(artifact.specimen_id) if artifact.specimen_id else None,
            "paired_artifact_id": str(artifact.paired_artifact_id) if artifact.paired_artifact_id else None,
            "validation": validation_metadata["validation"],
        }


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    try:
        artifact_uuid = UUID(artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid artifact_id") from exc
    artifact = db.get(Artifact, artifact_uuid)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    case = db.get(Case, artifact.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Artifact not found")
    require_case_tenant(case, principal)
    if artifact.storage_uri.startswith("gs://"):
        content = FirebaseArtifactStore(settings.firebase_storage_bucket).download_bytes(artifact.storage_uri)
        return Response(content=content, media_type=artifact.media_type or "application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'})
    store = ArtifactStore(settings.artifact_root)
    path = store.local_path(artifact.storage_uri)
    return FileResponse(path, media_type=artifact.media_type or "application/octet-stream", filename=artifact.filename)
