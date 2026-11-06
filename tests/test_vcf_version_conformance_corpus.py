"""Version-gated VCF conformance corpus.

The matrix deliberately tests version boundaries, not just that each version
string is recognized. Expectations are derived from the GA4GH/HTS specifications
and are kept separate from SIRALOOM's downstream SNV/INDEL scope.
"""

import gzip
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
    assert profile["alternate_allele_count"] == 2


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



@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_declared_info_number_a_matches_each_alt_allele(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-info-number-a.vcf",
        version,
        "1\t10\t.\tA\tC,G\t.\tPASS\tTEST=3,4",
        metadata=(
            '##INFO=<ID=TEST,Number=A,Type=Integer,Description="One value per ALT">',
        ),
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_declared_info_number_a_rejects_wrong_alt_cardinality(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-bad-info-number-a.vcf",
        version,
        "1\t10\t.\tA\tC,G\t.\tPASS\tTEST=3",
        metadata=(
            '##INFO=<ID=TEST,Number=A,Type=Integer,Description="One value per ALT">',
        ),
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_declared_format_number_r_includes_reference_and_alt(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-format-number-r.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\t.\tGT:XAD\t0/1:10,5",
        metadata=(
            '##FORMAT=<ID=XAD,Number=R,Type=Integer,Description="Allelic depths">',
        ),
        samples=True,
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_explicit_dot_is_valid_missing_format_value(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-missing-format-dot.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\t.\tGT:XDP\t0/1:.",
        metadata=(
            '##FORMAT=<ID=XDP,Number=1,Type=Integer,Description="Depth">',
        ),
        samples=True,
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_empty_format_value_is_not_a_missing_value(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-empty-format-value.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\t.\tGT:XDP\t0/1:",
        metadata=(
            '##FORMAT=<ID=XDP,Number=1,Type=Integer,Description="Depth">',
        ),
        samples=True,
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_SAMPLE_INVALID"


@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_integer_field_rejects_values_outside_vcf_32_bit_range(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-integer-overflow.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\tTEST=2147483648",
        metadata=(
            '##INFO=<ID=TEST,Number=1,Type=Integer,Description="Integer test">',
        ),
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_crlf_line_endings_are_accepted(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-crlf.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\t.",
    )
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    assert validate_vcf_strict(path)["records"] == 1



@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_gzip_compressed_vcf_is_accepted_for_every_supported_version(
    tmp_path: Path, version: str
) -> None:
    path = tmp_path / f"{version}.vcf.gz"
    content = (
        f"##fileformat={version}\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tC\t.\tPASS\t.\n"
    )
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as stream:
        stream.write(content)

    profile = validate_vcf_strict(path)

    assert profile["fileformat"] == version
    assert profile["records"] == 1


@pytest.mark.parametrize("version", VCF_VERSIONS)
def test_utf8_description_metadata_is_accepted(
    tmp_path: Path, version: str
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-utf8-description.vcf",
        version,
        "1\t10\t.\tA\tC\t.\tPASS\tTEST=1",
        metadata=(
            '##INFO=<ID=TEST,Number=1,Type=Integer,Description="Cohort café">',
        ),
    )

    assert validate_vcf_strict(path)["records"] == 1



@pytest.mark.parametrize("version", VCF_VERSIONS)
@pytest.mark.parametrize(
    ("genotype", "likelihoods", "expected_ploidy"),
    [
        (".", "0,10", 1),
        ("./.", "0,10,20", 2),
        ("././.", "0,10,20,30", 3),
    ],
)
def test_number_g_cardinality_uses_ploidy_even_for_missing_gt_alleles(
    tmp_path: Path,
    version: str,
    genotype: str,
    likelihoods: str,
    expected_ploidy: int,
) -> None:
    path = _write_vcf(
        tmp_path / f"{version}-missing-gt-ploidy-{expected_ploidy}.vcf",
        version,
        f"1\t10\t.\tA\tC\t.\tPASS\t.\tGT:XGL\t{genotype}:{likelihoods}",
        metadata=(
            '##FORMAT=<ID=XGL,Number=G,Type=Float,Description="Genotype likelihoods">',
        ),
        samples=True,
    )

    assert validate_vcf_strict(path)["records"] == 1
