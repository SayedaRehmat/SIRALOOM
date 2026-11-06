from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


@pytest.mark.parametrize("version", ["VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"])
@pytest.mark.parametrize(
    "definition",
    [
        '##FORMAT=<ID=GT,Number=2,Type=String,Description="Genotype">',
        '##FORMAT=<ID=GT,Number=1,Type=Integer,Description="Genotype">',
    ],
)
def test_gt_header_definition_is_always_number_one_string(
    tmp_path: Path, version: str, definition: str
):
    path = tmp_path / f"gt-header-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        f"{definition}\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"
