from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import gzip
import re
import shutil
import subprocess

from backend.app.domain.vcf import parse_vcf
from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.variant_identity import canonical_key


class BcftoolsError(RuntimeError):
    """Base error for the external bcftools normalization boundary."""


class BcftoolsUnavailableError(BcftoolsError):
    pass


class BcftoolsExecutionError(BcftoolsError):
    pass


class UnsupportedVariantTypeError(BcftoolsError):
    """Input is a valid VCF construct but belongs to another variant workflow."""


@dataclass(frozen=True)
class BcftoolsNormalizationResult:
    output_path: str
    input_record_count: int
    output_record_count: int
    normalized_record_count: int
    split_record_count: int
    variants: list[CanonicalVariant] | None


_SYMBOLIC_ALT = re.compile(r"^<[^>]+>$")
_BREAKEND_ALT = re.compile(r"[[]]")


def _count_variant_records(path: Path) -> int:
    count = 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig") as handle:
        for raw in handle:
            if raw and not raw.startswith("#"):
                count += 1
    return count


def _inspect_small_variant_scope(path: Path) -> None:
    """Reject variant classes that require a different laboratory workflow.

    bcftools is intentionally used here as the standards-based small-variant
    normalizer. Structural variants and GVCF reference-confidence records are
    not silently forced through that workflow.
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw or raw.startswith("#"):
                continue
            fields = raw.rstrip("\n").split("\t")
            if len(fields) < 5:
                continue
            alt = fields[4]
            if "<NON_REF>" in alt or "<*>" in alt or "END=" in fields[7] if len(fields) >= 8 else False:
                raise UnsupportedVariantTypeError(
                    f"GVCF/reference-confidence content detected at line {line_no}; "
                    "route the input through a GVCF-specific workflow."
                )
            for allele in alt.split(","):
                if _SYMBOLIC_ALT.fullmatch(allele) or _BREAKEND_ALT.search(allele):
                    raise UnsupportedVariantTypeError(
                        f"Symbolic/structural-variant ALT detected at line {line_no}: {allele}. "
                        "Route the input through the structural-variant workflow."
                    )


def _reference_fasta(reference: object) -> Path:
    fasta_path = getattr(reference, "fasta_path", None)
    if fasta_path is None:
        raise BcftoolsExecutionError(
            "bcftools normalization requires a local reference FASTA. "
            "A remote sequence provider is not a substitute for the reference file "
            "used by the normalization tool."
        )
    fasta = Path(fasta_path)
    fai = Path(f"{fasta}.fai")
    if not fasta.is_file():
        raise BcftoolsExecutionError(f"Reference FASTA not found: {fasta}")
    if not fai.is_file():
        raise BcftoolsExecutionError(
            f"Reference FASTA index not found: {fai}. "
            "Create and validate the .fai before normalization."
        )
    return fasta


def _output_type(path: Path) -> str:
    if path.suffix == ".gz":
        return "z"
    if path.suffix == ".bcf":
        return "b"
    return "v"


def _ensure_siraloom_header(path: Path, genome_build: str) -> None:
    """Add SIRALOOM provenance before #CHROM without rewriting variant records."""
    opener = gzip.open if path.suffix == ".gz" else open
    lines: list[str] = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for raw in handle:
            if raw.startswith("#CHROM"):
                lines.append(f"##SIRALOOM_normalization_workflow=bcftools_norm\\n")
                lines.append(f"##SIRALOOM_reference_build={genome_build}\\n")
                lines.append(raw)
            else:
                lines.append(raw)
    tmp = path.with_name(f"{path.name}.siraloom-header.tmp")
    tmp_opener = gzip.open if path.suffix == ".gz" else open
    with tmp_opener(tmp, "wt", encoding="utf-8", newline="") as handle:
        handle.writelines(lines)
    tmp.replace(path)


def normalize_vcf_with_bcftools(
    input_path: str | Path,
    output_path: str | Path,
    *,
    genome_build: str,
    reference: object,
    collect_variants: bool = True,
) -> BcftoolsNormalizationResult:
    """Normalize ordinary SNV/small-indel VCF with the established bcftools norm implementation.

    The command deliberately uses:
      -f reference.fa       reference-aware normalization
      -c e                  fail on REF/reference mismatches
      -m -both              split multiallelic SNP and indel records
      --old-rec-tag ...    retain source-record provenance after splitting

    No SIRALOOM-specific allele normalization algorithm is performed here.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        raise BcftoolsExecutionError(f"VCF input not found: {input_path}")

    executable = shutil.which("bcftools")
    if executable is None:
        raise BcftoolsUnavailableError(
            "bcftools is not installed in the worker image. "
            "The small-variant normalization stage cannot run."
        )

    fasta = _reference_fasta(reference)
    _inspect_small_variant_scope(input_path)

    input_count = _count_variant_records(input_path)
    if input_count == 0:
        raise BcftoolsExecutionError("VCF contains no variant records")

    cmd = [
        executable,
        "norm",
        "-f", str(fasta),
        "-c", "e",
        "-m", "-both",
        "--old-rec-tag", "SIRALOOM_ORIGINAL",
        "-O", _output_type(output_path),
        "-o", str(output_path),
        str(input_path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise BcftoolsExecutionError(f"Unable to execute bcftools: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise BcftoolsExecutionError(
            f"bcftools norm failed with exit code {completed.returncode}: {detail}"
        )

    if not output_path.is_file():
        raise BcftoolsExecutionError(
            f"bcftools reported success but did not create the output: {output_path}"
        )

    _ensure_siraloom_header(output_path, genome_build)
    output_count = _count_variant_records(output_path)

    variants: list[CanonicalVariant] | None = [] if collect_variants else None
    if variants is not None:
        for record in parse_vcf(str(output_path)):
            variants.append(
                CanonicalVariant(
                    genome_build=genome_build,
                    chromosome=record.chrom,
                    position=record.pos,
                    reference=record.ref,
                    alternate=record.alt,
                    normalization_status="NORMALIZED",
                    variant_key=canonical_key(
                        genome_build,
                        record.chrom,
                        record.pos,
                        record.ref,
                        record.alt,
                    ),
                )
            )

    # A split multiallelic record can increase the output record count. The tool,
    # not SIRALOOM, owns the exact allele/genotype remapping semantics.
    split_count = max(0, output_count - input_count)
    normalized_count = output_count

    return BcftoolsNormalizationResult(
        output_path=str(output_path),
        input_record_count=input_count,
        output_record_count=output_count,
        normalized_record_count=normalized_count,
        split_record_count=split_count,
        variants=variants,
    )
