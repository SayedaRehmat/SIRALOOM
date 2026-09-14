from __future__ import annotations

import gzip
import re
from dataclasses import dataclass
from pathlib import Path

from backend.app.domain.vcf import VCFValidationError, parse_vcf

PRIMARY_SUFFIXES = (".vcf", ".vcf.gz", ".vcf.bgz")
INDEX_SUFFIXES = (".tbi", ".csi")
SUPPORTED_BUILDS = {"GRCh37", "GRCh38"}


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
    detected_build = None
    has_fileformat = False
    opener = gzip.open if path.name.lower().endswith((".gz", ".bgz")) else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("##fileformat="):
                    has_fileformat = True
                elif line.startswith("##reference="):
                    value = line.split("=", 1)[1].strip()
                    if value in SUPPORTED_BUILDS:
                        detected_build = value
                    elif "GRCh38" in value or "hg38" in value:
                        detected_build = "GRCh38"
                    elif "GRCh37" in value or "hg19" in value:
                        detected_build = "GRCh37"
                elif line.startswith("#CHROM"):
                    headers = line.split("\t")
                    break
    except (OSError, UnicodeDecodeError) as exc:
        raise VCFValidationError(f"Unable to read VCF text: {exc}") from exc
    return headers, detected_build, has_fileformat


def validate_vcf(path: str | Path) -> ValidationResult:
    p = Path(path)
    if classify_filename(p.name) != "VCF":
        return ValidationResult("INVALID", "UNSUPPORTED", 0, [], None, ["File is not a supported VCF input."], [])
    try:
        headers, detected_build, has_fileformat = _header_info(p)
        if not has_fileformat:
            raise VCFValidationError("VCF is missing the required ##fileformat header")
        if len(headers) < 8:
            raise VCFValidationError("#CHROM header must contain at least the 8 required VCF columns")
        required = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
        if headers[:8] != required:
            raise VCFValidationError("The first eight VCF columns must be #CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO")
        records = 0
        for _ in parse_vcf(str(p)):
            records += 1
        if records == 0:
            raise VCFValidationError("VCF contains no variant records")
        return ValidationResult("VALID", "VCF", records, headers[9:] if len(headers) > 9 else [], detected_build, [], [])
    except (VCFValidationError, OSError, EOFError, gzip.BadGzipFile, UnicodeError) as exc:
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
