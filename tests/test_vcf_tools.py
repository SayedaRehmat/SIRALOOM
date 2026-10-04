from pathlib import Path
import subprocess

import pytest

from backend.app.domain.vcf_tools import VCFToolError, normalize_vcf_with_bcftools


def make_reference(tmp_path: Path) -> Path:
    fasta = tmp_path / "GRCh38.fa"
    # Small synthetic reference used only to qualify the bcftools invocation.
    sequence = "CAAAAAC"
    fasta.write_text(f">1\n{sequence}\n", encoding="utf-8")
    # FASTA geometry: header is 3 bytes; sequence line is 7 bases + newline.
    (tmp_path / "GRCh38.fa.fai").write_text(
        f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence) + 1}\n",
        encoding="utf-8",
    )
    return fasta


def test_bcftools_reference_aware_normalization_splits_and_left_aligns(tmp_path: Path):
    if subprocess.run(["which", "bcftools"], capture_output=True).returncode != 0:
        pytest.skip("bcftools is not installed outside CI")
    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t4\t.\tAA\tA,C\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = normalize_vcf_with_bcftools(
        input_vcf,
        output_vcf,
        reference_fasta=fasta,
        expected_bcftools_version="1.19",
    )

    assert result["tool"] == "bcftools"
    assert result["tool_version"] == "bcftools 1.19"
    assert result["expected_tool_version"] == "1.19"
    assert result["reference_check"] == "error"
    assert result["multiallelic_mode"] == "SPLIT_WITH_BCFTOOLS"
    import gzip
    assert Path(str(output_vcf) + ".csi").is_file()
    with gzip.open(output_vcf, "rt", encoding="utf-8") as handle:
        lines = [
            line for line in handle.read().splitlines()
            if line and not line.startswith("#")
        ]
    assert len(lines) == 2
    assert lines[0].split("\t")[0:5] == ["1", "1", ".", "CA", "C"]
    assert lines[1].split("\t")[0:5] == ["1", "4", ".", "AA", "C"]


def test_bcftools_rejects_reference_allele_mismatch(tmp_path: Path):
    if subprocess.run(["which", "bcftools"], capture_output=True).returncode != 0:
        pytest.skip("bcftools is not installed outside CI")
    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "bad.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tC\tA\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with pytest.raises(VCFToolError, match="reference-aware normalization failed"):
        normalize_vcf_with_bcftools(
            input_vcf,
            output_vcf,
            reference_fasta=fasta,
            expected_bcftools_version="1.19",
        )


def test_bcftools_version_pin_rejects_mismatch(tmp_path: Path):
    if subprocess.run(["which", "bcftools"], capture_output=True).returncode != 0:
        pytest.skip("bcftools is not installed outside CI")
    fasta = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t4\t.\tAA\tA\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(VCFToolError, match="version mismatch"):
        normalize_vcf_with_bcftools(
            input_vcf,
            output_vcf,
            reference_fasta=fasta,
            expected_bcftools_version="0.0.0",
        )
