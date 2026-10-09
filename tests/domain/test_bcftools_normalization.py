from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.domain.bcftools_normalization import (
    BcftoolsExecutionError,
    BcftoolsUnavailableError,
    UnsupportedVariantTypeError,
    _inspect_small_variant_scope,
    normalize_vcf_with_bcftools,
)


def write_vcf(path: Path, alt: str = "G", info: str = ".") -> None:
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=100>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t10\t.\tA\t{alt}\t.\tPASS\t{info}\n",
        encoding="utf-8",
    )


def test_gvcf_reference_confidence_is_routed(tmp_path: Path):
    path = tmp_path / "input.vcf"
    write_vcf(path, "<NON_REF>", "END=20")
    with pytest.raises(UnsupportedVariantTypeError, match="GVCF"):
        _inspect_small_variant_scope(path)


def test_symbolic_sv_is_routed(tmp_path: Path):
    path = tmp_path / "input.vcf"
    write_vcf(path, "<DEL>")
    with pytest.raises(UnsupportedVariantTypeError, match="structural"):
        _inspect_small_variant_scope(path)


def test_missing_bcftools_is_explicit(tmp_path: Path):
    input_path = tmp_path / "input.vcf"
    output_path = tmp_path / "output.vcf.gz"
    write_vcf(input_path)
    fasta = tmp_path / "GRCh38.fa"
    fasta.write_text(">1\n" + "A" * 100 + "\n", encoding="utf-8")
    (tmp_path / "GRCh38.fa.fai").write_text("1\t100\t5\t100\t101\n", encoding="utf-8")

    with patch("backend.app.domain.bcftools_normalization.shutil.which", return_value=None):
        with pytest.raises(BcftoolsUnavailableError, match="bcftools is not installed"):
            normalize_vcf_with_bcftools(
                input_path,
                output_path,
                genome_build="GRCh38",
                reference=type("Ref", (), {"fasta_path": fasta})(),
            )


def test_remote_reference_provider_is_not_used_for_tool_normalization(tmp_path: Path):
    input_path = tmp_path / "input.vcf"
    output_path = tmp_path / "output.vcf"
    write_vcf(input_path)

    with patch("backend.app.domain.bcftools_normalization.shutil.which", return_value="/usr/bin/bcftools"):
        with pytest.raises(BcftoolsExecutionError, match="local reference FASTA"):
            normalize_vcf_with_bcftools(
                input_path,
                output_path,
                genome_build="GRCh38",
                reference=object(),
            )
