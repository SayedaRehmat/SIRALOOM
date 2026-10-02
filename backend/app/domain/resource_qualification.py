"""Server-side qualification of staged scientific resources.

Qualification is separate from organization adoption. The API must use this
module rather than accepting a caller-supplied ``checks.passed`` value.
"""
from __future__ import annotations

import gzip
import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.domain.resource_source_contract import (
    ResourceSourceContractError,
    validate_execution_contract,
    validate_source_contract,
)
from backend.app.infrastructure.db.models import Resource


@dataclass(frozen=True)
class QualificationResult:
    qualification_version: str
    passed: bool
    checks: dict[str, Any]

    @property
    def blockers(self) -> list[str]:
        return list(self.checks.get("activation_blockers") or [])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_path(resource: Resource) -> Path | None:
    location = str(resource.location or "")
    if location.startswith("file://"):
        return Path(location.removeprefix("file://"))
    path = Path(location)
    return path if path.is_absolute() else None


def _qualify_clinvar(resource: Resource, path: Path | None, checks: dict[str, Any]) -> None:
    expected_name = f"ClinVarVCVRelease_{resource.version}.xml.gz"
    artifact_url = str(checks["source_contract"].get("artifact_url") or "")
    checks["provider"] = "ClinVarReleaseProvider"
    checks["release_filename"] = expected_name
    checks["artifact_filename_match"] = artifact_url.endswith(expected_name)
    if path is None:
        checks["artifact_validation"] = "STAGING_REQUIRED"
        return
    if not path.is_file() or path.stat().st_size <= 0:
        checks["artifact_validation"] = "MISSING_OR_EMPTY"
        return
    try:
        with gzip.open(path, "rb") as handle:
            payload = handle.read(1024 * 1024)
        if not payload.lstrip().startswith(b"<"):
            raise ValueError("gzip payload does not begin with XML")
        ET.fromstring(payload)
        checks["artifact_validation"] = "GZIP_XML_PREFIX_VALID"
    except (OSError, EOFError, ET.ParseError, ValueError) as exc:
        checks["artifact_validation"] = f"INVALID: {exc}"


def qualify_resource(resource: Resource, *, qualification_version: str = "siraloom-resource-qualification-v1") -> QualificationResult:
    if not qualification_version.strip():
        raise ValueError("qualification_version is required")
    metadata = dict(resource.metadata_json or {})
    try:
        contract = validate_source_contract(dict(metadata.get("source_contract") or {}))
    except ResourceSourceContractError as exc:
        return QualificationResult(qualification_version, False, {
            "engine": "siraloom.resource_qualification.v1",
            "passed": False,
            "source_contract": "INVALID",
            "activation_blockers": ["SOURCE_CONTRACT_INVALID"],
            "errors": [str(exc)],
        })

    blockers: list[str] = []
    try:
        execution = validate_execution_contract(
            dict(metadata.get("execution") or {}),
            resource_provider=resource.provider,
            resource_access_method=resource.access_method,
            resource_location=resource.location,
        )
    except ResourceSourceContractError as exc:
        return QualificationResult(qualification_version, False, {
            "engine": "siraloom.resource_qualification.v1",
            "passed": False,
            "source_contract": contract.as_dict(),
        "execution_contract": execution.as_dict(),
            "execution_contract": "INVALID",
            "activation_blockers": ["EXECUTION_CONTRACT_INVALID"],
            "errors": [str(exc)],
        })

    checks: dict[str, Any] = {
        "engine": "siraloom.resource_qualification.v1",
        "source_contract": contract.as_dict(),
        "publisher_present": bool(contract.publisher),
        "release_identity_match": resource.version == contract.release_identity,
        "artifact_location_match": resource.location == contract.artifact_url or _local_path(resource) is not None,
        "staging": "NOT_PRESENT",
        "activation_blockers": blockers,
    }
    path = _local_path(resource)
    if path is not None and path.is_file() and path.stat().st_size > 0:
        actual = _sha256(path)
        checks["staging"] = "PRESENT"
        checks["staged_sha256"] = actual
        checks["staged_size_bytes"] = path.stat().st_size
        if resource.checksum:
            checks["checksum_match"] = actual == resource.checksum.lower()
            if not checks["checksum_match"]:
                blockers.append("CHECKSUM_MISMATCH")
        elif contract.checksum_status == "PUBLISHED_AND_VERIFIED":
            blockers.append("PUBLISHED_CHECKSUM_MISSING")
    elif path is not None:
        checks["staging"] = "MISSING"
        blockers.append("STAGED_ARTIFACT_MISSING")
    else:
        blockers.append("STAGING_REQUIRED")
    if contract.checksum_status in {"NOT_PUBLISHED", "UNKNOWN", "TRANSPORT_DIGEST_ONLY"}:
        blockers.append("AUTHORITATIVE_CHECKSUM_UNVERIFIED")
    if contract.license_status in {"REVIEW_REQUIRED", "UNKNOWN", "RESTRICTED"}:
        blockers.append("LICENSE_REVIEW_REQUIRED")
    if contract.access_mode == "LICENSE_REQUIRED" and contract.license_status != "VERIFIED":
        blockers.append("LICENSE_NOT_VERIFIED")
    if resource.provider == "NCBI ClinVar":
        _qualify_clinvar(resource, path, checks)
    passed = all(bool(checks.get(name)) for name in ("publisher_present", "release_identity_match", "artifact_location_match")) and not blockers
    if resource.provider == "NCBI ClinVar" and checks.get("artifact_validation") != "GZIP_XML_PREFIX_VALID":
        passed = False
        if "ARTIFACT_STRUCTURE_NOT_VALIDATED" not in blockers:
            blockers.append("ARTIFACT_STRUCTURE_NOT_VALIDATED")
    checks["passed"] = passed
    checks["qualification_outcome"] = "QUALIFIED" if passed else "BLOCKED"
    return QualificationResult(qualification_version, passed, checks)