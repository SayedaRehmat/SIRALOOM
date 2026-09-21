from dataclasses import dataclass
from typing import Iterator
import gzip
import re
from backend.app.domain.schemas import CanonicalVariant

@dataclass(frozen=True)
class VCFRecord:
    chrom: str
    pos: int
    ref: str
    alt: str
    raw: str

class VCFValidationError(ValueError):
    pass

def open_text(path: str):
    # utf-8-sig transparently strips a leading UTF-8 byte-order-mark if one is present
    # (common in files that have passed through Windows/Excel/some download tools) and
    # behaves identically to plain utf-8 for files that don't have one -- so this is a
    # strict improvement, not a behavior change for already-working files. Without this,
    # a BOM-prefixed file fails validation with a misleading "missing ##fileformat
    # header" error, because the BOM sits invisibly in front of the first line.
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8-sig")
    return open(path, "rt", encoding="utf-8-sig")

def parse_vcf(path: str) -> Iterator[VCFRecord]:
    found_header = False
    with open_text(path) as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                found_header = True
                continue
            if line.startswith("#"):
                continue
            if not found_header:
                raise VCFValidationError(f"VCF data encountered before #CHROM header at line {line_no}")
            fields = line.split("\t")
            if len(fields) < 8:
                raise VCFValidationError(f"Malformed VCF record at line {line_no}: expected at least 8 tab-separated columns")
            chrom, pos_s, _id, ref, alt = fields[:5]
            try:
                pos = int(pos_s)
            except ValueError as exc:
                raise VCFValidationError(f"Invalid POS at line {line_no}: {pos_s!r}") from exc
            if pos <= 0:
                raise VCFValidationError(f"POS must be > 0 at line {line_no}")
            if not re.fullmatch(r"[A-Za-z*.]+", ref) or not re.fullmatch(r"[A-Za-z*.,<>\[\]():]+", alt):
                raise VCFValidationError(f"Invalid REF/ALT allele syntax at line {line_no}")
            if not ref or not alt:
                raise VCFValidationError(f"REF/ALT missing at line {line_no}")
            for alt_allele in alt.split(","):
                yield VCFRecord(chrom, pos, ref, alt_allele, line)

def validate_and_extract(path: str, genome_build: str) -> list[CanonicalVariant]:
    records = list(parse_vcf(path))
    if not records:
        raise VCFValidationError("VCF contains no variant records")
    variants = []
    for r in records:
        variants.append(CanonicalVariant(
            genome_build=genome_build,
            chromosome=r.chrom,
            position=r.pos,
            reference=r.ref,
            alternate=r.alt,
        ))
    return variants
