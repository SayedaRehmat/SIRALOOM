from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


@pytest.mark.parametrize("version", ["VCFv4.1", "VCFv4.2", "VCFv4.3"])
@pytest.mark.parametrize("gt", ["0|1/0", "0/1|0"])
def test_pre_vcf44_rejects_mixed_gt_phase_separators(
    tmp_path: Path, version: str, gt: str
):
    path = tmp_path / f"mixed-phase-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tA\tC\t.\tPASS\t.\tGT\t{gt}\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_GENOTYPE_INVALID"


@pytest.mark.parametrize(
    ("version", "gt"),
    [
        ("VCFv4.4", "0|1/0"),
        ("VCFv4.4", "/0/1"),
        ("VCFv4.5", "0/1|0"),
        ("VCFv4.5", "|0|1/2"),
    ],
)
def test_vcf44_plus_accepts_partial_phasing_and_optional_prefix(
    tmp_path: Path, version: str, gt: str
):
    path = tmp_path / f"partial-phase-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT\t{gt}\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1
