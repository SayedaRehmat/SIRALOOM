import gzip
from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_reference_alleles,
    validate_vcf_strict,
)


def write_vcf(path: Path, body: str, *, version: str = "VCFv4.3", columns: str | None = None) -> None:
    columns = columns or "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
    path.write_text(
        f"##fileformat={version}\n"
        f"{columns}\n"
        f"{body}",
        encoding="utf-8",
    )


def write_vcf_with_metadata(path: Path, metadata: list[str], body: str, *, sample: bool = False) -> None:
    columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
    if sample:
        columns += "\tFORMAT\tSAMPLE1"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        + "\n".join(metadata)
        + "\n"
        + columns
        + "\n"
        + body,
        encoding="utf-8",
    )


def test_strict_validation_accepts_standard_vcf(tmp_path: Path):
    path = tmp_path / "valid.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\t.\n")
    profile = validate_vcf_strict(path, reference_contigs={"1"})
    assert profile["records"] == 1
    assert profile["reference_contig_policy"] == "EXACT"


def test_strict_validation_rejects_whitespace_in_chromosome_name(tmp_path: Path):
    path = tmp_path / "whitespace-contig.vcf"
    write_vcf(path, "chr 1\t2\t.\tA\tG\t.\tPASS\t.\n")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_CHROM_INVALID"


def test_strict_validation_accepts_nonzero_numeric_filter_identifier(tmp_path: Path):
    path = tmp_path / "numeric-filter-id.vcf"
    write_vcf_with_metadata(
        path,
        ['##FILTER=<ID=10x,Description="laboratory filter">'],
        "1\t2\t.\tA\tG\t.\t10x\t.\n",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1


def test_strict_validation_accepts_vcf_record_ids_with_valid_punctuation(tmp_path: Path):
    path = tmp_path / "punctuated-record-id.vcf"
    write_vcf(path, "1\t2\tlab+variant:01\tA\tG\t.\tPASS\t.\n")

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1


def test_strict_validation_accepts_vcf_info_and_format_keys_allowed_by_spec(tmp_path: Path):
    path = tmp_path / "underscore-info-format-keys.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##INFO=<ID=_CUSTOM,Number=1,Type=Integer,Description="custom">',
            '##INFO=<ID=1000G,Number=0,Type=Flag,Description="legacy membership">',
            '##FORMAT=<ID=_GX,Number=1,Type=Integer,Description="custom genotype value">',
        ],
        "1\t2\t.\tA\tG\t.\tPASS\t_CUSTOM=7;1000G\tGT:_GX\t0/1:9\n",
        sample=True,
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1


def test_strict_validation_rejects_decreasing_positions_within_contig(tmp_path: Path):
    path = tmp_path / "positions-out-of-order.vcf"
    write_vcf(
        path,
        "1\t3\t.\tA\tG\t.\tPASS\t.\n"
        "1\t2\t.\tC\tT\t.\tPASS\t.\n",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_POS_ORDER_INVALID"


def test_strict_validation_rejects_noncontiguous_chromosome_blocks(tmp_path: Path):
    path = tmp_path / "chromosome-blocks-out-of-order.vcf"
    write_vcf(
        path,
        "1\t2\t.\tA\tG\t.\tPASS\t.\n"
        "2\t1\t.\tC\tT\t.\tPASS\t.\n"
        "1\t3\t.\tG\tA\t.\tPASS\t.\n",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_CHROM_BLOCK_NONCONTIGUOUS"


def test_strict_validation_accepts_equal_positions_and_any_contig_block_order(
    tmp_path: Path,
):
    path = tmp_path / "valid-contiguous-blocks.vcf"
    write_vcf(
        path,
        "2\t3\t.\tA\tG\t.\tPASS\t.\n"
        "2\t3\t.\tC\tT\t.\tPASS\t.\n"
        "1\t1\t.\tG\tA\t.\tPASS\t.\n",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 3


def test_strict_validation_rejects_data_record_without_final_line_separator(tmp_path: Path):
    path = tmp_path / "missing-final-newline.vcf"
    path.write_bytes(
        b"##fileformat=VCFv4.3\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"1\t2\t.\tA\tG\t.\tPASS\t."
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_RECORD_TERMINATOR_MISSING"


def test_strict_validation_rejects_metadata_after_chrom_header(tmp_path: Path):
    path = tmp_path / "metadata-after-header.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "##source=late-metadata\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_ORDER_INVALID"


def test_strict_validation_rejects_hash_prefixed_record_instead_of_silently_dropping_it(
    tmp_path: Path,
):
    path = tmp_path / "hash-prefixed-record.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "#1\t100\trs1\tA\tG\t.\tPASS\t.\n"
        "1\t200\trs2\tC\tT\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_INVALID"


def test_late_info_definition_cannot_make_an_invalid_record_pass(tmp_path: Path):
    path = tmp_path / "late-info-definition.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t.\tPASS\tLATE=1,2\n"
        '##INFO=<ID=LATE,Number=1,Type=Integer,Description="must precede records">\n',
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_ORDER_INVALID"


def test_strict_validation_accepts_vcf_reference_only_alt_dot_record(tmp_path: Path):
    path = tmp_path / "reference-only.vcf"
    write_vcf(path, "1\t2\t.\tA\t.\t.\tPASS\t.\n")

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1
    assert profile["reference_only_records"] == 1


def test_strict_validation_accepts_vcf_telomere_sentinel_and_marks_it_for_review(tmp_path: Path):
    path = tmp_path / "telomere.vcf"
    write_vcf(path, "1\t0\t.\tA\tG\t.\tPASS\t.\n")

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1
    assert profile["telomere_records"] == 1


def test_strict_validation_counts_declared_contig_n_plus_one_as_telomere(tmp_path: Path):
    path = tmp_path / "telomere-after-contig.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=10>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t11\ttelo-after\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1
    assert profile["telomere_records"] == 1


def test_declared_vcf_contig_length_parses_quoted_id_and_attributes_in_any_order(tmp_path: Path):
    path = tmp_path / "quoted-contig.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##contig=<assembly="GRCh38",length=10,ID="chr,1">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr,1\t11\ttelo-after\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["telomere_records"] == 1


def test_strict_validation_does_not_treat_out_of_range_position_as_telomere(tmp_path: Path):
    path = tmp_path / "out-of-range.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=10>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t12\toutside\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["telomere_records"] == 0


def test_strict_validation_rejects_missing_alt_mixed_with_called_alt(tmp_path: Path):
    path = tmp_path / "mixed-missing-alt.vcf"
    write_vcf(path, "1\t2\t.\tA\t.,G\t.\tPASS\t.\n")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_ALT_INVALID"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("1\t2\t.\tA\tG\n", "VCF_RECORD_INVALID"),
        ("1\t-1\t.\tA\tG\t.\tPASS\t.\n", "VCF_POS_INVALID"),
        ("1\t2\tbad id\tA\tG\t.\tPASS\t.\n", "VCF_ID_INVALID"),
        ("1\t2\t.;rs123\tA\tG\t.\tPASS\t.\n", "VCF_ID_INVALID"),
        ("1\t2\t.\tX\tG\t.\tPASS\t.\n", "VCF_REF_INVALID"),
        ("1\t2\t.\tA\tG\t-1\tPASS\t.\n", "VCF_QUAL_INVALID"),
        ("1\t2\t.\tA\tG\t.\tBAD;\t.\n", "VCF_FILTER_INVALID"),
        ("1\t2\t.\tA\tG\t.\t0\t.\n", "VCF_FILTER_INVALID"),
        ("1\t2\t.\tA\tG\t.\tLowQual;LowQual\t.\n", "VCF_FILTER_INVALID"),
        ("1\t2\t.\tA\tG\t.\tPASS;LowQual\t.\n", "VCF_FILTER_INVALID"),
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


@pytest.mark.parametrize("version", ["VCFv4.2", "VCFv4.3"])
def test_strict_validation_accepts_only_declared_supported_vcf_versions(
    tmp_path: Path, version: str
):
    path = tmp_path / f"{version}.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\t.\n", version=version)

    profile = validate_vcf_strict(path, reference_contigs={"1"})

    assert profile["records"] == 1


@pytest.mark.parametrize("version", ["VCFv4.1", "VCFv4.4", "VCFv4.5"])
def test_strict_validation_rejects_unqualified_vcf_versions(
    tmp_path: Path, version: str
):
    path = tmp_path / f"{version}.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\t.\n", version=version)

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FILEFORMAT_UNSUPPORTED"
    assert "supported versions are VCFv4.2 and VCFv4.3" in str(exc.value)


@pytest.mark.parametrize(
    ("body", "duplicate_id"),
    [
        ("1\t2\trs1\tA\tG\t.\tPASS\t.\n1\t3\trs1\tC\tT\t.\tPASS\t.\n", "rs1"),
        ("1\t2\trs1;rs1\tA\tG\t.\tPASS\t.\n", "(?i)record id list"),
    ],
)
def test_strict_validation_rejects_duplicate_record_identifiers(
    tmp_path: Path, body: str, duplicate_id: str,
):
    path = tmp_path / "duplicate-record-id.vcf"
    write_vcf(path, body)

    with pytest.raises(StrictVCFValidationError, match=duplicate_id) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_ID_DUPLICATE"


@pytest.mark.parametrize("prefix", ["##source=test\n", "\n", "#comment\n"])
def test_strict_validation_requires_fileformat_on_first_line(tmp_path: Path, prefix: str):
    path = tmp_path / "misplaced-fileformat.vcf"
    path.write_text(
        prefix
        + "##fileformat=VCFv4.3\n"
        + "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FILEFORMAT_POSITION_INVALID"


@pytest.mark.parametrize("compressed", [False, True])
def test_strict_validation_rejects_utf8_bom(tmp_path: Path, compressed: bool):
    path = tmp_path / ("bom.vcf.gz" if compressed else "bom.vcf")
    content = (
        "\ufeff##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\n"
    )
    if compressed:
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            stream.write(content)
    else:
        path.write_text(content, encoding="utf-8")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_BOM_FORBIDDEN"


@pytest.mark.parametrize("control", ["\x00", "\x08", "\x0b", "\x0c", "\x1f"])
def test_strict_validation_rejects_vcf_forbidden_control_characters(
    tmp_path: Path, control: str,
):
    path = tmp_path / "control-character.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        f"##source=invalid{control}metadata\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_CONTROL_CHARACTER_INVALID"


def test_info_number_a_and_r_cardinality_is_checked_for_multiallelic_records(tmp_path: Path):
    path = tmp_path / "info-cardinality.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##INFO=<Description="Per-ALT frequency, with comma",Type=Float,Number=A,ID=AF>',
            '##INFO=<ID=AD,Number=R,Type=Integer,Description="Read depths">',
        ],
        "1\t2\t.\tA\tC,G\t.\tPASS\tAF=0.1,0.2;AD=10,3,4\n",
    )

    assert validate_vcf_strict(path)["multiallelic_records"] == 1

    path.write_text(
        path.read_text(encoding="utf-8").replace("AF=0.1,0.2", "AF=0.1"),
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


@pytest.mark.parametrize(
    ("genotype", "pl_values", "expected_count"),
    [
        ("0/1", "0,1,2,3,4,5", 6),
        ("0/1/2", "0,1,2,3,4,5,6,7,8,9", 10),
    ],
)
def test_format_number_g_cardinality_uses_sample_ploidy(
    tmp_path: Path, genotype: str, pl_values: str, expected_count: int,
):
    path = tmp_path / "format-number-g.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">',
        ],
        f"1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:PL\t{genotype}:{pl_values}\n",
        sample=True,
    )

    assert validate_vcf_strict(path)["records"] == 1
    assert len(pl_values.split(",")) == expected_count


def test_format_number_r_rejects_wrong_per_sample_allele_count(tmp_path: Path):
    path = tmp_path / "format-number-r.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Read depths">',
        ],
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:AD\t0/1:12,4\n",
        sample=True,
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


def test_format_number_g_rejects_wrong_genotype_cardinality(tmp_path: Path):
    path = tmp_path / "format-number-g-invalid.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">',
        ],
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:PL\t0/1:0,1,2,3,4\n",
        sample=True,
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


@pytest.mark.parametrize("pl_values", ["0,1,2", "0,1,2,3,4,5", "0,1,2,3,4,5,6,7,8,9"])
def test_format_number_g_without_gt_does_not_assume_diploid_ploidy(
    tmp_path: Path, pl_values: str,
):
    path = tmp_path / "format-number-g-without-gt.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">'],
        f"1\t2\t.\tA\tC,G\t.\tPASS\t.\tPL\t{pl_values}\n",
        sample=True,
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1
    assert profile["unchecked_format_number_g_fields"] == ["PL"]


def test_strict_validation_rejects_duplicate_info_keys(tmp_path: Path):
    path = tmp_path / "duplicate-info-key.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\tDP=10;DP=11\n")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_INFO_INVALID"


@pytest.mark.parametrize(
    "metadata",
    [
        [
            '##FILTER=<ID=LowQual,Description="low quality">',
            '##FILTER=<ID=LowQual,Description="duplicate filter ID">',
        ],
        [
            '##contig=<ID=chr1,length=100>',
            '##contig=<ID=chr1,length=100>',
        ],
        [
            '##ALT=<ID=DEL,Description="Deletion">',
            '##ALT=<ID=DEL,Description="duplicate ALT ID">',
        ],
    ],
)
def test_strict_validation_rejects_duplicate_structured_header_ids(
    tmp_path: Path, metadata: list[str],
):
    path = tmp_path / "duplicate-structured-id.vcf"
    write_vcf_with_metadata(path, metadata, "1\t2\t.\tA\tG\t.\tPASS\t.\n")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


def test_structured_header_ids_are_unique_per_type(tmp_path: Path):
    path = tmp_path / "same-id-different-header-types.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##INFO=<ID=DP,Number=1,Type=Integer,Description="Depth">',
            '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Sample depth">',
        ],
        "1\t2\t.\tA\tG\t.\tPASS\tDP=10\tDP\t10\n",
        sample=True,
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("field_type", "value"),
    [
        ("Integer", "1.5"),
        ("Integer", "2147483648"),
        ("Float", "not-a-number"),
        ("Character", "too-long"),
    ],
)
def test_declared_info_payload_type_is_enforced(tmp_path: Path, field_type: str, value: str):
    path = tmp_path / "invalid-declared-type.vcf"
    write_vcf_with_metadata(
        path,
        [f'##INFO=<ID=X,Number=1,Type={field_type},Description="Typed value">'],
        f"1\t2\t.\tA\tG\t.\tPASS\tX={value}\n",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


@pytest.mark.parametrize("value", ["1.25e-3", "-INF", "nan", "."])
def test_declared_float_accepts_vcf_numeric_forms(tmp_path: Path, value: str):
    path = tmp_path / "valid-declared-float.vcf"
    write_vcf_with_metadata(
        path,
        ['##INFO=<ID=X,Number=1,Type=Float,Description="Typed value">'],
        f"1\t2\t.\tA\tG\t.\tPASS\tX={value}\n",
    )

    assert validate_vcf_strict(path)["records"] == 1


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


@pytest.mark.parametrize(
    ("records", "code"),
    [
        ("1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tMATEID=bnd2\n", "VCF_BREAKEND_SVTYPE_INVALID"),
        (
            "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=missing\n",
            "VCF_BREAKEND_MATE_MISSING",
        ),
        (
            "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\n"
            "2\t10\tbnd2\tA\tA]1:6]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\n",
            "VCF_BREAKEND_MATE_COORDINATE_MISMATCH",
        ),
    ],
)
def test_strict_validation_checks_breakend_type_and_mate_relationships(tmp_path, records, code):
    path = tmp_path / "invalid-breakend-pair.vcf"
    write_vcf(path, records)

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


def test_reference_validation_checks_preserved_gvcf_sv_breakend_and_spanning_records(tmp_path):
    fasta = tmp_path / "reference.fa"
    sequence = "A" * 30
    fasta.write_text(f">1\n{sequence}\n>2\n{sequence}\n", encoding="ascii", newline="\n")
    # FAI offsets are byte offsets to each sequence's first base. Both
    # sequences occupy one line, so line_width includes its newline byte.
    second_sequence_offset = len(f">1\n{sequence}\n>2\n".encode("ascii"))
    (tmp_path / "reference.fa.fai").write_text(
        f"1\t30\t3\t30\t31\n2\t30\t{second_sequence_offset}\t30\t31\n",
        encoding="ascii",
    )
    source = tmp_path / "mixed.g.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=30>\n##contig=<ID=2,length=30>\n"
        '##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t1\t.\tA\t<NON_REF>\t.\tPASS\tEND=4\tGT\t0/0\n"
        "1\t5\tdel1\tA\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=10\tGT\t0/1\n"
        "1\t11\tseqdel\tAA\tA\t.\tPASS\t.\tGT\t0/1\n"
        "1\t12\tstar1\tA\t*\t.\tPASS\t.\tGT\t0/1\n"
        # This same-bracket reciprocal pair follows the VCFv4.3 example
        # (bnd_W/bnd_Y); orientation is encoded by each ALT, not by requiring
        # the two records to use opposite bracket characters.
        "1\t15\tbnd1\tA\tA]2:20]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\tGT\t0/1\n"
        "2\t20\tbnd2\tA\tA]1:15]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\tGT\t0/1\n",
        encoding="ascii",
    )

    assert validate_vcf_strict(source)["records"] == 6
    profile = validate_vcf_reference_alleles(source, fasta)

    assert profile["result"] == "PASS"
    assert profile["checked_record_count"] == 6
    assert profile["checked_breakend_mate_count"] == 2


def test_reference_validation_rejects_ref_mismatch_in_preserved_symbolic_record(tmp_path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1\n" + "A" * 30 + "\n", encoding="ascii", newline="\n")
    (tmp_path / "reference.fa.fai").write_text("1\t30\t3\t30\t31\n", encoding="ascii")
    source = tmp_path / "mismatched-sv.vcf"
    write_vcf(source, "1\t5\tdel1\tC\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=10\n")
    validate_vcf_strict(source)

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_reference_alleles(source, fasta)

    assert exc.value.code == "VCF_REFERENCE_MISMATCH"


def test_reference_validation_marks_telomere_record_unvalidated_without_invalid_fasta_fetch(tmp_path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1\n" + "A" * 30 + "\n", encoding="ascii", newline="\n")
    (tmp_path / "reference.fa.fai").write_text("1\t30\t3\t30\t31\n", encoding="ascii")
    source = tmp_path / "telomere.vcf"
    write_vcf(source, "1\t0\ttelo\tA\tG\t.\tPASS\t.\n")
    validate_vcf_strict(source)

    profile = validate_vcf_reference_alleles(source, fasta)

    assert profile["result"] == "PARTIAL"
    assert profile["checked_record_count"] == 0
    assert profile["unvalidated_telomere_record_count"] == 1


def test_reference_validation_confirms_n_plus_one_telomere_against_selected_reference(tmp_path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1\n" + "A" * 30 + "\n", encoding="ascii", newline="\n")
    (tmp_path / "reference.fa.fai").write_text("1\t30\t3\t30\t31\n", encoding="ascii")
    source = tmp_path / "telomere-after-contig.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t31\ttelo-after\tA\tG\t.\tPASS\t.\n",
        encoding="ascii",
    )
    validate_vcf_strict(source)

    profile = validate_vcf_reference_alleles(source, fasta)

    assert profile["result"] == "PARTIAL"
    assert profile["checked_record_count"] == 0
    assert profile["unvalidated_telomere_record_count"] == 1


def test_reference_validation_rejects_vcf_contig_length_disagreement(tmp_path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1\n" + "A" * 30 + "\n", encoding="ascii", newline="\n")
    (tmp_path / "reference.fa.fai").write_text("1\t30\t3\t30\t31\n", encoding="ascii")
    source = tmp_path / "mismatched-contig-length.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=29>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t30\tlast-base\tA\tG\t.\tPASS\t.\n",
        encoding="ascii",
    )
    validate_vcf_strict(source)

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_reference_alleles(source, fasta)

    assert exc.value.code == "VCF_CONTIG_LENGTH_MISMATCH"
