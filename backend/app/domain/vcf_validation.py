from __future__ import annotations

import gzip
import re
from pathlib import Path

SUPPORTED_VCF_VERSIONS = {"VCFv4.2", "VCFv4.3"}
STANDARD_COLUMNS = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
DNA_RE = re.compile(r"^[ACGTN]+$")
SYMBOLIC_RE = re.compile(r"^<[^>]+>$")
BREAKEND_RE = re.compile(r"[][A-Za-z0-9_.:-]+[][]")


class StrictVCFValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "VCF_INVALID"):
        super().__init__(message)
        self.code = code


def _open(path: str | Path):
    p = Path(path)
    return gzip.open(p, "rt", encoding="utf-8-sig") if p.name.lower().endswith((".gz", ".bgz")) else open(p, "rt", encoding="utf-8-sig")


def _validate_info(value: str, line_no: int) -> None:
    if value == ".":
        return
    if not value:
        raise StrictVCFValidationError(f"INFO is empty at line {line_no}", code="VCF_INFO_INVALID")
    for item in value.split(";"):
        if not item:
            raise StrictVCFValidationError(f"Empty INFO entry at line {line_no}", code="VCF_INFO_INVALID")
        if "=" in item:
            key, val = item.split("=", 1)
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", key) or val == "":
                raise StrictVCFValidationError(f"Malformed INFO entry at line {line_no}: {item!r}", code="VCF_INFO_INVALID")
        elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", item):
            raise StrictVCFValidationError(f"Malformed INFO flag at line {line_no}: {item!r}", code="VCF_INFO_INVALID")


def _validate_record(fields: list[str], line_no: int, reference_contigs: set[str] | None) -> tuple[str, int, list[str]]:
    if len(fields) < 8:
        raise StrictVCFValidationError(f"Expected at least 8 VCF columns at line {line_no}", code="VCF_RECORD_INVALID")
    chrom, pos_text, identifier, ref, alt, qual, filt, info = fields[:8]

    if not chrom or chrom.startswith("#"):
        raise StrictVCFValidationError(f"Invalid CHROM at line {line_no}", code="VCF_CHROM_INVALID")
    if reference_contigs is not None and chrom not in reference_contigs:
        raise StrictVCFValidationError(
            f"Contig {chrom!r} is not present in the selected reference package at line {line_no}",
            code="REFERENCE_CONTIG_MISMATCH",
        )

    try:
        pos = int(pos_text)
    except ValueError as exc:
        raise StrictVCFValidationError(f"Invalid POS at line {line_no}: {pos_text!r}", code="VCF_POS_INVALID") from exc
    if pos <= 0:
        raise StrictVCFValidationError(f"POS must be > 0 at line {line_no}", code="VCF_POS_INVALID")

    if identifier == "":
        raise StrictVCFValidationError(f"ID is empty at line {line_no}", code="VCF_ID_INVALID")
    if identifier != "." and any(not re.fullmatch(r"[A-Za-z0-9_.:-]+", x) for x in identifier.split(";")):
        raise StrictVCFValidationError(f"Malformed ID at line {line_no}: {identifier!r}", code="VCF_ID_INVALID")

    ref = ref.upper()
    if not DNA_RE.fullmatch(ref):
        raise StrictVCFValidationError(f"REF must contain only A/C/G/T/N for Phase 1 at line {line_no}", code="VCF_REF_INVALID")

    alts = [a.upper() for a in alt.split(",")]
    if not alt or any(
        not DNA_RE.fullmatch(a) and not SYMBOLIC_RE.fullmatch(a) and not BREAKEND_RE.fullmatch(a) and a != "*"
        for a in alts
    ):
        raise StrictVCFValidationError(f"Malformed ALT at line {line_no}: {alt!r}", code="VCF_ALT_INVALID")

    if qual != ".":
        try:
            q = float(qual)
        except ValueError as exc:
            raise StrictVCFValidationError(f"Invalid QUAL at line {line_no}: {qual!r}", code="VCF_QUAL_INVALID") from exc
        if q < 0:
            raise StrictVCFValidationError(f"QUAL must be non-negative at line {line_no}", code="VCF_QUAL_INVALID")

    if filt != ".":
        if not filt or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", x) for x in filt.split(";")):
            raise StrictVCFValidationError(f"Malformed FILTER at line {line_no}: {filt!r}", code="VCF_FILTER_INVALID")

    _validate_info(info, line_no)

    if len(fields) >= 9:
        fmt = fields[8]
        if not fmt:
            raise StrictVCFValidationError(f"FORMAT is empty at line {line_no}", code="VCF_FORMAT_INVALID")
        keys = fmt.split(":")
        if len(keys) != len(set(keys)) or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", k) for k in keys):
            raise StrictVCFValidationError(f"Malformed or duplicate FORMAT key at line {line_no}", code="VCF_FORMAT_INVALID")
        for sample_index, sample in enumerate(fields[9:], start=1):
            values = sample.split(":")
            if len(values) != len(keys):
                raise StrictVCFValidationError(
                    f"Sample {sample_index} has {len(values)} FORMAT values but {len(keys)} keys at line {line_no}",
                    code="VCF_SAMPLE_INVALID",
                )
            if "GT" in keys:
                gt = values[keys.index("GT")]
                if gt != ".":
                    for allele_index in re.split(r"[|/]", gt):
                        if allele_index == ".":
                            continue
                        try:
                            index = int(allele_index)
                        except ValueError as exc:
                            raise StrictVCFValidationError(
                                f"Invalid GT allele index at line {line_no}: {gt!r}",
                                code="VCF_GENOTYPE_INVALID",
                            ) from exc
                        if index < 0 or index > len(alts):
                            raise StrictVCFValidationError(
                                f"GT allele index {index} exceeds ALT count {len(alts)} at line {line_no}",
                                code="VCF_GENOTYPE_INVALID",
                            )

    return chrom, pos, alts


def validate_vcf_strict(path: str | Path, *, reference_contigs: set[str] | None = None) -> dict:
    fileformat: str | None = None
    chrom_header: list[str] | None = None
    found_header = False
    records = 0
    multiallelic = 0
    symbolic = 0
    breakends = 0
    gvcf_markers = 0
    singleton_headers: set[str] = set()

    with _open(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.rstrip("\n\r")
            if not line:
                continue
            if line.startswith("##"):
                if line.startswith("##fileformat="):
                    if fileformat is not None:
                        raise StrictVCFValidationError("Duplicate ##fileformat header", code="VCF_HEADER_INVALID")
                    fileformat = line.split("=", 1)[1]
                if line.startswith("##ALT=<ID=NON_REF"):
                    gvcf_markers += 1
                continue
            if line.startswith("#CHROM"):
                if found_header:
                    raise StrictVCFValidationError("Duplicate #CHROM header", code="VCF_HEADER_INVALID")
                columns = line.split("\t")
                if len(columns) < 8 or columns[:8] != STANDARD_COLUMNS:
                    raise StrictVCFValidationError(
                        "The #CHROM header must begin with CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO",
                        code="VCF_HEADER_INVALID",
                    )
                if len(columns) >= 9 and columns[8] != "FORMAT":
                    raise StrictVCFValidationError("Column 9 must be FORMAT when sample columns are present", code="VCF_HEADER_INVALID")
                if len(columns) > 9 and len(columns[9:]) != len(set(columns[9:])):
                    raise StrictVCFValidationError("Duplicate sample names are not allowed", code="VCF_SAMPLE_INVALID")
                chrom_header = columns
                found_header = True
                continue
            if line.startswith("#"):
                if line.startswith("##"):
                    continue
                if "=" in line:
                    key = line[2:].split("=", 1)[0]
                    if key in singleton_headers and key not in {"INFO", "FORMAT", "FILTER", "ALT", "contig"}:
                        raise StrictVCFValidationError(f"Duplicate singleton header: {key}", code="VCF_HEADER_INVALID")
                    singleton_headers.add(key)
                continue
            if not found_header:
                raise StrictVCFValidationError(
                    f"VCF data encountered before #CHROM at line {line_no}",
                    code="VCF_HEADER_INVALID",
                )
            fields = line.split("\t")
            _chrom, _pos, alts = _validate_record(fields, line_no, reference_contigs)
            records += 1
            if len(alts) > 1:
                multiallelic += 1
            for alt in alts:
                if SYMBOLIC_RE.fullmatch(alt) or alt == "*":
                    symbolic += 1
                if "[" in alt or "]" in alt:
                    breakends += 1
                if alt == "<NON_REF>":
                    gvcf_markers += 1

    if fileformat not in SUPPORTED_VCF_VERSIONS:
        raise StrictVCFValidationError(
            f"Unsupported or missing ##fileformat header: {fileformat!r}; supported versions are VCFv4.2 and VCFv4.3",
            code="VCF_FILEFORMAT_UNSUPPORTED",
        )
    if not found_header or chrom_header is None:
        raise StrictVCFValidationError("VCF is missing the #CHROM header", code="VCF_HEADER_INVALID")
    if records == 0:
        raise StrictVCFValidationError("VCF contains no variant records", code="VCF_EMPTY")

    return {
        "fileformat": fileformat,
        "records": records,
        "multiallelic_records": multiallelic,
        "symbolic_records": symbolic,
        "breakend_records": breakends,
        "gvcf_markers": gvcf_markers,
        "sample_count": max(0, len(chrom_header) - 9),
        "reference_contig_policy": "EXACT" if reference_contigs is not None else "NOT_CHECKED",
    }
