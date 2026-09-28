from pathlib import Path
import shutil

import pytest

from backend.app.domain.vcf import parse_vcf
from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools, VCFToolError


pytestmark = pytest.mark.skipif(shutil.which("bcftools") is None, reason="bcftools is required for production normalization golden tests")


def make_reference(tmp_path: Path) -> Path:
    fasta = tmp_path / "ref.fa"
    sequence = "CAAAAAC"
    fasta.write_text(f">1\n{sequence}\n", encoding="utf-8")
    # One sequence line: header is 3 bytes, sequence starts at offset 3.
    (tmp_path / "ref.fa.fai").write_text(
        f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence)+1}\n",
        encoding="utf-8",
    )
    return fasta


def write_vcf(path: Path, records: str) -> None:
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + records,
        encoding="utf-8",
    )


def records(path: Path):
    return [
        (r.chrom, r.pos, r.ref, r.alt)
        for r in parse_vcf(str(path))
    ]


def normalize(tmp_path: Path, records_text: str):
    reference = make_reference(tmp_path)
    source = tmp_path / "input.vcf"
    output = tmp_path / "normalized.vcf"
    write_vcf(source, records_text)
    stats = normalize_vcf_with_bcftools(source, output, reference_fasta=reference)
    assert output.is_file()
    assert stats["tool"] == "bcftools"
    assert stats["operation"] == "reference_aware_normalization"
    return records(output), reference, source, output


def test_golden_snv_is_reference_checked_and_preserved(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t2\t.\tA\tG\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "A", "G")]


def test_golden_repeat_deletion_is_left_normalized(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t4\t.\tAA\tA\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "AA", "A")]


def test_golden_repeat_insertion_is_left_normalized(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t4\t.\tA\tAA\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "A", "AA")]


def test_golden_multiallelic_is_split_without_losing_alleles(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t2\t.\tA\tC,G\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "A", "C"), ("1", 2, "A", "G")]


def test_golden_mnv_is_not_atomized(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t2\t.\tAA\tTT\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "AA", "TT")]


def test_golden_ref_mismatch_fails_closed(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "bad.vcf"
    output = tmp_path / "normalized.vcf"
    write_vcf(source, "1\t2\t.\tC\tG\t.\tPASS\t.\n")
    with pytest.raises(VCFToolError, match="reference-aware normalization failed"):
        normalize_vcf_with_bcftools(source, output, reference_fasta=reference)


def test_golden_unknown_contig_fails_bcftools(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "bad.vcf"
    output = tmp_path / "normalized.vcf"
    write_vcf(source, "2\t2\t.\tA\tG\t.\tPASS\t.\n")
    with pytest.raises(VCFToolError):
        normalize_vcf_with_bcftools(source, output, reference_fasta=reference)


def test_golden_normalization_is_idempotent_at_variant_representation_level(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "input.vcf"
    first = tmp_path / "first.vcf"
    second = tmp_path / "second.vcf"
    write_vcf(source, "1\t4\t.\tAA\tA\t.\tPASS\t.\n")
    normalize_vcf_with_bcftools(source, first, reference_fasta=reference)
    normalize_vcf_with_bcftools(first, second, reference_fasta=reference)
    assert records(first) == records(second)
