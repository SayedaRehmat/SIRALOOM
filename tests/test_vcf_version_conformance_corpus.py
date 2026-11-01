"""Version-gated VCF conformance corpus.

The matrix deliberately tests version boundaries, not just that each version
string is recognized. Expectations are derived from the GA4GH/HTS specifications
and are kept separate from SIRALOOM's downstream SNV/INDEL scope.
"""

from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict


VCF_VERSIONS = tuple(f"VCFv4.{minor}" for minor in range(6))


def _write_vcf(
    path: Path,
    version: str,
    record: str,
    *,
    metadata: tuple[str, ...] = (),
    samples: bool = False,
) -> Path:
    columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
    if samples:
        columns += "\tFORMAT\tSAMPLE1"
    path.write_text(
        "\n".join((f"##fileformat={version}", *metadata, columns, record, "")),
        encoding="utf-8",
        newline="\n",
    )
    return path


@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_minimal_sites_only_record_is_accepted_for_every_supported_version(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\t.",
    )

    profile = validate_vcf_strict(path)

    assert profile["fileformat"] == version
    assert profile["records"] == 1


@pytest.mark.parametrize("version", VCF_VERSIONS[:4])
def test_vcf44_leading_gt_phase_separator_is_rejected_before_v44(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-leading-phase.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\t.\tGT\t|0/1",
        samples=True,
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_GENOTYPE_INVALID"


@pytest.mark.parametrize("version", VCF_VERSIONS[4:])
def test_vcf44_leading_gt_phase_separator_is_accepted_from_v44(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-leading-phase.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\t.\tGT\t|0/1",
        samples=True,
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("version", VCF_VERSIONS[:5])
def test_duplicate_alt_alleles_remain_accepted_before_v45_contract(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-duplicate-alt.vcf",
        version,
        "1\t10\t.\tA\tC,c\t.\tPASS\t.",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1
    assert profile["alternate_alleles"] == 2


def test_vcf45_duplicate_alt_alleles_are_rejected(tmp_path: Path) -> None:
    path = _write_vcf(
        tmp_path / "vcf45-duplicate-alt.vcf",
        "VCFv4.5",
        "1\t10\t.\tA\tC,c\t.\tPASS\t.",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_ALT_DUPLICATE"


@pytest.mark.parametrize("version", VCF_VERSIONS[:3])
def test_vcf43_contig_name_grammar_is_not_applied_to_older_versions(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-legacy-contig.vcf",
        version,
        "chr[1]\t10\t.\tA\tC\t.\tPASS\t.",
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("version", VCF_VERSIONS[3:])
def test_vcf43_contig_name_grammar_rejects_reserved_breakend_characters(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-invalid-contig.vcf",
        version,
        "chr[1]\t10\t.\tA\tC\t.\tPASS\t.",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_CHROM_INVALID"


def test_vcf45_local_allele_number_is_accepted_with_laa_context(tmp_path: Path) -> None:
    path = _write_vcf(
        tmp_path / "vcf45-local-number-la.vcf",
        "VCFv4.5",
        "1\t10\t.\tA\tC\t.\tPASS\t.\tGT:LAA:LOCAL\t0/1:1:7",
        metadata=(
            '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">',
            '##FORMAT=<ID=LOCAL,Number=LA,Type=Integer,Description="Local allele values">',
        ),
        samples=True,
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("version", VCF_VERSIONS[:5])
def test_local_allele_number_is_rejected_before_vcf45(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-local-number-la.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\t.\tGT\t0/1",
        metadata=(
            '##FORMAT=<ID=LOCAL,Number=LA,Type=Integer,Description="Local allele values">',
        ),
        samples=True,
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"
