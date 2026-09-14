from pathlib import Path

import pytest

from backend.app.domain.normalization import NormalizationError, UnsupportedVariantError, normalize_vcf_file
from backend.app.domain.reference import FastaReference
from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid


def make_reference(tmp_path: Path) -> tuple[Path, Path]:
    fasta = tmp_path / "ref.fa"
    seq = "CAAAAAC"
    fasta.write_text(">1\n" + seq + "\n", encoding="utf-8")
    # Header is 3 bytes (>1 + newline). One sequence line of 7 bases + newline.
    fai = tmp_path / "ref.fa.fai"
    fai.write_text(f"1\t{len(seq)}\t3\t{len(seq)}\t{len(seq)+1}\n", encoding="utf-8")
    return fasta, fai


def test_reference_fetch_and_ref_validation(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    with FastaReference(fasta, fai) as ref:
        assert ref.fetch("chr1", 0, 7) == "CAAAAAC"
        assert ref.base("1", 1) == "C"

        with pytest.raises(NormalizationError, match="Reference allele mismatch"):
            from backend.app.domain.normalization import normalize_alleles
            normalize_alleles(chrom="1", pos1=2, ref="C", alt="A", reference=ref)


def test_left_normalize_deletion(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t4\t.\tAA\tA\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with FastaReference(fasta, fai) as ref:
        result = normalize_vcf_file(input_vcf, output_vcf, genome_build="GRCh38", reference=ref)
    assert result["variants"][0].position == 1
    assert result["variants"][0].reference == "CA"
    assert result["variants"][0].alternate == "C"
    assert "1\t1\t.\tCA\tC" in output_vcf.read_text(encoding="utf-8")


def test_left_normalize_insertion(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t4\t.\tA\tAA\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with FastaReference(fasta, fai) as ref:
        result = normalize_vcf_file(input_vcf, output_vcf, genome_build="GRCh38", reference=ref)
    assert result["variants"][0].position == 1
    assert result["variants"][0].reference == "C"
    assert result["variants"][0].alternate == "CA"


def test_multiallelic_rejected(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with FastaReference(fasta, fai) as ref:
        with pytest.raises(UnsupportedVariantError, match="Multiallelic"):
            normalize_vcf_file(input_vcf, output_vcf, genome_build="GRCh38", reference=ref)


def test_canonical_key_and_stable_id():
    key_a = canonical_key("hg38", "chr1", 1, "CA", "C")
    key_b = canonical_key("GRCh38", "1", 1, "CA", "C")
    assert key_a == key_b == "GRCh38:1:1:CA:C"
    assert stable_variant_uuid(key_a) == stable_variant_uuid(key_b)
