"""Server-side qualification of staged scientific resources.

Qualification is separate from organization adoption. The API must use this
module rather than accepting a caller-supplied ``checks.passed`` value.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.domain.local_uri import local_path_from_uri
from backend.app.domain.hgnc_crosswalk import (
    HGNC_ARCHIVE_RELEASE,
    HGNCResolver,
)
from backend.app.domain.resource_source_contract import (
    ResourceSourceContractError,
    validate_execution_contract,
    validate_source_contract,
)
from backend.app.infrastructure.db.models import Resource, ResourceStaging


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
    path = local_path_from_uri(location)
    if path is None:
        return None
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
        # Validate the complete decompressed XML stream without materializing a
        # large ClinVar release in memory. This proves XML well-formedness only;
        # it is not XSD validation or scientific-content validation.
        element_count = 0
        root_tag: str | None = None
        with gzip.open(path, "rb") as handle:
            for event, element in ET.iterparse(handle, events=("start", "end")):
                if event == "start" and root_tag is None:
                    root_tag = str(element.tag)
                elif event == "end":
                    element_count += 1
                    element.clear()
        if root_tag is None or element_count == 0:
            raise ValueError("gzip payload contained no XML elements")
        checks["artifact_validation"] = "GZIP_XML_WELL_FORMED"
        checks["xml_root_tag"] = root_tag
        checks["xml_element_count"] = element_count
    except (OSError, EOFError, ET.ParseError, ValueError) as exc:
        checks["artifact_validation"] = f"INVALID: {exc}"


def _qualify_reference_toolchain(resource: Resource, execution: Any, blockers: list[str], checks: dict[str, Any]) -> None:
    """Require the exact normalization toolchain for governed reference execution."""
    toolchain = dict(execution.toolchain or {})
    bcftools = toolchain.get("bcftools")
    if not isinstance(bcftools, dict):
        blockers.append("BCFTOOLS_TOOLCHAIN_NOT_DECLARED")
        return
    version = str(bcftools.get("version") or "").strip()
    if not version:
        blockers.append("BCFTOOLS_VERSION_NOT_DECLARED")
        return
    checks["bcftools_version"] = version
    checks["bcftools_tool"] = "bcftools"
    checks["bcftools_execution"] = "GOVERNED"


def _qualify_vep_runtime(execution: Any, blockers: list[str], checks: dict[str, Any]) -> None:
    """Require the governed VEP executable and cache to be usable offline.

    This is a technical preflight only. Scientific accuracy still requires an
    independently specified known-answer fixture and laboratory qualification.
    """
    from backend.app.adapters.annotation.vep import VEPProvider, VEPProviderError

    try:
        provider = VEPProvider.from_execution_contract(execution)
        build = str((execution.toolchain or {}).get("assembly") or "")
        checks["vep_runtime"] = provider.verify_local_runtime(build)
    except (VEPProviderError, OSError) as exc:
        blockers.append("VEP_RUNTIME_PREFLIGHT_FAILED")
        checks["vep_runtime"] = {
            "status": "BLOCKED",
            "error": str(exc)[:2000],
        }


def _qualify_hgnc(resource: Resource, manifest_path: Path | None, blockers: list[str], checks: dict[str, Any]) -> None:
    """Validate exact pinned HGNC artifacts and deterministic crosswalk structure."""
    checks["provider"] = "HGNCArchiveProvider"
    checks["hgnc_release"] = resource.version
    if manifest_path is None or not manifest_path.is_file():
        blockers.append("HGNC_ACQUISITION_MANIFEST_MISSING")
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != "siraloom.hgnc-acquisition.v1":
            raise ValueError("unsupported acquisition manifest schema")
        if manifest.get("release") != HGNC_ARCHIVE_RELEASE or resource.version != HGNC_ARCHIVE_RELEASE:
            raise ValueError("HGNC release identity does not match pinned qualification")
        if manifest.get("publisher") != "HUGO Gene Nomenclature Committee":
            raise ValueError("unexpected HGNC publisher")
        if manifest.get("license") != "CC0-1.0":
            raise ValueError("HGNC license identity is not CC0-1.0")
        files = {item.get("filename"): item for item in manifest.get("files", [])}
        expected = {
            "hgnc_complete_set.txt": "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/quarterly/tsv/hgnc_complete_set_2026-10-06.txt",
            "withdrawn.txt": "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/quarterly/tsv/withdrawn_2026-10-06.txt",
        }
        paths = {}
        for filename, source_url in expected.items():
            record = files.get(filename)
            if not record or record.get("source_url") != source_url:
                raise ValueError(f"unexpected or missing pinned source artifact: {filename}")
            artifact = manifest_path.parent / filename
            if not artifact.is_file() or artifact.stat().st_size <= 0:
                raise ValueError(f"HGNC artifact missing or empty: {filename}")
            observed = _sha256(artifact)
            if observed != record.get("sha256") or artifact.stat().st_size != record.get("size_bytes"):
                raise ValueError(f"HGNC artifact integrity mismatch: {filename}")
            paths[filename] = artifact
        resolver = HGNCResolver(
            paths["hgnc_complete_set.txt"], paths["withdrawn.txt"],
            release=HGNC_ARCHIVE_RELEASE,
        )
        checks["hgnc_crosswalk"] = {
            "status": "STRUCTURALLY_VALIDATED",
            "release": HGNC_ARCHIVE_RELEASE,
            "approved_gene_count": len(resolver._approved),
            "approved_symbol_count": len(resolver._approved_symbols),
            "alias_symbol_count": len(resolver._alias_index),
            "previous_symbol_count": len(resolver._previous),
            "ensembl_gene_id_count": len(resolver._ensembl),
            "withdrawn_symbol_count": len(resolver._withdrawn),
            "complete_set_sha256": resolver.complete_sha256,
            "withdrawn_sha256": resolver.withdrawn_sha256,
            "checksum_semantics": manifest.get("checksum_semantics"),
            "upstream_checksums_published": False,
        }
        if len(resolver._approved) < 10000:
            raise ValueError("HGNC complete set is implausibly small")
        if not resolver._ensembl:
            raise ValueError("HGNC complete set contains no Ensembl gene identifiers")
        checks["hgnc_crosswalk"]["status"] = "QUALIFICATION_CHECKS_PASSED"
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        blockers.append("HGNC_CROSSWALK_QUALIFICATION_FAILED")
        checks["hgnc_crosswalk"] = {"status": "BLOCKED", "error": str(exc)[:2000]}


def _qualify_gene_disease_provider(
    resource: Resource,
    path: Path | None,
    blockers: list[str],
    checks: dict[str, Any],
) -> None:
    """Run the production provider parser against exact staged, digest-pinned bytes."""
    if path is None or not path.is_file():
        blockers.append("GENE_DISEASE_SOURCE_ARTIFACT_MISSING")
        return
    expected_sha = str(resource.checksum or "").lower()
    if not expected_sha or _sha256(path) != expected_sha:
        blockers.append("GENE_DISEASE_SOURCE_DIGEST_MISMATCH")
        return
    metadata = dict(resource.metadata_json or {})
    execution = dict(metadata.get("execution") or {})
    toolchain = dict(execution.get("toolchain") or {})
    release = str(toolchain.get("release") or "")
    manifest_path_value = str(toolchain.get("manifest_path") or metadata.get("acquisition_manifest_path") or "")
    manifest_sha_expected = str(toolchain.get("manifest_sha256") or metadata.get("acquisition_manifest_sha256") or "").lower()
    if not manifest_path_value or not manifest_sha_expected:
        blockers.append("GENE_DISEASE_ACQUISITION_MANIFEST_NOT_PINNED")
        return
    manifest_path = Path(manifest_path_value)
    if not manifest_path.is_file() or _sha256(manifest_path) != manifest_sha_expected:
        blockers.append("GENE_DISEASE_ACQUISITION_MANIFEST_DIGEST_MISMATCH")
        return
    try:
        acquisition_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if acquisition_manifest.get("schema") != "siraloom.gene-disease-acquisition.v1":
            raise ValueError("unsupported acquisition manifest schema")
        manifest_records = [
            item for item in acquisition_manifest.get("artifacts", [])
            if item.get("provider") == resource.provider
        ]
        if len(manifest_records) != 1:
            raise ValueError("acquisition manifest must contain exactly one matching provider artifact")
        manifest_record = manifest_records[0]
        if (
            manifest_record.get("release_identity") != release
            or manifest_record.get("sha256") != expected_sha
            or manifest_record.get("size_bytes") != path.stat().st_size
            or manifest_record.get("requested_url") != metadata.get("source_requested_url")
            or manifest_record.get("final_url") != metadata.get("source_final_url")
        ):
            raise ValueError("acquisition manifest does not identify the registered source bytes and endpoint")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        blockers.append("GENE_DISEASE_ACQUISITION_MANIFEST_INVALID")
        checks["gene_disease_acquisition_manifest"] = {"status": "BLOCKED", "error": str(exc)[:2000]}
        return
    checks["gene_disease_acquisition_manifest"] = {
        "status": "VERIFIED",
        "sha256": manifest_sha_expected,
        "acquired_at_utc": acquisition_manifest.get("acquired_at_utc"),
        "release_identity_kind": manifest_record.get("release_identity_kind"),
        "requested_url": manifest_record.get("requested_url"),
        "final_url": manifest_record.get("final_url"),
    }
    if release != resource.version:
        blockers.append("GENE_DISEASE_RELEASE_IDENTITY_MISMATCH")
        checks["gene_disease_source"] = {"status": "BLOCKED", "resource_version": resource.version, "declared_release": release}
        return
    try:
        if resource.provider == "Gene2Phenotype":
            from backend.app.adapters.gene_disease.g2p import G2PProvider
            provider = G2PProvider(resource_path=str(path), expected_sha256=expected_sha, release=release)
            records = tuple(provider._records)
            record_ids = [record.source_record_id for record in records]
            mondo_missing = sum(record.disease_mondo is None for record in records)
            gene_ids_present = sum(record.hgnc_id is not None for record in records)
            source_schema = "G2P_CSV"
        elif resource.provider == "ClinGen Gene-Disease Validity":
            from backend.app.adapters.clingen.gene_disease_validity import ClinGenGeneDiseaseValidityProvider
            provider = ClinGenGeneDiseaseValidityProvider(resource_path=str(path), expected_sha256=expected_sha, expected_release=release)
            index = provider._load_index()
            records = tuple(record for group in index.values() for record in group)
            record_ids = [record.source_record_id for record in records]
            mondo_missing = sum(record.mondo_id is None for record in records)
            gene_ids_present = sum(record.hgnc_id is not None for record in records)
            source_schema = "CLINGEN_GENE_VALIDITY_CSV"
            if provider.release_date != release:
                raise ValueError("ClinGen FILE CREATED does not match pinned resource release")
        else:
            return
        if not records:
            raise ValueError("provider parser returned no gene-disease assertions")
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("provider export contains duplicate source record identifiers")
        checks["gene_disease_source"] = {
            "status": "PROVIDER_PARSER_QUALIFIED",
            "provider": resource.provider,
            "schema": source_schema,
            "release": release,
            "sha256": expected_sha,
            "record_count": len(records),
            "unique_source_record_count": len(set(record_ids)),
            "records_missing_mondo": mondo_missing,
            "records_with_native_hgnc_id": gene_ids_present,
            "records_without_native_hgnc_id": len(records) - gene_ids_present,
            "raw_artifact_preserved": True,
            "parser": "production_provider_adapter",
            "clinical_validity_claim": False,
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        blockers.append("GENE_DISEASE_PROVIDER_QUALIFICATION_FAILED")
        checks["gene_disease_source"] = {"status": "BLOCKED", "provider": resource.provider, "error": str(exc)[:2000]}


def qualify_resource(
    resource: Resource,
    *,
    staging: ResourceStaging | None = None,
    qualification_version: str = "siraloom-resource-qualification-v1",
) -> QualificationResult:
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
    if staging is None:
        blockers.append("STAGING_RECORD_REQUIRED")
    elif staging.resource_id != resource.id or staging.resource_version != resource.version:
        blockers.append("STAGING_RESOURCE_IDENTITY_MISMATCH")
    elif staging.status != "STAGED":
        blockers.append("STAGING_NOT_VERIFIED")
    elif staging.destination_uri != resource.location:
        blockers.append("STAGING_LOCATION_MISMATCH")
    try:
        execution = validate_execution_contract(
            dict(metadata.get("execution") or {}),
            resource_provider=resource.provider,
            resource_access_method=resource.access_method,
            resource_location=resource.location,
            resource_organization_id=resource.organization_id,
        )
    except ResourceSourceContractError as exc:
        return QualificationResult(qualification_version, False, {
            "engine": "siraloom.resource_qualification.v1",
            "passed": False,
            "source_contract": contract.as_dict(),
            "execution_contract": "INVALID",
            "activation_blockers": ["EXECUTION_CONTRACT_INVALID"],
            "errors": [str(exc)],
        })

    checks: dict[str, Any] = {
        "engine": "siraloom.resource_qualification.v1",
        "source_contract": contract.as_dict(),
        "execution_contract": execution.as_dict(),
        "publisher_present": bool(contract.publisher),
        "release_identity_match": resource.version == contract.release_identity,
        "artifact_location_match": resource.location == contract.artifact_url or _local_path(resource) is not None,
        "staging": (
            "VERIFIED"
            if staging is not None and staging.status == "STAGED"
            else "NOT_PRESENT"
        ),
        "staging_record_id": str(staging.id) if staging is not None else None,
        "activation_blockers": blockers,
    }
    if resource.resource_type == "REFERENCE_PACKAGE":
        _qualify_reference_toolchain(resource, execution, blockers, checks)
    path = _local_path(resource)
    if (
        staging is not None
        and staging.status == "STAGED"
        and staging.destination_uri == resource.location
        and path is not None
        and path.is_file()
        and path.stat().st_size > 0
    ):
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
    elif staging is None:
        blockers.append("STAGING_RECORD_REQUIRED")
    elif staging.status != "STAGED":
        blockers.append("STAGING_NOT_VERIFIED")
    elif path is not None:
        checks["staging"] = "MISSING"
        blockers.append("STAGED_ARTIFACT_MISSING")
    else:
        blockers.append("STAGING_REQUIRED")
    if contract.checksum_status in {"NOT_PUBLISHED", "UNKNOWN", "TRANSPORT_DIGEST_ONLY"} and resource.provider != "HGNC":
        blockers.append("AUTHORITATIVE_CHECKSUM_UNVERIFIED")
    if contract.license_status in {"REVIEW_REQUIRED", "UNKNOWN", "RESTRICTED"}:
        blockers.append("LICENSE_REVIEW_REQUIRED")
    if contract.access_mode == "LICENSE_REQUIRED" and contract.license_status != "VERIFIED":
        blockers.append("LICENSE_NOT_VERIFIED")
    if resource.provider == "HGNC":
        _qualify_hgnc(resource, path, blockers, checks)
    if resource.provider in {"Gene2Phenotype", "ClinGen Gene-Disease Validity"}:
        _qualify_gene_disease_provider(resource, path, blockers, checks)
    if resource.provider == "NCBI ClinVar":
        _qualify_clinvar(resource, path, checks)
    if resource.provider == "VEP":
        if not path or not path.is_file() or not staging or staging.status != "STAGED":
            blockers.append("VEP_RESOURCE_ARTIFACT_NOT_STAGED")
            checks["vep_runtime"] = {"status": "NOT_RUN", "reason": "resource artifact is not staged"}
        else:
            toolchain = dict(execution.toolchain or {})
            registered_artifact_sha256 = str(resource.checksum or "").lower()
            if (
                not registered_artifact_sha256
                or str(toolchain.get("cache_artifact_sha256") or "").lower()
                != registered_artifact_sha256
            ):
                blockers.append("VEP_CACHE_ARTIFACT_DIGEST_MISMATCH")
            _qualify_vep_runtime(execution, blockers, checks)
    passed = all(bool(checks.get(name)) for name in ("publisher_present", "release_identity_match", "artifact_location_match")) and not blockers
    if resource.provider == "NCBI ClinVar" and checks.get("artifact_validation") != "GZIP_XML_WELL_FORMED":
        passed = False
        if "ARTIFACT_STRUCTURE_NOT_VALIDATED" not in blockers:
            blockers.append("ARTIFACT_STRUCTURE_NOT_VALIDATED")
    checks["passed"] = passed
    checks["qualification_outcome"] = "QUALIFIED" if passed else "BLOCKED"
    return QualificationResult(qualification_version, passed, checks)
