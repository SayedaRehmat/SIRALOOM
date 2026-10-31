import gzip
from pathlib import Path

import pytest

from backend.app.domain.normalization import NormalizationError, UnsupportedVariantError, iter_normalized_vcf, normalize_vcf_file
from backend.app.domain.reference import FastaReference
from backend.app.domain.variant_identity import canonical_key, stable_variant_uuid


def make_reference(tmp_path: Path) -> tuple[Path, Path]:
    fasta = tmp_path / "ref.fa"
    seq = "CAAAAAC"
    # FAI offsets are byte offsets; avoid Windows text-mode newline translation.
    fasta.write_bytes((">1\n" + seq + "\n").encode("ascii"))
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


def test_unsupported_variant_errors_have_stable_codes():
    error = UnsupportedVariantError(
        "GVCF input is not supported by Phase 1.",
        code="UNSUPPORTED_GVCF_INPUT",
    )
    assert error.code == "UNSUPPORTED_GVCF_INPUT"
    assert str(error) == "GVCF input is not supported by Phase 1."



def test_failed_normalization_does_not_publish_partial_output(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\n"
        "1\t3\t.\tT\tA\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    output_vcf.write_text("previous-valid-output\n", encoding="utf-8")
    with FastaReference(fasta, fai) as ref:
        with pytest.raises(NormalizationError, match="Reference allele mismatch"):
            normalize_vcf_file(input_vcf, output_vcf, genome_build="GRCh38", reference=ref)
    assert output_vcf.read_text(encoding="utf-8") == "previous-valid-output\n"
    assert not list(tmp_path.glob(".normalized.*.tmp"))


def test_gzip_output_is_valid_and_published_with_final_gzip_suffix(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf.gz"
    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with FastaReference(fasta, fai) as ref:
        result = normalize_vcf_file(input_vcf, output_vcf, genome_build="GRCh38", reference=ref)
    assert result["output_path"] == str(output_vcf)
    with gzip.open(output_vcf, "rt", encoding="utf-8") as handle:
        normalized_text = handle.read()
    assert "#CHROM" in normalized_text
    assert "1\t2\t.\tA\tC" in normalized_text
    assert not list(tmp_path.glob(".normalized.*.tmp.gz"))



def test_normalized_vcf_iteration_uses_only_the_explicitly_selected_sample(tmp_path: Path):
    normalized_vcf = tmp_path / "family.normalized.vcf"
    normalized_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPROBAND\tMOTHER\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/1:30\t0/0:25\n",
        encoding="utf-8",
    )

    proband_variants = list(iter_normalized_vcf(normalized_vcf, "GRCh38", sample_name="PROBAND"))
    mother_variants = list(iter_normalized_vcf(normalized_vcf, "GRCh38", sample_name="MOTHER"))

    assert len(proband_variants) == 1
    assert proband_variants[0].sample_call["sample_name"] == "PROBAND"
    assert proband_variants[0].sample_call["genotype"] == "0/1"
    assert mother_variants == []


def test_normalized_iteration_excludes_only_proven_non_carrier_alt_records(tmp_path: Path):
    normalized_vcf = tmp_path / "normalized-non-carrier.vcf"
    normalized_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        '##INFO=<ID=SIRALOOM_ORIG,Number=.,Type=String,Description="Original source record">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=SIRALOOM_SOURCE_GT,Number=1,Type=String,Description="Original source genotype">\n'
        '##FORMAT=<ID=SIRALOOM_SOURCE_ALT_COUNT,Number=1,Type=Integer,Description="Original ALT count">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "1\t100\t.\tA\tC\t.\tPASS\tSIRALOOM_ORIG=1|100|A|C,G|1\t"
        "GT:SIRALOOM_SOURCE_GT:SIRALOOM_SOURCE_ALT_COUNT\t./.:2/2:2\n"
        "1\t100\t.\tA\tG\t.\tPASS\tSIRALOOM_ORIG=1|100|A|C,G|2\t"
        "GT:SIRALOOM_SOURCE_GT:SIRALOOM_SOURCE_ALT_COUNT\t1/1:2/2:2\n"
        "1\t200\t.\tA\tC\t.\tPASS\tSIRALOOM_ORIG=1|200|A|C,G|1\t"
        "GT:SIRALOOM_SOURCE_GT:SIRALOOM_SOURCE_ALT_COUNT\t0/.:0/.:2\n",
        encoding="utf-8",
    )
    exclusion_stats: dict[str, int] = {}

    variants = list(
        iter_normalized_vcf(
            normalized_vcf, "GRCh38", sample_name="SAMPLE",
            exclusion_stats=exclusion_stats,
        )
    )

    assert [(variant.position, variant.alternate) for variant in variants] == [
        (100, "G"),
        (200, "C"),
    ]
    assert variants[0].sample_call["genotype"] == "2/2"
    assert variants[0].sample_call["normalized_genotype"] == "1/1"
    assert variants[0].sample_call["source_genotype"] == "2/2"
    assert variants[0].sample_call["selected_alt_dosage"] == 2
    assert variants[1].sample_call["genotype"] == "0/."
    assert variants[1].sample_call["source_genotype"] == "0/."
    assert variants[1].sample_call["projection_status"] == "PARTIAL_CALL"
    assert variants[1].sample_call["missing_allele_count"] == 1
    assert exclusion_stats["reference_only_genotype_alleles"] == 1
