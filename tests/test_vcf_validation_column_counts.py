from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict


def _write_vcf(path: Path, header: str, record: str) -> Path:
    path.write_text(f"##fileformat=VCFv4.2\n{header}\n{record}\n", encoding="utf-8")
    return path


def test_strict_vcf_accepts_exact_eight_column_record(tmp_path):
    path = _write_vcf(
        tmp_path / "valid.vcf",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
        "1\t10\t.\tA\tG\t.\tPASS\t.",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1
    assert profile["sample_count"] == 0


def test_strict_vcf_rejects_record_column_count_mismatch(tmp_path):
    path = _write_vcf(
        tmp_path / "truncated-sample.vcf",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1",
        "1\t10\t.\tA\tG\t.\tPASS\t.\tGT",
    )

    with pytest.raises(StrictVCFValidationError) as error:
        validate_vcf_strict(path)

    assert error.value.code == "VCF_RECORD_COLUMN_COUNT_MISMATCH"


def test_strict_vcf_rejects_format_without_sample_column(tmp_path):
    path = _write_vcf(
        tmp_path / "format-without-sample.vcf",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT",
        "1\t10\t.\tA\tG\t.\tPASS\t.\tGT",
    )

    with pytest.raises(StrictVCFValidationError) as error:
        validate_vcf_strict(path)

    assert error.value.code == "VCF_HEADER_INVALID"


def test_strict_vcf_accepts_sample_columns_when_counts_match(tmp_path):
    path = _write_vcf(
        tmp_path / "valid-sample.vcf",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1",
        "1\t10\t.\tA\tG\t.\tPASS\t.\tGT\t0/1",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1
    assert profile["sample_count"] == 1
