from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict


def write_vcf(path: Path, body: str, *, version: str = "VCFv4.3", columns: str | None = None) -> None:
    columns = columns or "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
    path.write_text(
        f"##fileformat={version}\n"
        f"{columns}\n"
        f"{body}",
        encoding="utf-8",
    )


def test_strict_validation_accepts_standard_vcf(tmp_path: Path):
    path = tmp_path / "valid.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\t.\n")
    profile = validate_vcf_strict(path, reference_contigs={"1"})
    assert profile["records"] == 1
    assert profile["reference_contig_policy"] == "EXACT"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("1\t2\t.\tA\tG\n", "VCF_RECORD_INVALID"),
        ("1\t0\t.\tA\tG\t.\tPASS\t.\n", "VCF_POS_INVALID"),
        ("1\t2\t.\tX\tG\t.\tPASS\t.\n", "VCF_REF_INVALID"),
        ("1\t2\t.\tA\tG\t-1\tPASS\t.\n", "VCF_QUAL_INVALID"),
        ("1\t2\t.\tA\tG\t.\tPASS\tBAD;\n", "VCF_FILTER_INVALID"),
    ],
)
def test_strict_validation_rejects_malformed_records(tmp_path: Path, body: str, code: str):
    path = tmp_path / "bad.vcf"
    write_vcf(path, body)
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == code


def test_strict_validation_rejects_missing_fileformat(tmp_path: Path):
    path = tmp_path / "bad.vcf"
    path.write_text(
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError, match="fileformat"):
        validate_vcf_strict(path)


def test_strict_validation_rejects_contig_mismatch(tmp_path: Path):
    path = tmp_path / "bad-contig.vcf"
    write_vcf(path, "chr1\t2\t.\tA\tG\t.\tPASS\t.\n")
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path, reference_contigs={"1"})
    assert exc.value.code == "REFERENCE_CONTIG_MISMATCH"


def test_strict_validation_checks_genotype_allele_indexes(tmp_path: Path):
    path = tmp_path / "bad-gt.vcf"
    write_vcf(
        path,
        "1\t2\t.\tA\tG\t.\tPASS\t.\tGT\t2/2\n",
        columns="#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_GENOTYPE_INVALID"


def test_strict_validation_profiles_multiallelic_and_symbolic_records(tmp_path: Path):
    path = tmp_path / "profile.vcf"
    write_vcf(
        path,
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\n"
        "1\t3\t.\tA\t<DEL>\t.\tPASS\t.\n",
    )
    profile = validate_vcf_strict(path)
    assert profile["multiallelic_records"] == 1
    assert profile["symbolic_records"] == 1
