from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


MNV_POLICY = "PRESERVE"
MULTIALLELIC_POLICY = "SPLIT_WITH_BCFTOOLS"


class VCFToolError(RuntimeError):
    pass


def bcftools_available() -> bool:
    return shutil.which("bcftools") is not None


def has_multiallelic_records(path: str | Path) -> bool:
    import gzip

    p = Path(path)
    opener = gzip.open if p.name.lower().endswith((".gz", ".bgz")) else open
    with opener(p, "rt", encoding="utf-8-sig") as fh:
        for line in fh:
            if not line or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) >= 5 and "," in fields[4]:
                return True
    return False


def split_multiallelic_vcf(input_path: str | Path, output_path: str | Path) -> dict:
    """
    Split multiallelic records into biallelic records without doing reference-aware
    normalization. bcftools performs genotype/allele bookkeeping; SIRALOOM's
    Ensembl-backed normalizer remains responsible for reference validation and
    left-alignment.

    This deliberately does not use -f: bcftools requires a local FASTA for
    reference-aware normalization, while SIRALOOM currently uses Ensembl REST.
    """
    if not bcftools_available():
        raise VCFToolError(
            "bcftools is required to split multiallelic VCF records in the deployed "
            "normalization pipeline."
        )

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "bcftools", "norm", "-m", "-any", "-N", "-Ov",
        "-o", str(output_path), str(input_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown bcftools error").strip()
        raise VCFToolError(f"bcftools could not split the multiallelic VCF: {detail}")

    return {
        "tool": "bcftools",
        "operation": "split_multiallelic",
        "command": "bcftools norm -m -any -N",
        "stderr": (completed.stderr or "").strip(),
    }


def normalize_vcf_with_bcftools(
    input_path: str | Path,
    output_path: str | Path,
    *,
    reference_fasta: str | Path,
    timeout_seconds: int = 1800,
) -> dict:
    """
    Perform reference-aware VCF normalization with pinned local reference data.

    This is the production normalization boundary for SIRALOOM. bcftools handles
    allele-aware multiallelic splitting and reference-aware left normalization in
    one operation, so Python does not reimplement normalization semantics.
    """
    if not bcftools_available():
        raise VCFToolError(
            "bcftools is required for SIRALOOM reference-aware VCF normalization."
        )

    input_path = Path(input_path)
    output_path = Path(output_path)
    reference_fasta = Path(reference_fasta)

    if not input_path.is_file():
        raise VCFToolError(f"VCF input does not exist: {input_path}")
    if not reference_fasta.is_file():
        raise VCFToolError(f"Reference FASTA does not exist: {reference_fasta}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    version_result = subprocess.run(
        ["bcftools", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if version_result.returncode != 0:
        detail = (version_result.stderr or version_result.stdout or "unknown bcftools error").strip()
        raise VCFToolError(f"Unable to determine bcftools version: {detail}")

    version_line = next(
        (line.strip() for line in version_result.stdout.splitlines() if line.strip()),
        "unknown",
    )

    output_type = "z" if output_path.name.lower().endswith((".gz", ".bgz")) else "v"
    command = [
        "bcftools",
        "norm",
        "-f",
        str(reference_fasta),
        "-c",
        "e",
        "-m",
        "-any",
        f"-O{output_type}",
        "-o",
        str(output_path),
        str(input_path),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=max(1, int(timeout_seconds)),
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown bcftools normalization error").strip()
        raise VCFToolError(
            f"bcftools reference-aware normalization failed "
            f"(exit {completed.returncode}): {detail}"
        )

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise VCFToolError("bcftools reported success but produced no normalized VCF.")

    return {
        "tool": "bcftools",
        "tool_version": version_line,
        "operation": "reference_aware_normalization",
        "command": " ".join(command),
        "reference_fasta": str(reference_fasta),
        "reference_check": "error",
        "multiallelic_mode": MULTIALLELIC_POLICY,
        "mnv_policy": MNV_POLICY,
        "stderr": (completed.stderr or "").strip(),
    }


def classify_records(path: str | Path) -> dict:
    import gzip

    p = Path(path)
    opener = gzip.open if p.name.lower().endswith((".gz", ".bgz")) else open
    multiallelic = 0
    symbolic = 0
    gvcf_markers = 0
    records = 0
    with opener(p, "rt", encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.startswith("##GVCFBlock") or "##ALT=<ID=NON_REF" in line:
                gvcf_markers += 1
            if line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 5:
                continue
            records += 1
            alts = fields[4].split(",")
            if len(alts) > 1:
                multiallelic += 1
            if any(
                alt.startswith("<") or alt.startswith("*") or "[" in alt or "]" in alt
                for alt in alts
            ):
                symbolic += 1
    return {
        "records": records,
        "multiallelic_records": multiallelic,
        "symbolic_records": symbolic,
        "gvcf_markers": gvcf_markers,
    }
