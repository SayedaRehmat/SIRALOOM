from __future__ import annotations

import gzip
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.app.domain.reference import FastaReference, ReferenceError
from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.variant_identity import canonical_key


class NormalizationError(ValueError):
    code = "NORMALIZATION_FAILED"


class UnsupportedVariantError(NormalizationError):
    code = "UNSUPPORTED_VARIANT"


@dataclass(frozen=True)
class NormalizationResult:
    variant: CanonicalVariant
    original_chromosome: str
    original_position: int
    original_reference: str
    original_alternate: str
    changed: bool


def bcftools_version() -> str:
    executable = shutil.which("bcftools")
    if not executable:
        raise NormalizationError(
            "bcftools is required for production normalization but is not installed."
        )
    completed = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise NormalizationError(
            f"Unable to determine bcftools version: {(completed.stderr or '').strip()}"
        )
    first_line = (completed.stdout or "").splitlines()[0] if completed.stdout else ""
    match = re.search(r"bcftools\s+([0-9][^\s]*)", first_line, re.I)
    return match.group(1) if match else first_line.strip()


def _output_type(path: Path) -> str:
    return "z" if path.name.lower().endswith((".vcf.gz", ".vcf.bgz", ".bcf")) else "v"


def _count_records(path: Path) -> int:
    opener = gzip.open if path.name.lower().endswith((".gz", ".bgz")) else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return sum(1 for line in handle if line and not line.startswith("#"))


def _assert_reference_index(reference: FastaReference) -> None:
    if not reference.fasta_path.is_file():
        raise ReferenceError(f"Reference FASTA not found: {reference.fasta_path}")
    if not reference.fai_path.is_file():
        raise ReferenceError(f"Reference FASTA index (.fai) not found: {reference.fai_path}")


def normalize_vcf_file(
    input_path: str | Path,
    output_path: str | Path,
    *,
    genome_build: str,
    reference: FastaReference,
    collect_variants: bool = True,
):
    """Production normalization boundary backed by the standard bcftools implementation."""
    if genome_build not in {"GRCh37", "GRCh38"}:
        raise NormalizationError(f"Unsupported genome build: {genome_build}")

    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.is_file():
        raise NormalizationError(f"Input VCF does not exist: {input_path}")

    _assert_reference_index(reference)

    executable = shutil.which("bcftools")
    if not executable:
        raise NormalizationError(
            "bcftools is required for SIRALOOM normalization but is not installed."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    version = bcftools_version()
    output_type = _output_type(output_path)
    command = [
        executable, "norm",
        "-f", str(reference.fasta_path),
        "-m", "-any",
        "-O", output_type,
        "-o", str(output_path),
        str(input_path),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=None,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown bcftools error").strip()
        raise NormalizationError(f"bcftools norm failed for {genome_build}: {detail}")

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise NormalizationError("bcftools norm completed without producing an output VCF.")

    record_count = _count_records(output_path)
    if record_count == 0:
        raise NormalizationError("Normalized VCF contains no variant records.")

    variants = list(iter_normalized_vcf(output_path, genome_build)) if collect_variants else None
    return {
        "record_count": record_count,
        "changed_count": None,
        "variants": variants,
        "output_path": str(output_path),
        "tool": "bcftools",
        "tool_version": version,
        "command": command,
        "stderr": (completed.stderr or "").strip(),
        "normalization_policy": {
            "reference_aware": True,
            "split_multiallelic": True,
            "check_ref": "error",
            "atomize": False,
            "remove_duplicates": False,
            "fix_ref": False,
        },
    }


def iter_normalized_vcf(path: str | Path, genome_build: str):
    """Yield canonical variants one record at a time from a normalized VCF."""
    from backend.app.domain.vcf import parse_vcf

    for record in parse_vcf(str(path)):
        yield CanonicalVariant(
            genome_build=genome_build,
            chromosome=record.chrom,
            position=record.pos,
            reference=record.ref,
            alternate=record.alt,
            normalization_status="NORMALIZED",
            variant_key=canonical_key(
                genome_build, record.chrom, record.pos, record.ref, record.alt
            ),
        )
