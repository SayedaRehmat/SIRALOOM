from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


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
