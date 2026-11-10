"""Immutable acquisition and governed registration for G2P and ClinGen GDV snapshots.

The downloader preserves the exact publisher response bytes. It never edits,
filters, normalizes, or rewrites a source artifact. Local SHA-256 identifies
the acquired snapshot where the publisher does not publish a checksum.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from backend.app.domain.resource_qualification import qualify_resource
from backend.app.domain.resource_staging import create_staging_candidate, stage_resource_release
from backend.app.domain.resources import qualify_resource_version, register_resource_version

G2P_PROVIDER = "Gene2Phenotype"
CLINGEN_PROVIDER = "ClinGen Gene-Disease Validity"
G2P_URL = "https://www.ebi.ac.uk/gene2phenotype/api/panel/all/download/"
CLINGEN_URL = "https://search.clinicalgenome.org/kb/gene-validity/download"
G2P_TERMS = "https://www.ebi.ac.uk/about/terms-of-use/"
CLINGEN_LICENSE = "https://www.clinicalgenome.org/docs/terms-of-use/"
CLINGEN_DOWNLOADS = "https://search.clinicalgenome.org/kb/downloads"


class GeneDiseaseAcquisitionError(RuntimeError):
    """Source acquisition or governed registration failed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_atomic(url: str, destination: Path) -> tuple[str, int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise GeneDiseaseAcquisitionError(
            f"Refusing to overwrite an existing acquired source artifact: {destination}"
        )
    request = Request(url, headers={"User-Agent": "SIRALOOM-resource-acquisition/1.0"})
    temporary: Path | None = None
    try:
        with urlopen(request, timeout=120) as response:
            final_url = response.geturl()
            if not final_url.startswith("https://"):
                raise GeneDiseaseAcquisitionError("Publisher download redirected away from HTTPS")
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
            ) as output:
                temporary = Path(output.name)
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
        if size <= 0:
            raise GeneDiseaseAcquisitionError("Publisher returned an empty source artifact")
        os.replace(temporary, destination)
        return final_url, size, digest.hexdigest()
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _clingen_file_created(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for _ in range(8):
            line = handle.readline()
            if not line:
                break
            match = re.search(r"FILE CREATED:\s*(\d{4}-\d{2}-\d{2})", line, re.IGNORECASE)
            if match:
                return match.group(1)
    raise GeneDiseaseAcquisitionError("ClinGen export is missing its FILE CREATED release identity")


def acquire_gene_disease_snapshots(destination: str | Path) -> dict:
    """Acquire exact current G2P and ClinGen publisher responses into a new directory."""
    root = Path(destination).resolve()
    if root.exists() and any(root.iterdir()):
        raise GeneDiseaseAcquisitionError("Acquisition destination must be new or empty")
    root.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(UTC).isoformat()
    g2p_path = root / "G2P_all.csv"
    clingen_path = root / "ClinGen_gene_validity.csv"
    g2p_final, g2p_size, g2p_sha = _download_atomic(G2P_URL, g2p_path)
    clingen_final, clingen_size, clingen_sha = _download_atomic(CLINGEN_URL, clingen_path)
    clingen_release = _clingen_file_created(clingen_path)
    acquisition_date = datetime.now(UTC).date().isoformat()
    manifest = {
        "schema": "siraloom.gene-disease-acquisition.v1",
        "acquired_at_utc": retrieved_at,
        "acquisition_date_utc": acquisition_date,
        "artifacts": [
            {
                "provider": G2P_PROVIDER,
                "filename": g2p_path.name,
                "requested_url": G2P_URL,
                "final_url": g2p_final,
                "release_identity": acquisition_date,
                "release_identity_kind": "ACQUISITION_DATE_UTC_ON_THE_FLY_EXPORT",
                "size_bytes": g2p_size,
                "sha256": g2p_sha,
                "publisher_checksum": None,
                "checksum_semantics": "LOCAL_SHA256_OF_UNMODIFIED_PUBLISHER_RESPONSE",
                "terms_url": G2P_TERMS,
            },
            {
                "provider": CLINGEN_PROVIDER,
                "filename": clingen_path.name,
                "requested_url": CLINGEN_URL,
                "final_url": clingen_final,
                "release_identity": clingen_release,
                "release_identity_kind": "PUBLISHER_FILE_CREATED_DATE",
                "size_bytes": clingen_size,
                "sha256": clingen_sha,
                "publisher_checksum": None,
                "checksum_semantics": "LOCAL_SHA256_OF_UNMODIFIED_PUBLISHER_RESPONSE",
                "license_url": CLINGEN_LICENSE,
            },
        ],
    }
    manifest_path = root / "manifest.json"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=root, prefix=".manifest.", delete=False
    ) as handle:
        temporary_manifest = Path(handle.name)
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_manifest, manifest_path)
    return manifest


def _copy_verified(source: Path, destination: Path, *, sha256: str, size_bytes: int) -> None:
    if not source.is_file() or source.stat().st_size != size_bytes or _sha256(source) != sha256:
        raise GeneDiseaseAcquisitionError(f"Acquisition source integrity check failed: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size != size_bytes or _sha256(destination) != sha256:
            raise GeneDiseaseAcquisitionError(f"Managed artifact conflicts with immutable source: {destination}")
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as output:
            temporary = Path(output.name)
            with source.open("rb") as input_handle:
                shutil.copyfileobj(input_handle, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size != size_bytes or _sha256(temporary) != sha256:
            raise GeneDiseaseAcquisitionError("Managed copy failed post-copy digest verification")
        os.replace(temporary, destination)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def register_and_qualify_gene_disease_snapshots(
    db: Session,
    *,
    acquisition_directory: str | Path,
    managed_directory: str | Path,
    qualified_by=None,
) -> list[tuple[object, object, object, object]]:
    """Register and technically qualify both exact source artifacts via Resource lifecycle.

    G2P's EMBL-EBI Terms of Use preserve upstream contributor rights; ClinGen
    curated content is CC0. Qualification remains separate from lab adoption.
    """
    source_dir = Path(acquisition_directory).resolve()
    managed_root = Path(managed_directory).resolve()
    manifest_path = source_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "siraloom.gene-disease-acquisition.v1":
        raise GeneDiseaseAcquisitionError("Unsupported gene-disease acquisition manifest")
    if len(manifest.get("artifacts", [])) != 2:
        raise GeneDiseaseAcquisitionError("Manifest must contain exactly G2P and ClinGen artifacts")
    outputs = []
    for item in manifest["artifacts"]:
        provider = item["provider"]
        filename = item["filename"]
        source = source_dir / filename
        sha = str(item["sha256"]).lower()
        size = int(item["size_bytes"])
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise GeneDiseaseAcquisitionError(f"Invalid SHA-256 in manifest for {filename}")
        release = str(item["release_identity"])
        managed = managed_root / provider.replace(" ", "_") / f"{release}-{sha[:12]}" / filename
        _copy_verified(source, managed, sha256=sha, size_bytes=size)
        is_g2p = provider == G2P_PROVIDER
        if not (is_g2p or provider == CLINGEN_PROVIDER):
            raise GeneDiseaseAcquisitionError(f"Unexpected provider in manifest: {provider}")
        source_contract = {
            "publisher": "EMBL-EBI" if is_g2p else "Clinical Genome Resource (ClinGen)",
            "canonical_source_url": "https://www.ebi.ac.uk/gene2phenotype/" if is_g2p else CLINGEN_DOWNLOADS,
            "artifact_url": item["requested_url"],
            "release_identity": release,
            "access_mode": "PUBLIC",
            "license_status": "VERIFIED",
            "license_url": None if is_g2p else CLINGEN_LICENSE,
            "terms_url": G2P_TERMS if is_g2p else None,
            "checksum_status": "LOCAL_SHA256_PINNED",
            "authority_evidence_url": "https://www.ebi.ac.uk/gene2phenotype/" if is_g2p else CLINGEN_DOWNLOADS,
        }
        execution = {
            "provider_id": provider,
            "provider_version": "G2P_CSV" if is_g2p else "GeneValidity",
            "access_method": "LOCAL",
            "location": str(managed),
            "toolchain": {
                "release": release,
                "sha256": sha,
                "manifest_path": str(manifest_path),
                "manifest_sha256": _sha256(manifest_path),
                "requested_url": item["requested_url"],
                "final_url": item["final_url"],
                "acquired_at_utc": manifest["acquired_at_utc"],
                "release_identity_kind": item["release_identity_kind"],
            },
        }
        resource, _ = register_resource_version(
            db,
            name="Gene2Phenotype disease models" if is_g2p else "ClinGen Gene-Disease Validity",
            provider=provider,
            resource_type="GENE_DISEASE",
            version=release,
            genome_build=None,
            access_method="LOCAL",
            license_text=(
                "EMBL-EBI Terms of Use; attribution expected; contributed data may retain original data-owner restrictions."
                if is_g2p else "CC0 1.0 Universal; attribution requested by ClinGen."
            ),
            checksum=sha,
            location=str(managed),
            population_definition=None,
            metadata_json={
                "source_contract": source_contract,
                "execution": execution,
                "acquisition_manifest_path": str(manifest_path),
                "acquisition_manifest_sha256": _sha256(manifest_path),
                "source_release_identity": release,
                "source_release_identity_kind": item["release_identity_kind"],
                "source_response_sha256": sha,
                "source_response_size_bytes": size,
                "source_requested_url": item["requested_url"],
                "source_final_url": item["final_url"],
                "attribution_required": True,
            },
            initial_status="CANDIDATE",
        )
        staging = create_staging_candidate(
            db,
            resource=resource,
            source_uri=str(source),
            destination_uri=str(managed),
            storage_backend="LOCAL_FILESYSTEM",
            expected_sha256=sha,
            expected_size_bytes=size,
            staging_key=f"{provider}:{release}:{sha}",
            metadata={"source_url": item["requested_url"], "acquired_at_utc": manifest["acquired_at_utc"]},
        )
        if staging.status != "STAGED":
            stage_resource_release(db, staging, local_source_path=source)
        result = qualify_resource(
            resource,
            staging=staging,
            qualification_version="siraloom-gene-disease-source-v1",
        )
        persisted = qualify_resource_version(
            db,
            resource_id=resource.id,
            qualification_version="siraloom-gene-disease-source-v1",
            checks=result.checks,
            qualified_by=qualified_by,
        )
        outputs.append((resource, staging, persisted, result))
    return outputs
