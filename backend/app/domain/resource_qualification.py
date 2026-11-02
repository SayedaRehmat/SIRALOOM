"""Server-side qualification of staged scientific resources.

Qualification is separate from organization adoption. The API must use this
module rather than accepting a caller-supplied ``checks.passed`` value.
"""
from __future__ import annotations

import gzip
import hashlib
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.domain.local_uri import local_path_from_uri
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


def _qualify_normalization_engine(
    resource: Resource,
    execution: Any,
    blockers: list[str],
    checks: dict[str, Any],
) -> None:
    """Qualify BCFtools against the exact release and SIRALOOM's core contract.

    GATK is intentionally blocked until a separate adapter has been qualified
    against the complete normalization contract; it is not treated as a
    drop-in replacement merely because it can left-align some indels.
    """
    provider = str(resource.provider or "").strip().casefold()
    if provider != "bcftools":
        blockers.append("NORMALIZATION_PROVIDER_ADAPTER_NOT_IMPLEMENTED")
        checks["normalization_runtime"] = {
            "status": "BLOCKED",
            "provider": resource.provider,
            "reason": "No qualified normalization adapter is registered for this provider.",
        }
        return

    toolchain = dict(execution.toolchain or {})
    bcftools = toolchain.get("bcftools")
    if not isinstance(bcftools, dict):
        blockers.append("BCFTOOLS_EXECUTION_NOT_DECLARED")
        checks["normalization_runtime"] = {"status": "BLOCKED", "reason": "toolchain.bcftools is missing"}
        return
    executable = str(bcftools.get("executable") or "").strip()
    if not executable:
        blockers.append("BCFTOOLS_EXECUTABLE_NOT_DECLARED")
        checks["normalization_runtime"] = {"status": "BLOCKED", "reason": "toolchain.bcftools.executable is missing"}
        return

    resolved_executable = shutil.which(executable)
    if resolved_executable is None and Path(executable).is_file():
        resolved_executable = str(Path(executable).resolve())
    if resolved_executable is None:
        blockers.append("BCFTOOLS_EXECUTABLE_UNAVAILABLE")
        checks["normalization_runtime"] = {"status": "BLOCKED", "executable": executable}
        return

    try:
        version_result = subprocess.run(
            [resolved_executable, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        blockers.append("BCFTOOLS_VERSION_PROBE_FAILED")
        checks["normalization_runtime"] = {
            "status": "BLOCKED",
            "executable": resolved_executable,
            "error_type": type(exc).__name__,
        }
        return
    version_output = "\n".join((version_result.stdout or "", version_result.stderr or ""))
    version_match = re.search(r"(?im)^bcftools\s+([^\s]+)", version_output)
    observed_version = version_match.group(1) if version_match else None
    checks["normalization_runtime"] = {
        "status": "VERSION_PROBED",
        "provider": "bcftools",
        "executable": resolved_executable,
        "expected_version": resource.version,
        "observed_version": observed_version,
        "version_exit_code": version_result.returncode,
    }
    if version_result.returncode != 0 or observed_version != str(resource.version).strip():
        blockers.append("BCFTOOLS_VERSION_MISMATCH")
        checks["normalization_runtime"]["status"] = "BLOCKED"
        return

    try:
        with tempfile.TemporaryDirectory(prefix="siraloom-normalization-qualification-") as directory:
            root = Path(directory)
            reference = root / "reference.fa"
            source = root / "source.vcf"
            normalized = root / "normalized.vcf"
            mismatch = root / "ref-mismatch.vcf"
            mismatch_output = root / "ref-mismatch.out.vcf"
            reference.write_text(">chr1\nCAAAAAC\n", encoding="ascii")
            source.write_text(
                "##fileformat=VCFv4.2\n"
                "##contig=<ID=chr1,length=7>\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                "chr1\t3\t.\tAA\tA\t.\tPASS\t.\n"
                "chr1\t7\t.\tC\tT,G\t.\tPASS\t.\n",
                encoding="ascii",
            )
            mismatch.write_text(
                "##fileformat=VCFv4.2\n"
                "##contig=<ID=chr1,length=7>\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                "chr1\t7\t.\tA\tT\t.\tPASS\t.\n",
                encoding="ascii",
            )
            normalize_result = subprocess.run(
                [
                    resolved_executable, "norm", "-f", str(reference), "-c", "e",
                    "-m", "-any", "-Ov", "-o", str(normalized), str(source),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if normalize_result.returncode != 0 or not normalized.is_file():
                raise RuntimeError("known-answer normalization command failed")
            observed_records = []
            for line in normalized.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#"):
                    fields = line.split("\t")
                    observed_records.append((fields[0], fields[1], fields[3], fields[4]))
            expected_records = [
                ("chr1", "1", "CA", "C"),
                ("chr1", "7", "C", "T"),
                ("chr1", "7", "C", "G"),
            ]
            if observed_records != expected_records:
                raise RuntimeError(
                    f"known-answer output mismatch: expected {expected_records!r}, observed {observed_records!r}"
                )
            mismatch_result = subprocess.run(
                [
                    resolved_executable, "norm", "-f", str(reference), "-c", "e",
                    "-m", "-any", "-Ov", "-o", str(mismatch_output), str(mismatch),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if mismatch_result.returncode == 0:
                raise RuntimeError("REF-mismatch fixture unexpectedly succeeded under -c e")
            checks["normalization_runtime"].update({
                "status": "QUALIFIED",
                "known_answer": "PASS",
                "left_alignment": "PASS",
                "multiallelic_decomposition": "PASS",
                "ref_mismatch_rejection": "PASS",
                "expected_records": [list(record) for record in expected_records],
                "observed_records": [list(record) for record in observed_records],
            })
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
        blockers.append("BCFTOOLS_NORMALIZATION_CONFORMANCE_FAILED")
        checks["normalization_runtime"].update({
            "status": "BLOCKED",
            "known_answer": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
        })


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
    if resource.resource_type == "NORMALIZATION":
        _qualify_normalization_engine(resource, execution, blockers, checks)
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
    if contract.checksum_status in {"NOT_PUBLISHED", "UNKNOWN", "TRANSPORT_DIGEST_ONLY"}:
        blockers.append("AUTHORITATIVE_CHECKSUM_UNVERIFIED")
    if contract.license_status in {"REVIEW_REQUIRED", "UNKNOWN", "RESTRICTED"}:
        blockers.append("LICENSE_REVIEW_REQUIRED")
    if contract.access_mode == "LICENSE_REQUIRED" and contract.license_status != "VERIFIED":
        blockers.append("LICENSE_NOT_VERIFIED")
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
