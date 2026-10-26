import gzip
import re
from dataclasses import dataclass, field
from typing import Iterator

from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.vcf_validation import declared_vcf_contig_lengths


@dataclass(frozen=True)
class VCFRecord:
    chrom: str
    pos: int
    ref: str
    alt: str
    raw: str
    sample_calls: dict[str, dict] = field(default_factory=dict)

class VCFValidationError(ValueError):
    pass

def open_text(path: str):
    # Preserve BOMs so the parser can reject them: the VCF specification forbids a
    # byte-order mark, and silently stripping it would make malformed input look valid.
    if path.endswith((".gz", ".bgz")):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rt", encoding="utf-8")

def parse_vcf(path: str) -> Iterator[VCFRecord]:
    found_header = False
    sample_names: list[str] = []
    declared_contig_lengths = declared_vcf_contig_lengths(path)
    with open_text(path) as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.rstrip("\n")
            if line_no == 1 and line.startswith("\ufeff"):
                raise VCFValidationError("VCF files must not contain a UTF-8 byte-order mark")
            if not line:
                continue
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                found_header = True
                sample_names = line.split("\t")[9:]
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
            if pos < 0:
                raise VCFValidationError(f"POS must be non-negative at line {line_no}")
            if not re.fullmatch(r"[A-Za-z*.]+", ref) or not re.fullmatch(r"[A-Za-z*.,<>\[\]():]+", alt):
                raise VCFValidationError(f"Invalid REF/ALT allele syntax at line {line_no}")
            if not ref or not alt:
                raise VCFValidationError(f"REF/ALT missing at line {line_no}")
            if alt == ".":
                continue
            if "." in alt.split(","):
                raise VCFValidationError(
                    f"ALT '.' cannot be combined with alternate alleles at line {line_no}"
                )
            if pos == 0 or pos == declared_contig_lengths.get(chrom, -2) + 1:
                # Telomere sentinels are not allele coordinates suitable for
                # canonical small-variant processing. N+1 is provisional
                # until the pinned reference verifies the declared length.
                continue
            sample_calls: dict[str, dict] = {}
            if len(fields) > 8 and sample_names:
                format_keys = [] if fields[8] in {"", "."} else fields[8].split(":")
                for sample_name, sample_value in zip(sample_names, fields[9:]):
                    values = sample_value.split(":")
                    call_fields = dict(zip(format_keys, values))
                    genotype = call_fields.get("GT")
                    sample_calls[sample_name] = {
                        "sample_name": sample_name,
                        "genotype": genotype,
                        "zygosity": _zygosity(genotype),
                        "phase": (
                            "PHASED" if genotype and "|" in genotype
                            else "UNPHASED" if genotype and "/" in genotype
                            else "UNSPECIFIED"
                        ),
                        "phase_set": call_fields.get("PS"),
                        "format_values": {
                            key: call_fields[key]
                            for key in ("DP", "GQ", "AD", "PL", "GL", "GP", "PS")
                            if key in call_fields
                        },
                        "status": (
                            "AVAILABLE"
                            if genotype and _zygosity(genotype) not in {
                                "NO_CALL", "PARTIAL_CALL", "INVALID_CALL"
                            }
                            else "MISSING_OR_PARTIAL"
                        ),
                    }
            for alt_allele in alt.split(","):
                yield VCFRecord(chrom, pos, ref, alt_allele, line, sample_calls)


def _zygosity(genotype: str | None) -> str:
    if not genotype or genotype == ".":
        return "NO_CALL"
    alleles = re.split(r"[/|]", genotype)
    if not alleles:
        return "INVALID_CALL"
    if all(allele == "." for allele in alleles):
        return "NO_CALL"
    if any(allele == "." for allele in alleles):
        return "PARTIAL_CALL"
    try:
        indexes = [int(allele) for allele in alleles]
    except ValueError:
        return "INVALID_CALL"
    if any(index < 0 for index in indexes):
        return "INVALID_CALL"
    if all(index == 0 for index in indexes):
        return "HOMOZYGOUS_REFERENCE" if len(indexes) > 1 else "REFERENCE_CALL"
    if len(indexes) == 1:
        return "HAPLOID_ALTERNATE"
    if all(index != 0 for index in indexes):
        return "HOMOZYGOUS_ALTERNATE" if len(set(indexes)) == 1 else "MULTIPLE_ALTERNATE_ALLELES"
    return "HETEROZYGOUS"

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
