from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import gzip

from backend.app.domain.reference import FastaReference, ReferenceError
from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.variant_identity import canonical_key

DNA_ALLELES = set("ACGTN")


class NormalizationError(ValueError):
    pass


class UnsupportedVariantError(NormalizationError):
    pass


@dataclass(frozen=True)
class NormalizationResult:
    variant: CanonicalVariant
    original_chromosome: str
    original_position: int
    original_reference: str
    original_alternate: str
    changed: bool


def normalize_alleles(
    *,
    chrom: str,
    pos1: int,
    ref: str,
    alt: str,
    reference: FastaReference,
) -> NormalizationResult:
    ref = ref.upper()
    alt = alt.upper()
    if not ref or not alt:
        raise NormalizationError("REF and ALT must be non-empty")
    if any(base not in DNA_ALLELES for base in ref + alt):
        raise UnsupportedVariantError(
            f"Unsupported symbolic/non-DNA allele at {chrom}:{pos1} {ref}>{alt}"
        )

    canonical_chrom = reference.resolve_contig(chrom)
    observed_ref = reference.fetch(canonical_chrom, pos1 - 1, pos1 - 1 + len(ref))
    if observed_ref != ref:
        raise NormalizationError(
            f"Reference allele mismatch at {chrom}:{pos1}: VCF REF={ref}, reference={observed_ref}"
        )

    original = (canonical_chrom, pos1, ref, alt)

    # Minimal representation. Do not allow either allele to become empty.
    while len(ref) > 1 and len(alt) > 1 and ref[-1] == alt[-1]:
        ref = ref[:-1]
        alt = alt[:-1]

    while len(ref) > 1 and len(alt) > 1 and ref[0] == alt[0]:
        ref = ref[1:]
        alt = alt[1:]
        pos1 += 1

    # Left-align simple indels in repeat contexts using the reference sequence.
    # This follows the minimal-representation + left-shifting principle used by
    # standard VCF normalization tools. No symbolic/SV alleles are accepted here.
    if len(ref) != len(alt):
        while pos1 > 1 and ref[-1] == alt[-1]:
            previous = reference.base(canonical_chrom, pos1 - 1)
            ref = previous + ref
            alt = previous + alt
            pos1 -= 1
            while len(ref) > 1 and len(alt) > 1 and ref[-1] == alt[-1]:
                ref = ref[:-1]
                alt = alt[:-1]

    # Re-check the final REF against the reference.
    observed_ref = reference.fetch(canonical_chrom, pos1 - 1, pos1 - 1 + len(ref))
    if observed_ref != ref:
        raise NormalizationError(
            f"Normalized REF mismatch at {canonical_chrom}:{pos1}: REF={ref}, reference={observed_ref}"
        )
    if ref == alt:
        raise NormalizationError("REF and ALT become identical after normalization")

    variant = CanonicalVariant(
        genome_build="TEMP",
        chromosome=canonical_chrom,
        position=pos1,
        reference=ref,
        alternate=alt,
        normalization_status="NORMALIZED",
        original_chromosome=original[0],
        original_position=original[1],
        original_reference=original[2],
        original_alternate=original[3],
    )
    return NormalizationResult(
        variant=variant,
        original_chromosome=original[0],
        original_position=original[1],
        original_reference=original[2],
        original_alternate=original[3],
        changed=original != (canonical_chrom, pos1, ref, alt),
    )


def normalize_record(*, chrom: str, pos1: int, ref: str, alt: str, genome_build: str, reference: FastaReference) -> NormalizationResult:
    result = normalize_alleles(
        chrom=chrom,
        pos1=pos1,
        ref=ref,
        alt=alt,
        reference=reference,
    )
    build = genome_build
    variant = result.variant.model_copy(update={
        "genome_build": build,
        "variant_key": canonical_key(build, result.variant.chromosome, result.variant.position, result.variant.reference, result.variant.alternate),
    })
    return NormalizationResult(
        variant=variant,
        original_chromosome=result.original_chromosome,
        original_position=result.original_position,
        original_reference=result.original_reference,
        original_alternate=result.original_alternate,
        changed=result.changed,
    )


def _split_vcf_alt(alt: str) -> list[str]:
    if "," in alt:
        raise UnsupportedVariantError(
            "Multiallelic VCF records are not yet accepted by the reference-aware Phase 1 normalizer. "
            "Use a validated multiallelic splitter (for example bcftools norm) before SIRALOOM."
        )
    return [alt]


def normalize_vcf_file(input_path: str | Path, output_path: str | Path, *, genome_build: str, reference: FastaReference, collect_variants: bool = True):
    """Stream-normalize a biallelic VCF without loading it into memory."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records = 0
    changed = 0
    variants: list[CanonicalVariant] | None = [] if collect_variants else None
    header_seen = False

    src_open = gzip.open if input_path.suffix == ".gz" else open
    dst_open = gzip.open if output_path.suffix == ".gz" else open
    with src_open(input_path, "rt", encoding="utf-8") as src, dst_open(output_path, "wt", encoding="utf-8", newline="") as dst:
        injected = False
        for line_no, raw_line in enumerate(src, 1):
            line = raw_line.rstrip("\n")
            if line.startswith("##"):
                dst.write(raw_line)
                continue
            if line.startswith("#CHROM"):
                if not injected:
                    dst.write(f"##SIRALOOM_normalization_version=1.0\n")
                    dst.write(f"##SIRALOOM_reference_build={genome_build}\n")
                    injected = True
                dst.write(raw_line)
                header_seen = True
                continue
            if line.startswith("#"):
                dst.write(raw_line)
                continue
            if not header_seen:
                raise NormalizationError(f"VCF data encountered before #CHROM at line {line_no}")

            fields = line.split("\t")
            if len(fields) < 5:
                raise NormalizationError(f"Malformed VCF record at line {line_no}")
            chrom, pos_s, vid, ref, alt = fields[:5]
            try:
                pos1 = int(pos_s)
            except ValueError as exc:
                raise NormalizationError(f"Invalid POS at line {line_no}: {pos_s!r}") from exc
            alts = _split_vcf_alt(alt)
            for alt_allele in alts:
                result = normalize_alleles(chrom=chrom, pos1=pos1, ref=ref, alt=alt_allele, reference=reference)
                v = result.variant.model_copy(update={"genome_build": genome_build})
                if variants is not None:
                    variants.append(v)
                records += 1
                changed += int(result.changed)
                new_fields = list(fields)
                new_fields[0] = v.chromosome
                new_fields[1] = str(v.position)
                new_fields[3] = v.reference
                new_fields[4] = v.alternate
                # A multi-allelic split is forbidden above; therefore sample/genotype
                # fields remain semantically aligned here.
                dst.write("\t".join(new_fields) + "\n")

    if not header_seen:
        raise NormalizationError("VCF is missing the #CHROM header")
    if records == 0:
        raise NormalizationError("VCF contains no supported variant records")
    return {
        "record_count": records,
        "changed_count": changed,
        "variants": variants if variants is not None else None,
        "output_path": str(output_path),
    }


def iter_normalized_vcf(path: str | Path, genome_build: str):
    """Yield canonical variants one record at a time from a normalized VCF.

    The iterator deliberately does not materialize the full variant set. It is the
    streaming boundary used by the M13 workflow for WES/WGS-scale inputs.
    """
    from backend.app.domain.vcf import parse_vcf
    for record in parse_vcf(str(path)):
        yield CanonicalVariant(
            genome_build=genome_build,
            chromosome=record.chrom,
            position=record.pos,
            reference=record.ref,
            alternate=record.alt,
            normalization_status="NORMALIZED",
            variant_key=canonical_key(genome_build, record.chrom, record.pos, record.ref, record.alt),
        )
