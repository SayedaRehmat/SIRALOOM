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


@pytest.mark.parametrize(
    "version",
    ["VCFv4.0", "VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"],
)
def test_upload_intake_accepts_each_supported_vcf_version(
    tmp_path: Path, version: str
):
    path = tmp_path / f"{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.record_count == 1
    assert result.fileformat == version
    assert result.detected_build == "GRCh38"


def test_upload_intake_accepts_vcf45_reserved_base_modification_alias_without_header_definition(
    tmp_path: Path,
):
    path = tmp_path / "vcf45-implicit-base-modification.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "##reference=GRCh38\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tC\tCTAG\t.\tPASS\t.\tGT:M5mC\t0/1:0,0.5,0.7\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.record_count == 1
    assert result.fileformat == "VCFv4.5"


def test_vcf_validation_reads_real_content(tmp_path: Path):
    path = tmp_path / "sample.vcf"
    path.write_text(VALID_VCF)
    result = validate_vcf(path)
    assert result.status == "VALID"
    assert result.record_count == 1
    assert result.detected_build == "GRCh38"


@pytest.mark.parametrize(
    ("records", "error_line"),
    [
        (
            "chr1\t101\t.\tA\tG\t.\tPASS\t.\nchr1\t100\t.\tC\tT\t.\tPASS\t.\n",
            "line 5",
        ),
        (
            "chr1\t100\t.\tA\tG\t.\tPASS\t.\nchr2\t100\t.\tC\tT\t.\tPASS\t.\nchr1\t101\t.\tG\tA\t.\tPASS\t.\n",
            "line 6",
        ),
    ],
)
def test_vcf_intake_rejects_nonconforming_record_order(
    tmp_path: Path, records: str, error_line: str
):
    path = tmp_path / "out-of-order.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + records,
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "INVALID"
    assert result.record_count == 0
    assert error_line in result.errors[0]


def test_vcf_intake_rejects_whitespace_in_chromosome_name(tmp_path: Path):
    path = tmp_path / "whitespace-contig.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr 1\t100\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "INVALID"
    assert result.record_count == 0
    assert "CHROM" in result.errors[0]


@pytest.mark.parametrize("filter_value", ["0", "LowQual;LowQual", "PASS;LowQual"])
def test_vcf_intake_rejects_nonconforming_filter_values(
    tmp_path: Path, filter_value: str
):
    path = tmp_path / "invalid-filter.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"chr1\t100\t.\tA\tG\t.\t{filter_value}\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "INVALID"
    assert result.record_count == 0
    assert "FILTER" in result.errors[0]


def test_vcf_intake_accepts_a_declared_nonzero_numeric_filter_id(tmp_path: Path):
    path = tmp_path / "numeric-filter-id.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        '##FILTER=<ID=10x,Description="laboratory filter">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t.\t10x\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.record_count == 1


def test_vcf_intake_accepts_record_id_punctuation_allowed_by_vcf(tmp_path: Path):
    path = tmp_path / "punctuated-record-id.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\tlab+variant:01\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.record_count == 1


def test_vcf_intake_accepts_spec_valid_underscore_and_legacy_info_keys(tmp_path: Path):
    path = tmp_path / "valid-info-keys.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        '##INFO=<ID=_CUSTOM,Number=1,Type=Integer,Description="custom">\n'
        '##INFO=<ID=1000G,Number=0,Type=Flag,Description="legacy membership">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t_CUSTOM=7;1000G;NOTE=a%3Db\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.record_count == 1


def test_vcf_intake_rejects_unescaped_equals_inside_info_value(tmp_path: Path):
    path = tmp_path / "unescaped-info-equals.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\tNOTE=a=b\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "INVALID"
    assert result.record_count == 0
    assert "INFO" in result.errors[0]


@pytest.mark.parametrize("info_value", ["NOTE=100%", "NOTE=%GG", "NOTE=a%3db"])
def test_vcf_intake_rejects_malformed_or_lowercase_percent_escapes(
    tmp_path: Path, info_value: str
):
    path = tmp_path / "invalid-info-percent-escape.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"chr1\t100\t.\tA\tG\t.\tPASS\t{info_value}\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "INVALID"
    assert result.record_count == 0
    assert "INFO" in result.errors[0]


@pytest.mark.parametrize("failure", ["timeout", "executable_unavailable"])
def test_bcftools_validation_failure_is_not_misclassified_as_invalid_vcf(
    tmp_path: Path, monkeypatch, failure: str,
):
    import backend.app.domain.ingestion as ingestion

    path = tmp_path / "sample.vcf"
    path.write_text(VALID_VCF, encoding="utf-8")
    monkeypatch.setattr(ingestion.shutil, "which", lambda _name: "/usr/bin/bcftools")

    def fail_to_run(*_args, **_kwargs):
        if failure == "timeout":
            raise ingestion.subprocess.TimeoutExpired("bcftools", 120)
        raise OSError("executable disappeared")

    monkeypatch.setattr(ingestion.subprocess, "run", fail_to_run)

    with pytest.raises(ingestion.VCFValidationUnavailable, match="bcftools/htslib"):
        ingestion.validate_vcf(path)


def test_vcf_intake_fails_retryably_when_bcftools_is_not_installed(
    tmp_path: Path, monkeypatch
):
    import backend.app.domain.ingestion as ingestion

    path = tmp_path / "sample.vcf"
    path.write_text(VALID_VCF, encoding="utf-8")
    monkeypatch.setattr(ingestion.shutil, "which", lambda _name: None)

    with pytest.raises(ingestion.VCFValidationUnavailable, match="executable was not found"):
        ingestion.validate_vcf(path)


def test_upload_maps_validation_tool_failure_to_retryable_503(tmp_path: Path, monkeypatch):
    from fastapi import HTTPException

    from backend.app.api.v1 import artifacts
    from backend.app.domain.ingestion import VCFValidationUnavailable

    monkeypatch.setattr(
        artifacts,
        "validate_vcf",
        lambda _path: (_ for _ in ()).throw(VCFValidationUnavailable("temporary tool failure")),
    )

    with pytest.raises(HTTPException) as exc:
        artifacts._validate_vcf_for_upload(tmp_path / "sample.vcf")

    assert exc.value.status_code == 503
    assert exc.value.detail == {
        "code": "VCF_VALIDATION_UNAVAILABLE",
        "message": "temporary tool failure",
        "retryable": True,
    }


def test_vcf_validation_excludes_reference_only_rows_and_reports_count(tmp_path: Path):
    path = tmp_path / "mixed-reference-variant.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t99\t.\tA\t.\t.\tPASS\t.\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.record_count == 1
    assert any("1 reference-only" in warning and "ALT='.'" in warning for warning in result.warnings)


def test_vcf_validation_preserves_telomere_only_input_for_worker_review(tmp_path: Path):
    path = tmp_path / "telomere-only.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t0\ttelo\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.record_count == 0
    assert any("telomere sentinel record" in warning and "POS=0" in warning for warning in result.warnings)


def test_vcf_validation_preserves_declared_n_plus_one_telomere_only_input_for_review(tmp_path: Path):
    path = tmp_path / "telomere-after-contig-only.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "##contig=<ID=chr1,length=100>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t101\ttelo-after\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.record_count == 0
    assert any("contig length + 1" in warning for warning in result.warnings)


def test_vcf_validation_reports_telomere_records_without_counting_them_as_variants(tmp_path: Path):
    path = tmp_path / "telomere-and-snv.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t0\ttelo\tA\tG\t.\tPASS\t.\n"
        "chr1\t100\trs1\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.record_count == 1
    assert any("1 VCF telomere" in warning for warning in result.warnings)


def test_vcf_with_only_reference_rows_is_not_accepted_as_variant_analysis(tmp_path: Path):
    path = tmp_path / "reference-only.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t99\t.\tA\t.\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "INVALID"
    assert "cannot establish a negative clinical result" in result.errors[0]


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


@pytest.mark.parametrize("mapping", ["   ", 123, ["VCF_SAMPLE"]])
def test_vcf_sample_identity_rejects_blank_or_malformed_specimen_mapping(mapping):
    result = ValidationResult("VALID", "VCF", 1, ["VCF_SAMPLE"], "GRCh38", [], [])

    checked = validate_specimen_sample_identity(result, mapping)

    assert checked.status == "INVALID"
    assert "explicit VCF sample name mapping" in checked.errors[0]


def test_vcf_sample_identity_validation_accepts_explicit_sample_within_multisample_callset():
    multi_sample = ValidationResult(
        "VALID", "VCF", 1, ["EXPECTED_SAMPLE", "OTHER_SAMPLE"], "GRCh38", [], []
    )

    checked = validate_specimen_sample_identity(multi_sample, "EXPECTED_SAMPLE")

    assert checked.status == "VALID"
    assert checked.sample_names == ["EXPECTED_SAMPLE", "OTHER_SAMPLE"]


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


def test_vcf_validation_warns_when_format_number_g_has_no_gt_ploidy(tmp_path: Path):
    path = tmp_path / "format-number-g-without-gt.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "chr1\t100\t.\tA\tC,G\t.\tPASS\t.\tPL\t0,1,2\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert any(
        "FORMAT fields declared with Number=G" in warning and "PL" in warning
        for warning in result.warnings
    )


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


def test_index_validation_rejects_index_for_uncompressed_vcf(tmp_path: Path):
    index = tmp_path / "sample.vcf.tbi"
    with gzip.open(index, "wb") as handle:
        handle.write(b"TBI\\x01dummy")

    result = validate_index(index, "sample.vcf")

    assert result.status == "INVALID"
    assert "BGZF-compressed" in result.errors[0]


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



def test_multisample_vcf_is_validated_and_explicit_sample_mapping_is_accepted(tmp_path: Path):
    path = tmp_path / "family.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPROBAND\tMOTHER\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/1:30\t0/0:25\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.sample_names == ["PROBAND", "MOTHER"]
    assert result.fileformat == "VCFv4.3"
    assert validate_specimen_sample_identity(result, "PROBAND").status == "VALID"
    mismatch = validate_specimen_sample_identity(result, "FATHER")
    assert mismatch.status == "INVALID"
    assert "sample identity mismatch" in mismatch.errors[0]


def test_sites_only_vcf_is_structurally_valid_but_not_sample_specific(tmp_path: Path):
    path = tmp_path / "sites-only.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##reference=GRCh38\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.sample_names == []
    checked = validate_specimen_sample_identity(result, None)
    assert checked.status == "VALID"
    assert any("Sites-only VCF" in warning for warning in checked.warnings)


def test_multisample_vcf_parser_requires_explicit_sample_selection(tmp_path: Path):
    from backend.app.domain.vcf import VCFValidationError, parse_vcf

    path = tmp_path / "family.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPROBAND\tMOTHER\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/1:30\t0/0:25\n",
        encoding="utf-8",
    )

    with pytest.raises(VCFValidationError, match="explicit sample_name"):
        list(parse_vcf(str(path)))

    records = list(parse_vcf(str(path), sample_name="PROBAND"))
    assert len(records) == 1
    assert list(records[0].sample_calls) == ["PROBAND"]
    assert records[0].sample_calls["PROBAND"]["genotype"] == "0/1"



def test_vcf45_local_allele_callset_passes_full_intake_validation(tmp_path: Path):
    path = tmp_path / "v45-local-alleles.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "##reference=GRCh38\n"
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">\n'
        '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">\n'
        '##FORMAT=<ID=LPL,Number=LG,Type=Integer,Description="Local genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "chr1\t100\t.\tA\tC,G,T\t.\tPASS\t.\tGT:LAA:LAD:LPL\t0/2:2:20,10:0,50,100\n",
        encoding="utf-8",
    )

    result = validate_vcf(path)

    assert result.status == "VALID"
    assert result.fileformat == "VCFv4.5"
    assert result.sample_names == ["SAMPLE1"]
