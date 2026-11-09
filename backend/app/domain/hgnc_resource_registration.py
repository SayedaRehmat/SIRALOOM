"""HGNC release registration through SIRALOOM's governed resource lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.domain.hgnc_crosswalk import (
    HGNC_ARCHIVE_RELEASE,
    HGNC_COMPLETE_URL,
    HGNC_LICENSE,
    HGNC_PUBLISHER,
    HGNCResourceError,
)
from backend.app.domain.resource_qualification import QualificationResult, qualify_resource
from backend.app.domain.resource_staging import (
    create_staging_candidate,
    stage_resource_release,
)
from backend.app.domain.resources import (
    qualify_resource_version,
    register_resource_version,
)
from backend.app.infrastructure.db.models import (
    Resource,
    ResourceQualification,
    ResourceStaging,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified_artifact(source: Path, destination: Path, expected_sha256: str, expected_size: int) -> None:
    if not source.is_file() or source.stat().st_size != expected_size:
        raise HGNCResourceError(f"HGNC source artifact size mismatch: {source.name}")
    if _sha256(source) != expected_sha256:
        raise HGNCResourceError(f"HGNC source artifact SHA-256 mismatch: {source.name}")
    if destination.exists():
        if destination.stat().st_size != expected_size or _sha256(destination) != expected_sha256:
            raise HGNCResourceError(f"existing managed HGNC artifact differs: {destination.name}")
        return
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
    ) as output:
        temporary = Path(output.name)
        try:
            with source.open("rb") as input_handle:
                shutil.copyfileobj(input_handle, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
            if temporary.stat().st_size != expected_size or _sha256(temporary) != expected_sha256:
                raise HGNCResourceError(f"copied HGNC artifact failed integrity check: {source.name}")
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def register_and_qualify_hgnc_release(
    db: Session,
    *,
    acquisition_directory: str | Path,
    managed_directory: str | Path,
    qualified_by: UUID | None = None,
    qualification_version: str = "siraloom-hgnc-2026-10-06-v1",
) -> tuple[Resource, ResourceStaging, ResourceQualification, QualificationResult]:
    """Stage the exact acquired HGNC package, register it, and persist qualification.

    The original acquisition directory is never modified. The two official TSV
    files are copied and independently hash-verified into the managed resource
    directory. The manifest itself is staged through the existing staging state
    machine. The existing server-side qualifier then validates the entire
    three-file package before the registry records QUALIFIED. This does not
    activate or approve the resource for any laboratory.
    """
    source_dir = Path(acquisition_directory).resolve()
    destination_dir = Path(managed_directory).resolve()
    source_manifest = source_dir / "manifest.json"
    if not source_manifest.is_file():
        raise HGNCResourceError("HGNC acquisition manifest is missing")
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") != "siraloom.hgnc-acquisition.v1":
        raise HGNCResourceError("unsupported HGNC acquisition manifest schema")
    if manifest.get("release") != HGNC_ARCHIVE_RELEASE:
        raise HGNCResourceError("HGNC acquisition release is not the pinned release")
    expected_sources = {
        "hgnc_complete_set.txt": HGNC_COMPLETE_URL,
        "withdrawn.txt": (
            "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/"
            "quarterly/tsv/withdrawn_2026-10-06.txt"
        ),
    }
    records = {item.get("filename"): item for item in manifest.get("files", [])}
    if set(records) != set(expected_sources):
        raise HGNCResourceError("HGNC manifest must contain exactly the two pinned TSV artifacts")
    destination_dir.mkdir(parents=True, exist_ok=True)
    for filename, expected_url in expected_sources.items():
        record = records[filename]
        if record.get("source_url") != expected_url:
            raise HGNCResourceError(f"HGNC source URL is not pinned for {filename}")
        _copy_verified_artifact(
            source_dir / filename,
            destination_dir / filename,
            str(record.get("sha256") or ""),
            int(record.get("size_bytes") or 0),
        )

    destination_manifest = destination_dir / "manifest.json"
    manifest_sha256 = _sha256(source_manifest)
    manifest_size = source_manifest.stat().st_size
    source_contract: dict[str, Any] = {
        "publisher": HGNC_PUBLISHER,
        "canonical_source_url": "https://www.genenames.org/download/archive/",
        "artifact_url": HGNC_COMPLETE_URL,
        "release_identity": HGNC_ARCHIVE_RELEASE,
        "access_mode": "PUBLIC",
        "license_status": "VERIFIED",
        "license_url": "https://www.genenames.org/about/license/",
        "checksum_status": "NOT_PUBLISHED",
        "authority_evidence_url": "https://www.genenames.org/download/archive/",
    }
    execution_contract = {
        "provider_id": "HGNC",
        "provider_version": HGNC_ARCHIVE_RELEASE,
        "access_method": "LOCAL",
        "location": str(destination_manifest),
    }
    resource, _created = register_resource_version(
        db,
        name="HGNC human gene nomenclature crosswalk",
        provider="HGNC",
        resource_type="GENE_NOMENCLATURE",
        version=HGNC_ARCHIVE_RELEASE,
        genome_build=None,
        access_method="LOCAL",
        license_text=HGNC_LICENSE,
        checksum=manifest_sha256,
        location=str(destination_manifest),
        population_definition=None,
        metadata_json={
            "source_contract": source_contract,
            "execution": execution_contract,
            "acquisition_manifest_sha256": manifest_sha256,
            "checksum_semantics": "LOCAL_SHA256; HGNC_DOES_NOT_PUBLISH_FILE_CHECKSUMS",
        },
        initial_status="CANDIDATE",
    )
    if resource.location != str(destination_manifest) or resource.checksum != manifest_sha256:
        raise HGNCResourceError("registered HGNC resource identity conflicts with the staged release")

    staging = create_staging_candidate(
        db,
        resource=resource,
        source_uri=str(source_manifest),
        destination_uri=str(destination_manifest),
        storage_backend="LOCAL_FILESYSTEM",
        expected_sha256=manifest_sha256,
        expected_size_bytes=manifest_size,
        staging_key=f"HGNC:{HGNC_ARCHIVE_RELEASE}:acquisition-manifest",
        metadata={
            "publisher": HGNC_PUBLISHER,
            "release": HGNC_ARCHIVE_RELEASE,
            "source_artifacts": sorted(expected_sources),
        },
    )
    if staging.status != "STAGED":
        stage_resource_release(db, staging, local_source_path=source_manifest)
    elif not destination_manifest.is_file() or _sha256(destination_manifest) != manifest_sha256:
        raise HGNCResourceError("existing HGNC staging record does not match its manifest bytes")

    result = qualify_resource(
        resource,
        staging=staging,
        qualification_version=qualification_version,
    )
    persisted = qualify_resource_version(
        db,
        resource_id=resource.id,
        qualification_version=qualification_version,
        checks=result.checks,
        qualified_by=qualified_by,
    )
    return resource, staging, persisted, result
