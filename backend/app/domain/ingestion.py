from __future__ import annotations

import gzip
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.app.domain.vcf import VCFValidationError, parse_vcf
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


def classify_filename(filename: str) -> str:
    name = Path(filename).name.lower()
    if name.endswith(".vcf.gz") or name.endswith(".vcf.bgz") or name.endswith(".vcf"):
        return "VCF"
    if name.endswith(".tbi"):
        return "TBI"
    if name.endswith(".csi"):
        return "CSI"
    return "UNSUPPORTED"


def _header_info(path: Path) -> tuple[list[str], str | None, bool]:
    headers: list[str] = []
    declared_builds: set[str] = set()
    has_fileformat = False

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
    return headers, detected_build, has_fileformat


def _bcftools_validate(path: Path) -> str | None:
    executable = shutil.which("bcftools")
    if executable is None:
        return None
    completed = subprocess.run(
        [executable, "view", "-Ov", "-o", "/dev/null", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        return (completed.stderr or completed.stdout or "bcftools rejected the VCF").strip()
    return None


def validate_vcf(path: str | Path) -> ValidationResult:
    p = Path(path)
    if classify_filename(p.name) != "VCF":
        return ValidationResult("INVALID", "UNSUPPORTED", 0, [], None, ["File is not a supported VCF input."], [])
    try:
        headers, detected_build, has_fileformat = _header_info(p)
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
        strict_profile = validate_vcf_strict(p)
        bcftools_error = _bcftools_validate(p)
        if bcftools_error:
            raise VCFValidationError(
                "VCF structural validation failed in bcftools/htslib: "
                + bcftools_error
            )

        records = 0
        warnings: list[str] = []
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
        for _ in parse_vcf(str(p)):
            records += 1
        if records == 0:
            raise VCFValidationError("VCF contains no variant records")
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
        unchecked_info_number_g = strict_profile["unchecked_info_number_g_fields"]
        if unchecked_info_number_g:
            warnings.append(
                "INFO fields declared with Number=G are present, but their genotype-value "
                "cardinality cannot be verified without a sample-specific ploidy: "
                + ", ".join(unchecked_info_number_g)
                + "."
            )
        return ValidationResult("VALID", "VCF", records, headers[9:] if len(headers) > 9 else [], detected_build, [], warnings)
    except (VCFValidationError, StrictVCFValidationError, OSError, EOFError, gzip.BadGzipFile, UnicodeError) as exc:
        return ValidationResult("INVALID", "VCF", 0, [], None, [str(exc)], [])


def validate_index(path: str | Path, primary_filename: str) -> ValidationResult:
    p = Path(path)
    kind = classify_filename(p.name)
    if kind not in {"TBI", "CSI"}:
        return ValidationResult("INVALID", kind, 0, [], None, ["Unsupported index format."], [])
    primary = Path(primary_filename).name
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
        return ValidationResult("VALID", kind, 0, [], None, [], [])
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
    expected = (expected_sample_name or "").strip()
    if result.status != "VALID":
        return result
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
        )
    if result.sample_names == [expected]:
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
    )
