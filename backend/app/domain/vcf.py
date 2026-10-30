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

def parse_vcf(
    path: str,
    *,
    sample_name: str | None = None,
    allow_unselected_multisample: bool = False,
) -> Iterator[VCFRecord]:
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
                if sample_name is not None and sample_name not in sample_names:
                    raise VCFValidationError(
                        f"Selected VCF sample {sample_name!r} is not present in the #CHROM header"
                    )
                if (
                    len(sample_names) > 1
                    and sample_name is None
                    and not allow_unselected_multisample
                ):
                    raise VCFValidationError(
                        "Multisample VCF parsing requires an explicit sample_name; "
                        "refusing to combine different individuals' genotype calls."
                    )
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
                selected_samples = (
                    [sample_name] if sample_name is not None else sample_names
                )
                sample_indexes = {name: sample_names.index(name) for name in selected_samples}
                for selected_name in selected_samples:
                    sample_value = fields[9 + sample_indexes[selected_name]]
                    values = sample_value.split(":")
                    # VCF permits omitted trailing FORMAT values; preserve the
                    # declared schema by materializing those values as missing.
                    call_fields = {
                        key: values[index] if index < len(values) else "."
                        for index, key in enumerate(format_keys)
                    }
                    genotype = call_fields.get("GT")
                    sample_calls[selected_name] = {
                        "sample_name": selected_name,
                        "genotype": genotype,
                        "zygosity": _zygosity(genotype),
                        "phase": (
                            "PARTIALLY_PHASED"
                            if genotype and "|" in genotype and "/" in genotype
                            else "PHASED" if genotype and "|" in genotype
                            else "UNPHASED" if genotype and "/" in genotype
                            else "UNSPECIFIED"
                        ),
                        "phase_set": call_fields.get("PS"),
                        # Retain standard, local-allele, caller-specific, and
                        # future FORMAT fields for traceability rather than
                        # silently dropping data that the interpretation layer
                        # may need to evaluate or review.
                        "format_values": {
                            key: value for key, value in call_fields.items() if key != "GT"
                        },
                        "status": (
                            "AVAILABLE"
                            if genotype and _zygosity(genotype) not in {
                                "NO_CALL", "PARTIAL_CALL", "INVALID_CALL"
                            }
                            else "MISSING_OR_PARTIAL"
                        ),
                    }
            alt_alleles = alt.split(",")
            for source_alt_index, alt_allele in enumerate(alt_alleles, start=1):
                per_alt_calls = _sample_calls_for_alt(
                    sample_calls,
                    source_alt_index=source_alt_index,
                    source_alt_count=len(alt_alleles),
                )
                yield VCFRecord(chrom, pos, ref, alt_allele, line, per_alt_calls)


def _sample_calls_for_alt(
    sample_calls: dict[str, dict],
    *,
    source_alt_index: int,
    source_alt_count: int,
) -> dict[str, dict]:
    """Project source genotypes onto one ALT while retaining the original call.

    This is a per-ALT interpretation projection, not a rewritten VCF record.
    The selected ALT is mapped to 1, REF and other ALT alleles to 0, matching
    the declared multiallelic overlap policy. Original genotype and FORMAT
    values remain in source-allele space for evidence and traceability.
    """
    projected: dict[str, dict] = {}
    for sample_name, source_call in sample_calls.items():
        call = dict(source_call)
        source_genotype = call.get("genotype")
        call["source_genotype"] = source_genotype
        call["source_alt_index"] = source_alt_index
        call["source_alt_count"] = source_alt_count
        if source_genotype:
            # Preserve phase separators (including VCFv4.4+ leading separators)
            # while remapping allele indices: REF -> 0, selected ALT -> 1,
            # and other ALT alleles -> 0 under the declared overlap policy.
            tokens = re.split(r"([/|])", source_genotype)
            remapped_tokens: list[str] = []
            for token in tokens:
                if token in {"/", "|"} or token == "" or token == ".":
                    remapped_tokens.append(token)
                    continue
                if token.isdigit():
                    allele_index = int(token)
                    if allele_index == 0:
                        remapped_tokens.append("0")
                    elif 1 <= allele_index <= source_alt_count:
                        remapped_tokens.append("1" if allele_index == source_alt_index else "0")
                    else:
                        # Keep invalid indices visible for strict validation or
                        # explicit review; do not silently reinterpret them.
                        remapped_tokens.append(token)
                else:
                    remapped_tokens.append(token)
            projected_genotype = "".join(remapped_tokens)
            # Keep genotype/zygosity/phase/status in the original source-allele
            # space. A per-ALT GT projection is an additional interpretation,
            # not a replacement for the source call: FORMAT values such as AD
            # (Number=R) and PL (Number=G) remain indexed to the original ALT list.
            call["projected_genotype"] = projected_genotype
            call["projected_zygosity"] = _zygosity(projected_genotype)
            call["projected_phase"] = (
                "PARTIALLY_PHASED"
                if "|" in projected_genotype and "/" in projected_genotype
                else "PHASED" if "|" in projected_genotype
                else "UNPHASED" if "/" in projected_genotype
                else "UNSPECIFIED"
            )
            call["projected_status"] = (
                "AVAILABLE"
                if projected_genotype and _zygosity(projected_genotype) not in {
                    "NO_CALL", "PARTIAL_CALL", "INVALID_CALL"
                }
                else "MISSING_OR_PARTIAL"
            )
        projected[sample_name] = call
    return projected


def _zygosity(genotype: str | None) -> str:
    if not genotype or genotype == ".":
        return "NO_CALL"
    # VCFv4.4+ permits a leading phase separator before the first allele.
    # Strict version-aware validation decides whether the input version permits it.
    if genotype[:1] in {"/", "|"}:
        genotype = genotype[1:]
    alleles = re.split(r"[/|]", genotype)
    if not genotype or any(allele == "" for allele in alleles):
        return "INVALID_CALL"
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

def validate_and_extract(
    path: str,
    genome_build: str,
    *,
    sample_name: str | None = None,
) -> list[CanonicalVariant]:
    records = list(parse_vcf(path, sample_name=sample_name))
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
