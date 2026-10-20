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
        ("1\t2\t.\tA\tG\t.\tBAD;\t.\n", "VCF_FILTER_INVALID"),
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


@pytest.mark.parametrize(
    ("columns", "body"),
    [
        (
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1",
            "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        ),
        (
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
            "1\t2\t.\tA\tG\t.\tPASS\t.\tGT\n",
        ),
    ],
)
def test_strict_validation_requires_record_column_count_to_match_header(
    tmp_path: Path, columns: str, body: str
):
    path = tmp_path / "wrong-column-count.vcf"
    write_vcf(path, body, columns=columns)

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_RECORD_INVALID"


def test_strict_validation_requires_gt_to_be_first_format_key(tmp_path: Path):
    path = tmp_path / "gt-not-first.vcf"
    write_vcf(
        path,
        "1\t2\t.\tA\tG\t.\tPASS\t.\tGQ:GT\t20:0/1\n",
        columns="#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FORMAT_INVALID"


def test_strict_validation_accepts_omitted_trailing_format_values(tmp_path: Path):
    path = tmp_path / "trailing-format-omission.vcf"
    write_vcf(
        path,
        "1\t2\t.\tA\tG\t.\tPASS\t.\tGT:GQ:DP\t0/1:40\n",
        columns="#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1


def test_strict_validation_profiles_multiallelic_and_symbolic_records(tmp_path: Path):
    path = tmp_path / "profile.vcf"
    write_vcf(
        path,
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\n"
        "1\t3\t.\tA\t<DEL>\t.\tPASS\tEND=9\n",
    )
    profile = validate_vcf_strict(path)
    assert profile["multiallelic_records"] == 1
    assert profile["symbolic_records"] == 1


@pytest.mark.parametrize(
    ("record", "code"),
    [
        ("1\t5\t.\tA\t<DEL>\t.\tPASS\tSVTYPE=DEL\n", "VCF_SV_SPAN_MISSING"),
        ("1\t5\t.\tA\t<DEL>\t.\tPASS\tEND=4\n", "VCF_SV_INVALID"),
        ("1\t5\t.\tA\t<DEL>\t.\tPASS\tEND=bad\n", "VCF_SV_INVALID"),
        ("1\t5\t.\tA\tA]2:0]\t.\tPASS\tSVTYPE=BND\n", "VCF_ALT_INVALID"),
    ],
)
def test_strict_validation_rejects_malformed_structural_representation(tmp_path, record, code):
    path = tmp_path / "malformed-sv.vcf"
    write_vcf(path, record)
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == code


def test_strict_validation_requires_context_for_spanning_deletion_allele(tmp_path):
    path = tmp_path / "orphan-star.vcf"
    write_vcf(path, "1\t11\t.\tT\t*\t.\tPASS\t.\n")
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_SPANNING_DELETION_CONTEXT_MISSING"


def test_strict_validation_accepts_spanning_deletion_with_overlapping_deletion_record(tmp_path):
    path = tmp_path / "contextual-star.vcf"
    write_vcf(
        path,
        "1\t10\tdel1\tAT\tA\t.\tPASS\t.\n"
        "1\t11\tstar1\tT\t*\t.\tPASS\t.\n",
    )
    profile = validate_vcf_strict(path)
    assert profile["records"] == 2


def test_strict_validation_rejects_spanning_deletion_carried_by_different_sample(tmp_path):
    path = tmp_path / "wrong-sample-star.vcf"
    columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1"
    write_vcf(
        path,
        "1\t10\tdel1\tAT\tA\t.\tPASS\t.\tGT\t0/0\n"
        "1\t11\tstar1\tT\t*\t.\tPASS\t.\tGT\t0/1\n",
        columns=columns,
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_SPANNING_DELETION_CONTEXT_MISSING"


def test_strict_validation_accepts_spanning_deletion_from_symbolic_deletion_span(tmp_path):
    path = tmp_path / "symbolic-context-star.vcf"
    columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1"
    write_vcf(
        path,
        "1\t10\tdel1\tA\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=11\tGT\t0/1\n"
        "1\t11\tstar1\tA\t*\t.\tPASS\t.\tGT\t0/1\n",
        columns=columns,
    )
    assert validate_vcf_strict(path)["records"] == 2
