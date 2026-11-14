from __future__ import annotations

import gzip
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from backend.app.config import settings
from backend.app.domain.ebi_vcf_validator import EBIValidatorUnavailable, run_ebi_vcf_validator
from backend.app.domain.vcf import VCFValidationError, parse_vcf
from backend.app.domain.vcf_caller_profiles import inspect_caller_provenance
from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict

PRIMARY_SUFFIXES = (".vcf", ".vcf.gz", ".vcf.bgz")
INDEX_SUFFIXES = (".tbi", ".csi")
SUPPORTED_BUILDS = {"GRCh37", "GRCh38"}
_BUILD_MARKERS = (
    (re.compile(r"(?<![A-Za-z0-9])(?:GRCh38|hg38)(?![A-Za-z0-9])", re.IGNORECASE), "GRCh38"),
    (re.compile(r"(?<![A-Za-z0-9])(?:GRCh37|hg19)(?![A-Za-z0-9])", re.IGNORECASE), "GRCh37"),
)
_CONTIG_ASSEMBLY = re.compile(r'(?:^|,)assembly=(?:"([^"]*)"|([^,>]*))')


@dataclass(frozen=True)
class ValidationResult:
    status: str
    file_kind: str
    record_count: int
    sample_names: list[str]
    detected_build: str | None
    errors: list[str]
    warnings: list[str]
    fileformat: str | None = None
    metadata: dict | None = None
    error_code: str | None = None


class VCFValidationUnavailable(RuntimeError):
    """A required validation tool could not complete; the VCF is not classified."""


def classify_filename(filename: str) -> str:
    name = Path(filename).name.lower()
    if name.endswith(".vcf.gz") or name.endswith(".vcf.bgz") or name.endswith(".vcf"):
        return "VCF"
    if name.endswith(".tbi"):
        return "TBI"
    if name.endswith(".csi"):
        return "CSI"
    return "UNSUPPORTED"


def _header_info(path: Path) -> tuple[list[str], str | None, bool, str | None]:
    headers: list[str] = []
    declared_builds: set[str] = set()
    has_fileformat = False
    fileformat: str | None = None

    def record_assembly(value: str) -> None:
        for marker, build in _BUILD_MARKERS:
            if marker.search(value):
                declared_builds.add(build)

    opener = gzip.open if path.name.lower().endswith((".gz", ".bgz")) else open
    try:
        # This preliminary scan tolerates a BOM only to extract headers consistently;
        # validate_vcf_strict subsequently rejects BOM-prefixed input per VCF spec.
        with opener(path, "rt", encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("##fileformat="):
                    has_fileformat = True
                    fileformat = line.split("=", 1)[1].strip()
                elif line.startswith("##reference="):
                    value = line.split("=", 1)[1].strip()
                    if not value:
                        raise VCFValidationError("VCF reference metadata cannot have an empty value")
                    record_assembly(value)
                elif line.startswith("##contig=<"):
                    contig_metadata = line[len("##contig=<"):]
                    if contig_metadata.endswith(">"):
                        contig_metadata = contig_metadata[:-1]
                    assembly = _CONTIG_ASSEMBLY.search(contig_metadata)
                    if assembly:
                        record_assembly((assembly.group(1) or assembly.group(2) or "").strip())
                elif line.startswith("#CHROM"):
                    headers = line.split("\t")
                    break
    except (OSError, UnicodeDecodeError) as exc:
        raise VCFValidationError(f"Unable to read VCF text: {exc}") from exc
    if len(declared_builds) > 1:
        raise VCFValidationError(
            "VCF header contains conflicting reference assembly declarations: "
            + ", ".join(sorted(declared_builds))
        )
    detected_build = next(iter(declared_builds), None)
    return headers, detected_build, has_fileformat, fileformat


def _bcftools_validate(path: Path) -> tuple[str | None, str, str]:
    executable = shutil.which(settings.bcftools_executable)
    if executable is None:
        raise VCFValidationUnavailable(
            "bcftools/htslib is required to validate VCF input, but the executable was not found. "
            "The VCF was not accepted; restore the configured laboratory toolchain and retry."
        )
    expected_version = settings.bcftools_version
    try:
        version_result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VCFValidationUnavailable(
            "bcftools/htslib version attestation timed out. The VCF was not accepted; "
            "restore the configured laboratory toolchain and retry."
        ) from exc
    except OSError as exc:
        raise VCFValidationUnavailable(
            "bcftools/htslib could not be executed for version attestation. "
            "The VCF was not accepted; retry after the laboratory execution issue is resolved."
        ) from exc
    if version_result.returncode != 0:
        detail = (version_result.stderr or version_result.stdout or "unknown bcftools error").strip()
        raise VCFValidationUnavailable(
            f"Unable to attest the configured bcftools version: {detail}"
        )
    version_output = version_result.stdout or version_result.stderr
    version_line = next(
        (line.strip() for line in version_output.splitlines() if line.strip()),
        "unknown",
    )
    version_parts = version_line.split()
    detected_version = (
        version_parts[1]
        if len(version_parts) > 1 and version_parts[0].lower() == "bcftools"
        else None
    )
    if detected_version is None:
        raise VCFValidationUnavailable(
            f"Unable to parse the installed bcftools version from {version_line!r}."
        )
    htslib_line = next(
        (line.strip() for line in version_output.splitlines() if "htslib" in line.lower()),
        None,
    )
    if htslib_line is None:
        raise VCFValidationUnavailable(
            "Unable to attest the HTSlib version reported by the installed bcftools."
        )
    detected_htslib_version = htslib_line.split()[-1]
    expected_htslib_version = settings.htslib_version
    if expected_htslib_version and detected_htslib_version != expected_htslib_version:
        raise VCFValidationUnavailable(
            "HTSlib version mismatch during VCF intake: "
            f"expected {expected_htslib_version}, found {detected_htslib_version}. "
            "The VCF was not accepted; restore the organization-approved toolchain and retry."
        )
    if expected_version and detected_version != expected_version:
        raise VCFValidationUnavailable(
            "bcftools version mismatch during VCF intake: "
            f"expected {expected_version}, found {detected_version}. "
            "The VCF was not accepted; restore the organization-approved toolchain and retry."
        )
    try:
        completed = subprocess.run(
            [executable, "view", "--no-version", "-Ov", "-o", "/dev/null", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VCFValidationUnavailable(
            "bcftools/htslib validation exceeded its 120-second execution limit. "
            "The VCF was not accepted; retry after the laboratory execution issue is resolved."
        ) from exc
    except OSError as exc:
        raise VCFValidationUnavailable(
            "bcftools/htslib could not be executed. The VCF was not accepted; "
            "retry after the laboratory execution issue is resolved."
        ) from exc
    if completed.returncode != 0:
        return (
            (completed.stderr or completed.stdout or "bcftools rejected the VCF").strip(),
            version_line,
            detected_htslib_version,
        )
    return None, version_line, detected_htslib_version


def validate_vcf(
    path: str | Path,
    *,
    caller_attestation: dict | None = None,
    organization_id: UUID | None = None,
    artifact_sha256: str | None = None,
    expected_reference_build: str | None = None,
) -> ValidationResult:
    p = Path(path)
    if classify_filename(p.name) != "VCF":
        return ValidationResult("INVALID", "UNSUPPORTED", 0, [], None, ["File is not a supported VCF input."], [])
    fileformat: str | None = None
    bcftools_version: str | None = None
    htslib_version: str | None = None
    ebi_validation: dict | None = None
    ebi_error_code: str | None = None
    ebi_failure_reason: str | None = None
    try:
        try:
            caller_evidence = inspect_caller_provenance(p)
            ebi_validation = run_ebi_vcf_validator(
                p,
                expected_version=settings.ebi_vcf_validator_version,
                profile_id=settings.ebi_vcf_validator_profile_id,
                executable_name=settings.ebi_vcf_validator_executable,
                caller_provenance=caller_evidence,
            )
            fileformat = ebi_validation.get("vcf_version")
        except EBIValidatorUnavailable as exc:
            raise VCFValidationUnavailable(str(exc)) from exc
        if ebi_validation.get("status") == "FAIL":
            report_text = "\\n".join(
                str(report.get("content") or "")
                for report in ebi_validation.get("reports", [])
                if isinstance(report, dict)
            ).strip()
            ebi_failure_reason = (
                ebi_validation.get("stderr")
                or ebi_validation.get("stdout")
                or report_text
                or ebi_validation.get("reason")
                or f"EBI vcf-validator rejected the VCF (exit_code={ebi_validation.get('exit_code')})."
            )
        elif ebi_validation.get("status") not in {"PASS", "NOT_SUPPORTED"}:
            raise VCFValidationUnavailable(
                "EBI vcf-validator returned an unrecognized validation state; intake is blocked."
            )
        strict_profile = validate_vcf_strict(
            p,
            caller_attestation=caller_attestation,
            organization_id=organization_id,
            artifact_sha256=artifact_sha256,
            expected_reference_build=expected_reference_build,
        )
        compression = strict_profile["compression"]
        headers, detected_build, has_fileformat, fileformat = _header_info(p)
        if not has_fileformat:
            raise VCFValidationError(
                "VCF is missing the required ##fileformat header. If this file looks "
                "correct when you open it, check for hidden formatting issues -- e.g. "
                "it was saved as .rtf/.docx instead of plain text, or is HTML/a web-page "
                "export rather than a raw .vcf file."
            )
        if len(headers) < 8:
            # A single-element headers list with no tabs at all almost always means the
            # file uses spaces (or another delimiter) instead of tabs -- give a specific,
            # actionable diagnosis instead of a generic column-count complaint, since this
            # is a common result of copy-pasting a VCF from a rendered web page/table
            # instead of downloading the raw file.
            if len(headers) == 1 and " " in headers[0]:
                raise VCFValidationError(
                    "The #CHROM header uses spaces instead of tabs between columns, which "
                    "is not valid VCF. This usually happens when a VCF is copy-pasted from "
                    "a web page instead of downloaded as a raw file. Try downloading/saving "
                    "the original .vcf file directly (e.g. right-click -> Save As) rather "
                    "than copying the displayed text."
                )
            raise VCFValidationError(
                f"#CHROM header must contain at least the 8 required VCF columns "
                f"(tab-separated); found {len(headers)}: {headers!r}"
            )
        required = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
        if headers[:8] != required:
            raise VCFValidationError(
                f"The first eight VCF columns must be #CHROM, POS, ID, REF, ALT, QUAL, "
                f"FILTER, INFO in that exact order; found {headers[:8]!r}"
            )
        bcftools_error, bcftools_version, htslib_version = _bcftools_validate(p)
        if bcftools_error:
            raise VCFValidationError(
                "VCF structural validation failed in bcftools/htslib: "
                + bcftools_error
            )

        parsed_variant_record_count = 0
        warnings: list[str] = []
        reference_only_records = strict_profile["reference_only_records"]
        telomere_records = strict_profile["telomere_records"]
        saw_multiallelic = False
        saw_symbolic = False
        saw_gvcf_marker = False
        opener = gzip.open if p.name.lower().endswith((".gz", ".bgz")) else open
        with opener(p, "rt", encoding="utf-8-sig") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if line.startswith("##GVCFBlock") or "##ALT=<ID=NON_REF" in line:
                    saw_gvcf_marker = True
                if line.startswith("#"):
                    continue
                fields = line.split("\t")
                if len(fields) >= 5:
                    alt = fields[4]
                    saw_multiallelic = saw_multiallelic or "," in alt
                    saw_symbolic = saw_symbolic or any(
                        token.startswith("<") or token.startswith("*") or "[" in token or "]" in token
                        for token in alt.split(",")
                    )
        for _ in parse_vcf(str(p), allow_unselected_multisample=True):
            parsed_variant_record_count += 1
        if parsed_variant_record_count == 0:
            if reference_only_records:
                raise VCFValidationError(
                    "VCF contains no variant records: every row has ALT='.' (no alternate allele). "
                    "This cannot establish a negative clinical result; review the upstream callset."
                )
            if not telomere_records:
                raise VCFValidationError("VCF contains no variant records")
        if telomere_records:
            warnings.append(
                f"{telomere_records} VCF telomere sentinel record(s) at POS=0 or declared contig length + 1 are structurally valid, "
                "retained in the source, and excluded from small-variant analysis for explicit review."
            )
        if reference_only_records:
            warnings.append(
                f"{reference_only_records} reference-only VCF record(s) with ALT='.' were retained "
                "in the original file and excluded from variant analysis."
            )
        if saw_multiallelic:
            warnings.append(
                "Multiallelic records detected. SIRALOOM will split them with bcftools "
                "before reference-aware normalization."
            )
        if saw_symbolic:
            warnings.append(
                "Symbolic/breakend alleles detected. These records require a structural-"
                "variant workflow and are not processed by the Phase 1 small-variant normalizer."
            )
        if saw_gvcf_marker:
            warnings.append(
                "GVCF markers detected. GVCF reference blocks require a genotyping/joint-"
                "genotyping workflow and are not treated as ordinary Phase 1 variant records."
            )
        if ebi_validation and ebi_validation.get("status") == "NOT_SUPPORTED":
            warnings.append(
                "EBI vcf-validator does not support the declared "
                f"{ebi_validation.get('vcf_version')!r}; SIRALOOM's independent validator "
                "still ran, but no EBI conformance result is claimed for this file."
            )
        caller_provenance = strict_profile["caller_provenance"]
        if caller_provenance.get("caller_semantic_compatibility_review_required"):
            compatibility_status = caller_provenance.get(
                "caller_semantic_compatibility_status", "REVIEW_REQUIRED"
            )
            warnings.append(
                "Caller semantic compatibility requires review before genotype-based "
                f"clinical analysis (status={compatibility_status})."
            )
        unchecked_info_number_g = strict_profile["unchecked_info_number_g_fields"]
        if unchecked_info_number_g:
            warnings.append(
                "INFO fields declared with Number=G are present, but their genotype-value "
                "cardinality cannot be verified without a sample-specific ploidy: "
                + ", ".join(unchecked_info_number_g)
                + "."
            )
        unchecked_format_number_g = strict_profile["unchecked_format_number_g_fields"]
        if unchecked_format_number_g:
            warnings.append(
                "FORMAT fields declared with Number=G are present, but their genotype-value "
                "cardinality cannot be verified because GT does not establish sample ploidy: "
                + ", ".join(unchecked_format_number_g)
                + "."
            )
        if "VCF_BGZF_EOF_MARKER_MISSING" in strict_profile["warning_codes"]:
            warnings.append(
                "BGZF stream has no terminal empty block; the HTS specification recommends an EOF marker to help detect truncation."
            )
        validation_metadata = {
            "source_record_count": strict_profile["records"],
            "alternate_allele_count": strict_profile["alternate_allele_count"],
            "parsed_variant_record_count": parsed_variant_record_count,
            "reference_only_record_count": reference_only_records,
            "telomere_record_count": telomere_records,
            "multiallelic_source_record_count": strict_profile["multiallelic_records"],
            "symbolic_source_record_count": strict_profile["symbolic_records"],
            "breakend_source_record_count": strict_profile["breakend_records"],
            "gvcf_marker_count": strict_profile["gvcf_markers"],
            "caller_provenance": strict_profile["caller_provenance"],
            "ebi_vcf_validation": ebi_validation,
            "caller_run_attestation": strict_profile.get("caller_run_attestation"),
            "caller_semantic_attestation": strict_profile.get("caller_semantic_attestation"),
            "caller_semantic_compatibility_review_required": strict_profile.get("caller_semantic_compatibility_review_required", False),
            "vcf45_reference_span_records": strict_profile["vcf45_reference_span_records"],
            "vcf45_max_reference_end": strict_profile["vcf45_max_reference_end"],
            "vcf45_reference_block_sample_count": strict_profile["vcf45_reference_block_sample_count"],
            "base_modification_format_fields": strict_profile["base_modification_format_fields"],
            "unchecked_info_number_g_fields": strict_profile["unchecked_info_number_g_fields"],
            "unchecked_format_number_g_fields": strict_profile["unchecked_format_number_g_fields"],
            "bcftools_version": bcftools_version,
            "expected_bcftools_version": settings.bcftools_version,
            "htslib_version": htslib_version,
            "expected_htslib_version": settings.htslib_version,
            "bcftools_profile_id": settings.bcftools_profile_id,
            "toolchain_validation_status": "PASS",
            "compression": compression,
            "warning_codes": strict_profile["warning_codes"],
        }
        if ebi_failure_reason:
            ebi_error_code = "EBI_VCF_VALIDATION_FAILED"
            raise VCFValidationError(
                "EBI vcf-validator rejected the VCF: " + ebi_failure_reason[:4000]
            )
        return ValidationResult(
            "VALID",
            "VCF",
            parsed_variant_record_count,
            headers[9:] if len(headers) > 9 else [],
            detected_build,
            [],
            warnings,
            strict_profile["fileformat"],
            validation_metadata,
        )
    except (VCFValidationError, StrictVCFValidationError, OSError, EOFError, gzip.BadGzipFile, UnicodeError) as exc:
        # Strict validation may reject a caller-semantic deviation before it
        # returns its full profile. Preserve independently inspectable header
        # provenance for the durable invalid-artifact record without allowing
        # that metadata to alter the structural validation decision.
        failure_metadata: dict | None = {}
        if ebi_validation is not None:
            failure_metadata["ebi_vcf_validation"] = ebi_validation
        try:
            caller_provenance = inspect_caller_provenance(p)
            if caller_provenance.get("identity_status") != "UNKNOWN":
                failure_metadata["caller_provenance"] = caller_provenance
        except (OSError, EOFError, gzip.BadGzipFile, UnicodeError):
            pass
        if bcftools_version is not None:
            failure_metadata.update({
                "bcftools_version": bcftools_version,
                "expected_bcftools_version": settings.bcftools_version,
                "htslib_version": htslib_version,
                "expected_htslib_version": settings.htslib_version,
                "bcftools_profile_id": settings.bcftools_profile_id,
                "toolchain_validation_status": "PASS",
            })
        if not failure_metadata:
            failure_metadata = None
        return ValidationResult(
            "INVALID", "VCF", 0, [], None, [str(exc)], [], fileformat,
            failure_metadata,
            (
                ebi_error_code
                or (exc.code if isinstance(exc, StrictVCFValidationError) else None)
            ),
        )


def validate_index(
    path: str | Path,
    primary_filename: str,
    *,
    primary_path: str | Path | None = None,
    expected_bcftools_version: str | None = None,
) -> ValidationResult:
    p = Path(path)
    kind = classify_filename(p.name)
    if kind not in {"TBI", "CSI"}:
        return ValidationResult("INVALID", kind, 0, [], None, ["Unsupported index format."], [])
    primary = Path(primary_filename).name
    if not primary.lower().endswith((".vcf.gz", ".vcf.bgz")):
        return ValidationResult(
            "INVALID",
            kind,
            0,
            [],
            None,
            ["VCF indexes require a BGZF-compressed .vcf.gz or .vcf.bgz primary artifact."],
            [],
        )
    expected_suffix = ".tbi" if kind == "TBI" else ".csi"
    expected = primary + expected_suffix
    if p.name != expected:
        return ValidationResult("INVALID", kind, 0, [], None, [f"Index filename must match the primary artifact ({expected})."], [])
    try:
        with p.open("rb") as fh:
            magic = fh.read(4)
        if kind == "CSI" and magic != b"CSI\x01":
            raise ValueError("CSI index does not contain the CSI magic header")
        if kind == "TBI":
            if magic[:2] != b"\x1f\x8b":
                raise ValueError("TBI index does not contain a BGZF/gzip header")
            with gzip.open(p, "rb") as fh:
                if fh.read(4) != b"TBI\x01":
                    raise ValueError("TBI index does not contain the TBI magic header")
        if primary_path is None:
            return ValidationResult(
                "VALID", kind, 0, [], None, [],
                ["Index structure is valid; concordance with the primary VCF was not checked."],
                metadata={"index_concordance": {"status": "NOT_CHECKED"}},
            )
        primary = Path(primary_path)
        if not primary.is_file() or primary.name != primary_filename:
            raise ValueError("Primary VCF path does not match the paired artifact filename.")
        from backend.app.domain.vcf_tools import (
            VCFToolError,
            VCFToolUnavailable,
            validate_vcf_index_concordance,
        )
        try:
            concordance = validate_vcf_index_concordance(
                primary,
                expected_bcftools_version=expected_bcftools_version,
            )
        except VCFToolUnavailable as exc:
            raise VCFValidationUnavailable(str(exc)) from exc
        except VCFToolError as exc:
            return ValidationResult(
                "INVALID", kind, 0, [], None, [str(exc)], [],
                metadata={"index_concordance": {"status": "FAILED"}},
            )
        return ValidationResult(
            "VALID", kind, 0, [], None, [], [],
            metadata={"index_concordance": concordance},
        )
    except (OSError, ValueError, EOFError, gzip.BadGzipFile) as exc:
        return ValidationResult("INVALID", kind, 0, [], None, [str(exc)], [])


def normalize_build(requested: str | None) -> str | None:
    if requested is None or not requested.strip():
        return None
    value = requested.strip()
    aliases = {"hg38": "GRCh38", "hg19": "GRCh37", "grch38": "GRCh38", "grch37": "GRCh37"}
    return aliases.get(value.lower(), value)


def validate_specimen_sample_identity(
    result: ValidationResult,
    expected_sample_name: str | None,
) -> ValidationResult:
    """Reject a structurally valid VCF that contradicts an explicit specimen mapping.

    A missing mapping is an accession validation failure; it is never inferred
    from the specimen identifier. This keeps case readiness aligned with the
    precondition enforced by analysis creation.
    """
    expected = expected_sample_name.strip() if isinstance(expected_sample_name, str) else ""
    if result.status != "VALID":
        return result
    if not result.sample_names:
        # A sites-only VCF is structurally valid but has no sample genotype.
        # Keep it as a site-level artifact; do not demand a fictitious sample.
        return ValidationResult(
            result.status, result.file_kind, result.record_count, result.sample_names,
            result.detected_build, result.errors,
            [*result.warnings, "Sites-only VCF: accepted as a site-level artifact; not eligible for sample-specific interpretation or clinical reporting."],
            result.fileformat,
            result.metadata,
            result.error_code,
        )
    if not expected:
        error = "The specimen must have an explicit VCF sample name mapping before intake can pass."
        return ValidationResult(
            "INVALID",
            result.file_kind,
            result.record_count,
            result.sample_names,
            result.detected_build,
            [*result.errors, error],
            result.warnings,
            result.fileformat,
            result.metadata,
            "VCF_SAMPLE_MAPPING_REQUIRED",
        )
    if expected in result.sample_names:
        return result
    observed = ", ".join(result.sample_names) if result.sample_names else "no named samples"
    error = (
        f"VCF sample identity mismatch: specimen is mapped to {expected!r}, "
        f"but the VCF contains {observed}."
    )
    return ValidationResult(
        "INVALID",
        result.file_kind,
        result.record_count,
        result.sample_names,
        result.detected_build,
        [*result.errors, error],
        result.warnings,
        result.fileformat,
        result.metadata,
        "VCF_SAMPLE_IDENTITY_MISMATCH",
    )
