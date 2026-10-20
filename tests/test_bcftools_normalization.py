from pathlib import Path
import gzip
import shutil

import pytest

from backend.app.domain.vcf import parse_vcf
from backend.app.domain.vcf_tools import MNV_POLICY, MULTIALLELIC_POLICY, normalize_vcf_with_bcftools, VCFToolError


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
        "##contig=<ID=1,length=7>\n"
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
    output = tmp_path / "normalized.vcf.gz"
    write_vcf(source, records_text)
    stats = normalize_vcf_with_bcftools(source, output, reference_fasta=reference)
    assert output.is_file()
    assert stats["tool"] == "bcftools"
    assert stats["operation"] == "reference_aware_normalization_sort_index"
    assert stats["compression"] == "BGZF"
    assert stats["index"] == "CSI"
    assert Path(str(output) + ".csi").is_file()
    assert stats["multiallelic_mode"] == MULTIALLELIC_POLICY
    assert stats["mnv_policy"] == MNV_POLICY
    return records(output), reference, source, output


def test_golden_snv_is_reference_checked_and_preserved(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t2\t.\tA\tG\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "A", "G")]


def test_golden_repeat_deletion_is_left_normalized(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t4\t.\tAA\tA\t.\tPASS\t.\n")
    assert normalized == [("1", 1, "CA", "C")]


def test_golden_repeat_insertion_is_left_normalized(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t4\t.\tA\tAA\t.\tPASS\t.\n")
    assert normalized == [("1", 1, "C", "CA")]


def test_golden_multiallelic_is_split_without_losing_alleles(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t2\t.\tA\tC,G\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "A", "C"), ("1", 2, "A", "G")]


def test_golden_mnv_is_not_atomized(tmp_path: Path):
    normalized, *_ = normalize(tmp_path, "1\t2\t.\tAA\tTT\t.\tPASS\t.\n")
    assert normalized == [("1", 2, "AA", "TT")]


def test_golden_ref_mismatch_fails_closed(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "bad.vcf"
    output = tmp_path / "normalized.vcf.gz"
    write_vcf(source, "1\t2\t.\tC\tG\t.\tPASS\t.\n")
    with pytest.raises(VCFToolError, match="reference-aware normalization failed"):
        normalize_vcf_with_bcftools(source, output, reference_fasta=reference, expected_bcftools_version="1.19")


def test_golden_unknown_contig_fails_bcftools(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "bad.vcf"
    output = tmp_path / "normalized.vcf.gz"
    write_vcf(source, "2\t2\t.\tA\tG\t.\tPASS\t.\n")
    with pytest.raises(VCFToolError):
        normalize_vcf_with_bcftools(source, output, reference_fasta=reference)


def test_golden_normalization_is_idempotent_at_variant_representation_level(tmp_path: Path):
    reference = make_reference(tmp_path)
    source = tmp_path / "input.vcf"
    first = tmp_path / "first.vcf.gz"
    second = tmp_path / "second.vcf.gz"
    write_vcf(source, "1\t4\t.\tAA\tA\t.\tPASS\t.\n")
    normalize_vcf_with_bcftools(source, first, reference_fasta=reference)
    normalize_vcf_with_bcftools(first, second, reference_fasta=reference)
    assert records(first) == records(second)


def test_pinned_bcftools_trims_unseen_gvcf_wildcard_without_changing_called_genotype(tmp_path: Path):
    from backend.app.domain.vcf_tools import route_vcf_records

    reference = make_reference(tmp_path)
    source = tmp_path / "sample.g.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        '##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n'
        "##INFO=<ID=AF,Number=A,Type=Float,Description=Allele frequency>\n"
        "##FORMAT=<ID=GT,Number=1,Type=String,Description=Genotype>\n"
        "##FORMAT=<ID=AD,Number=R,Type=Integer,Description=Allelic depths>\n"
        "##FORMAT=<ID=PL,Number=G,Type=Integer,Description=Phred likelihoods>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t1\t.\tC\t<NON_REF>\t.\tPASS\t.\tGT:AD:PL\t0/0:20,0:0,40,400\n"
        "1\t2\trsG\tA\tG,<NON_REF>\t50\tPASS\tAF=0.2,0\tGT:AD:PL\t0/1:15,9,0:100,50,60,40,0,30\n",
        encoding="utf-8",
    )
    routed = route_vcf_records(source, tmp_path / "routed-gvcf")
    assert routed["gvcf_reference_blocks"] == 1
    assert routed["sequence_records"] == 1

    output = tmp_path / "called-variants.normalized.vcf.gz"
    stats = normalize_vcf_with_bcftools(
        routed["sequence_path"], output, reference_fasta=reference,
        expected_bcftools_version="1.19",
    )

    assert stats["tool_version"].split()[1] == "1.19"
    assert stats["gvcf_wildcard_command"] == "bcftools view -A"
    assert records(output) == [("1", 2, "A", "G")]
    with gzip.open(output, "rt", encoding="utf-8") as handle:
        variant = next(line for line in handle if not line.startswith("#"))
    fields = variant.rstrip("\n").split("\t")
    assert fields[4] == "G"
    assert fields[7] == "AF=0.2"
    assert fields[8] == "GT:AD:PL"
    # Removing allele 2 retains PL entries for 0/0, 0/1, and 1/1; the
    # removed 0/2 and 1/2 likelihoods must not be reassigned to 1/1.
    assert fields[9] == "0/1:15,9:100,50,60"
