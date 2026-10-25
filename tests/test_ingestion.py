import gzip
from pathlib import Path

import pytest

from backend.app.domain.ingestion import (
    ValidationResult,
    classify_filename,
    validate_index,
    validate_specimen_sample_identity,
    validate_vcf,
)
from backend.app.domain.vcf import VCFValidationError, parse_vcf

VALID_VCF = """##fileformat=VCFv4.3
##reference=GRCh38
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
chr1\t100\t.\tA\tG\t.\tPASS\t.
"""


def test_supported_filename_classification():
    assert classify_filename("sample.vcf") == "VCF"
    assert classify_filename("sample.vcf.gz") == "VCF"
    assert classify_filename("sample.vcf.bgz") == "VCF"
    assert classify_filename("sample.vcf.gz.tbi") == "TBI"
    assert classify_filename("sample.vcf.bgz.csi") == "CSI"
    assert classify_filename("sample.bam") == "UNSUPPORTED"


def test_vcf_validation_reads_real_content(tmp_path: Path):
    path = tmp_path / "sample.vcf"
    path.write_text(VALID_VCF)
    result = validate_vcf(path)
    assert result.status == "VALID"
    assert result.record_count == 1
    assert result.detected_build == "GRCh38"


def test_vcf_upload_validation_rejects_explicit_specimen_sample_mismatch():
    result = ValidationResult(
        "VALID", "VCF", 1, ["OTHER_SAMPLE"], "GRCh38", [], []
    )

    checked = validate_specimen_sample_identity(result, "EXPECTED_SAMPLE")

    assert checked.status == "INVALID"
    assert checked.sample_names == ["OTHER_SAMPLE"]
    assert "sample identity mismatch" in checked.errors[0]


def test_vcf_sample_identity_requires_explicit_specimen_mapping():
    result = ValidationResult("VALID", "VCF", 1, ["VCF_SAMPLE"], "GRCh38", [], [])

    checked = validate_specimen_sample_identity(result, None)

    assert checked.status == "INVALID"
    assert checked.sample_names == ["VCF_SAMPLE"]
    assert "explicit VCF sample name mapping" in checked.errors[0]


def test_vcf_sample_identity_validation_requires_exact_single_sample_match():
    multi_sample = ValidationResult(
        "VALID", "VCF", 1, ["EXPECTED_SAMPLE", "OTHER_SAMPLE"], "GRCh38", [], []
    )

    checked = validate_specimen_sample_identity(multi_sample, "EXPECTED_SAMPLE")

    assert checked.status == "INVALID"
    assert "EXPECTED_SAMPLE, OTHER_SAMPLE" in checked.errors[0]


def test_vcf_validation_warns_when_info_number_g_cannot_be_checked(tmp_path: Path):
    path = tmp_path / "info-number-g.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##INFO=<ID=GL,Number=G,Type=Float,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\tGL=0,-1,-2\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert any("Number=G" in warning and "GL" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "assembly_headers",
    [
        ("##reference=GRCh38", "##reference=GRCh37"),
        ("##reference=GRCh38", '##contig=<ID=chr1,length=10,assembly="GRCh37">'),
        ("##reference=file:///references/GRCh38_and_GRCh37.fa",),
    ],
)
def test_vcf_validation_rejects_conflicting_reference_assembly_declarations(
    tmp_path: Path, assembly_headers: tuple[str, ...],
):
    path = tmp_path / "conflicting-reference.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        + "\n".join(assembly_headers)
        + "\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "chr1\t1\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "INVALID"
    assert result.detected_build is None
    assert "conflicting reference assembly declarations" in result.errors[0]


def test_vcf_validation_accepts_consistent_reference_and_contig_assembly_tags(tmp_path: Path):
    path = tmp_path / "consistent-reference.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=file:///references/GRCh38.fa\n"
        '##contig=<ID=chr1,length=10,assembly="GRCh38">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.detected_build == "GRCh38"


def test_vcf_validation_rejects_empty_reference_metadata(tmp_path: Path):
    path = tmp_path / "empty-reference.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference= \n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "INVALID"
    assert "reference metadata cannot have an empty value" in result.errors[0]


def test_vcf_record_parser_does_not_silently_strip_a_bom(tmp_path: Path):
    path = tmp_path / "bom-parser.vcf"
    path.write_bytes(b"\xef\xbb\xbf" + VALID_VCF.encode("utf-8"))

    with pytest.raises(VCFValidationError, match="must not contain a UTF-8 byte-order mark"):
        list(parse_vcf(str(path)))


def test_vcfgz_validation_reads_real_content(tmp_path: Path):
    path = tmp_path / "sample.vcf.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(VALID_VCF)
    result = validate_vcf(path)
    assert result.status == "VALID"
    assert result.record_count == 1


def test_vcfbgz_validation_parses_compressed_records(tmp_path: Path):
    path = tmp_path / "sample.vcf.bgz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(VALID_VCF)
    result = validate_vcf(path)
    assert result.status == "VALID"
    assert result.record_count == 1
    assert result.detected_build == "GRCh38"


def test_invalid_vcf_header_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.vcf"
    path.write_text("#CHROM\tPOS\tID\tREF\tALT\nchr1\t1\t.\tA\tG\n")
    result = validate_vcf(path)
    assert result.status == "INVALID"
    assert result.errors


def test_upload_validation_rejects_sample_count_mismatch(tmp_path: Path):
    path = tmp_path / "sample-count-mismatch.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "INVALID"
    assert "header declares 10" in result.errors[0]


def test_upload_validation_accepts_omitted_trailing_format_values(tmp_path: Path):
    path = tmp_path / "trailing-format-omission.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\tGT:GQ:DP\t0/1:40\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.sample_names == ["SAMPLE1"]


def test_index_filename_and_magic_validation(tmp_path: Path):
    primary = "sample.vcf.gz"
    tbi = tmp_path / "sample.vcf.gz.tbi"
    import gzip
    with gzip.open(tbi, "wb") as fh:
        fh.write(b"TBI\x01dummy")
    assert validate_index(tbi, primary).status == "VALID"

    wrong = tmp_path / "other.vcf.gz.tbi"
    with gzip.open(wrong, "wb") as fh:
        fh.write(b"TBI\x01dummy")
    assert validate_index(wrong, primary).status == "INVALID"


def test_csi_magic_validation(tmp_path: Path):
    csi = tmp_path / "sample.vcf.bgz.csi"
    csi.write_bytes(b"CSI\x01dummy")
    assert validate_index(csi, "sample.vcf.bgz").status == "VALID"


def test_index_alone_is_not_primary_input():
    assert classify_filename("sample.vcf.gz.tbi") == "TBI"


def test_malformed_tbi_is_rejected(tmp_path: Path):
    tbi = tmp_path / "sample.vcf.gz.tbi"
    tbi.write_bytes(b"\x1f\x8b\x08\x04not-a-valid-gzip")
    assert validate_index(tbi, "sample.vcf.gz").status == "INVALID"
