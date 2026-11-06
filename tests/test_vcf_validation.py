import struct
from pathlib import Path
import zlib

import pytest

from backend.app.domain.vcf_feature_compatibility import feature_compatibility_for_version
from backend.app.domain.vcf_spec_registry import get_vcf_specification_profile
from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    _validate_record,
    read_vcf_fileformat,
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


def _bgzf_block(data: bytes) -> bytes:
    compressor = zlib.compressobj(level=6, wbits=-15)
    payload = compressor.compress(data) + compressor.flush()
    header = (
        b"\x1f\x8b\x08\x04" + b"\0" * 4 + b"\0\xff"
        + struct.pack("<H", 6) + b"BC\x02\0"
    )
    block_size = len(header) + 2 + len(payload) + 8
    header += struct.pack("<H", block_size - 1)
    return header + payload + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))


def write_vcf_with_metadata(
    path: Path,
    metadata: list[str],
    body: str,
    *,
    sample: bool = False,
    version: str = "VCFv4.3",
) -> None:
    columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
    if sample:
        columns += "\tFORMAT\tSAMPLE1"
    path.write_text(
        f"##fileformat={version}\n"
        + "\n".join(metadata)
        + "\n"
        + columns
        + "\n"
        + body,
        encoding="utf-8",
    )


def test_read_vcf_fileformat_identifies_future_version_before_parser_validation(tmp_path: Path):
    path = tmp_path / "future.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\t.\n", version="VCFv4.6")

    assert read_vcf_fileformat(path) == "VCFv4.6"


def test_read_vcf_fileformat_supports_bgzf_gzip_streams(tmp_path: Path):
    path = tmp_path / "future.vcf.gz"
    content = (
        b"##fileformat=VCFv4.6\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"1\t2\t.\tA\tG\t.\tPASS\t.\n"
    )
    path.write_bytes(_bgzf_block(content) + _bgzf_block(b""))

    assert read_vcf_fileformat(path) == "VCFv4.6"


def test_strict_validation_accepts_standard_vcf(tmp_path: Path):
    path = tmp_path / "valid.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\t.\n")
    profile = validate_vcf_strict(path, reference_contigs={"1"})
    assert profile["records"] == 1
    assert profile["reference_contig_policy"] == "EXACT_OR_EXPLICIT_ALIAS"


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
        "1\t2\t.\tA\tG\t.\tPASS\t_CUSTOM=7;1000G;NOTE=a%3Db\tGT:_GX\t0/1:9\n",
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
        '##contig=<assembly="GRCh38",length=10,ID="chr_1">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr_1\t11\ttelo-after\tA\tG\t.\tPASS\t.\n",
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
        ("1\t2\t.\tA\tG\t.\tPASS\tNOTE=a=b\n", "VCF_INFO_INVALID"),
        ("1\t2\t.\tA\tG\t.\tPASS\tNOTE=100%\n", "VCF_INFO_INVALID"),
        ("1\t2\t.\tA\tG\t.\tPASS\tNOTE=%GG\n", "VCF_INFO_INVALID"),
        ("1\t2\t.\tA\tG\t.\tPASS\tNOTE=a%3db\n", "VCF_INFO_INVALID"),
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


def test_strict_validation_rejects_ordinary_gzip_with_vcf_suffix(tmp_path: Path):
    import gzip

    path = tmp_path / "ordinary-gzip.vcf.gz"
    content = (
        b"##fileformat=VCFv4.3\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"1\t2\t.\tA\tG\t.\tPASS\t.\n"
    )
    with gzip.open(path, "wb") as stream:
        stream.write(content)

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_BGZF_REQUIRED"


@pytest.mark.parametrize(
    "version", ["VCFv4.0", "VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"]
)
def test_strict_validation_accepts_standardized_vcf_4x_versions(
    tmp_path: Path, version: str
):
    path = tmp_path / f"{version}.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\t.\n", version=version)

    profile = validate_vcf_strict(path, reference_contigs={"1"})

    assert profile["records"] == 1
    assert profile["fileformat"] == version


def test_strict_validation_rejects_nonexistent_future_vcf_major_version(tmp_path: Path):
    path = tmp_path / "future-v5.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\t.\n", version="VCFv5.0")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FILEFORMAT_UNSUPPORTED"
    assert "VCFv4.0 through VCFv4.5" in str(exc.value)


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
        content_bytes = content.encode("utf-8")
        path.write_bytes(_bgzf_block(content_bytes) + _bgzf_block(b""))
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
    ("field_id", "field_type"),
    [("PL", "Integer"), ("GL", "Float"), ("GP", "Float")],
)
@pytest.mark.parametrize(
    ("genotype", "values", "expected_count"),
    [
        # Number=G cardinality is C(number_of_alleles + ploidy - 1, ploidy).
        # Three alleles (REF + two ALT): haploid=3, diploid=6,
        # triploid=10, and tetraploid=15.
        ("1", "0,1,2", 3),
        ("0/1", "0,1,2,3,4,5", 6),
        ("0/1/2", "0,1,2,3,4,5,6,7,8,9", 10),
        ("0/1/2/2", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14", 15),
    ],
)
def test_format_number_g_cardinality_uses_sample_ploidy(
    tmp_path: Path,
    field_id: str,
    field_type: str,
    genotype: str,
    values: str,
    expected_count: int,
):
    # GP is a probability vector: use finite values in [0, 1] that sum to 1.
    # PL and GL fixtures intentionally test cardinality/type, not calibration.
    if field_id == "GP":
        values = ",".join([f"{1 / expected_count:.8f}"] * expected_count)

    path = tmp_path / f"format-number-g-{field_id}.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            f'##FORMAT=<ID={field_id},Number=G,Type={field_type},Description="Genotype likelihood/probability values">',
        ],
        f"1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:{field_id}\t{genotype}:{values}\n",
        sample=True,
    )

    assert validate_vcf_strict(path)["records"] == 1
    assert len(values.split(",")) == expected_count


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


@pytest.mark.parametrize(
    ("pl_values", "valid"),
    [
        ("0,1,2,3,4,5", True),
        ("0,1,2", False),
        ("0,1,2,3,4,5,6,7,8,9", False),
    ],
)
def test_format_number_g_without_gt_uses_specified_diploid_default(
    tmp_path: Path, pl_values: str, valid: bool,
):
    path = tmp_path / "format-number-g-without-gt.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">'],
        f"1\t2\t.\tA\tC,G\t.\tPASS\t.\tPL\t{pl_values}\n",
        sample=True,
    )

    if valid:
        profile = validate_vcf_strict(path)
        assert profile["records"] == 1
        assert profile["unchecked_format_number_g_fields"] == []
    else:
        with pytest.raises(StrictVCFValidationError) as exc:
            validate_vcf_strict(path)
        assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


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


def test_info_number_g_with_mixed_sample_ploidy_is_explicitly_unchecked(tmp_path: Path):
    path = tmp_path / "info-number-g-mixed-ploidy.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##INFO=<ID=IG,Number=G,Type=Float,Description="Genotype-indexed site values">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHAPLOID\tDIPLOID\n"
        "1\t2\t.\tA\tC,G\t.\tPASS\tIG=0.1,0.2,0.3,0.1,0.1,0.2\tGT\t1\t0/1\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)

    # INFO is record-level, but sample genotypes can have different ploidies.
    # The validator must not guess a single Number=G cardinality.
    assert result["records"] == 1
    assert result["unchecked_info_number_g_fields"] == ["IG"]


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
        ("1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=DEL;MATEID=bnd2\n", "VCF_BREAKEND_SVTYPE_INVALID"),
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



@pytest.mark.parametrize("version", ["VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"])
def test_strict_validation_accepts_recognized_vcf_4x_versions(tmp_path: Path, version: str):
    path = tmp_path / f"{version}.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\t.\n", version=version)

    profile = validate_vcf_strict(path)

    assert profile["fileformat"] == version
    assert profile["records"] == 1
    assert profile["format_compatibility"]["support_status"] == "PARTIAL_FEATURE_QUALIFICATION"
    assert profile["format_compatibility"]["validation_mode"] == "VERSION_AWARE_PARTIAL"
    assert profile["format_compatibility"]["specification_repository"] == (
        "https://github.com/samtools/hts-specs"
    )
    if version == "VCFv4.5":
        assert profile["format_compatibility"]["specification_document"] == (
            "https://samtools.github.io/hts-specs/VCFv4.5.pdf"
        )


def test_vcf45_local_allele_cardinality_is_validated(tmp_path: Path):
    path = tmp_path / "local-alleles-v45.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">\n'
        '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">\n'
        '##FORMAT=<ID=LPL,Number=LG,Type=Integer,Description="Local genotype likelihoods">\n'
        '##FORMAT=<ID=CUSTOM_P,Number=P,Type=Integer,Description="Per-ploidy values">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC,G,T\t.\tPASS\t.\tGT:LAA:LAD:LPL:CUSTOM_P\t0/2:2:20,10:0,50,100:12,13\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["fileformat"] == "VCFv4.5"
    assert profile["records"] == 1


def test_vcf45_local_allele_fields_reject_out_of_range_laa_index(tmp_path: Path):
    path = tmp_path / "bad-local-alleles-v45.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">\n'
        '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:LAA:LAD\t0/1:3:20,10\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_LOCAL_ALLELE_INVALID"


def test_vcf44_rejects_vcf45_only_local_allele_cardinality(tmp_path: Path):
    path = tmp_path / "local-alleles-v44.vcf"
    path.write_text(
        "##fileformat=VCFv4.4\n"
        '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tLAD\t20,10\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"



@pytest.mark.parametrize("version", ["VCFv4.4", "VCFv4.5"])
@pytest.mark.parametrize("gt", ["|0/1", "/0/1", "|0|1"])
def test_vcf44_and_vcf45_accept_leading_gt_phase_separator_and_correct_ploidy(
    tmp_path: Path, gt: str, version: str
):
    path = tmp_path / f"prefixed-gt-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tA\tG\t.\tPASS\t.\tGT\t{gt}\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1


def test_vcf43_rejects_vcf44_leading_gt_phase_separator(tmp_path: Path):
    path = tmp_path / "prefixed-gt-v43.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\tGT\t|0/1\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_GENOTYPE_INVALID"




@pytest.mark.parametrize("version", ["VCFv4.1", "VCFv4.2"])
def test_vcf41_vcf42_pedigree_uses_legacy_relationship_attributes_without_id(
    tmp_path: Path, version: str
):
    path = tmp_path / f"pedigree-legacy-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        "##PEDIGREE=<Derived=PROBAND,Original=MOTHER>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("version", ["VCFv4.3", "VCFv4.4", "VCFv4.5"])
def test_vcf43_plus_pedigree_structured_metadata_requires_id(
    tmp_path: Path, version: str
):
    path = tmp_path / f"pedigree-no-id-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        "##PEDIGREE=<Derived=PROBAND,Original=MOTHER>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


@pytest.mark.parametrize("version", ["VCFv4.3", "VCFv4.4", "VCFv4.5"])
def test_vcf43_plus_pedigree_structured_metadata_accepts_unique_id(
    tmp_path: Path, version: str
):
    path = tmp_path / f"pedigree-with-id-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        "##PEDIGREE=<ID=PROBAND,Original=MOTHER>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_strict_validation_rejects_format_column_without_sample_columns(tmp_path: Path):
    path = tmp_path / "format-without-sample.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\tGT\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_INVALID"


@pytest.mark.parametrize(
    ("field_id", "reference", "alternate", "genotype", "value", "expected_count", "info"),
    [
        ("M5mC", "C", "A", "0/1", "0.95", 1, "."),
        ("M5mC", "C", "CTAG", "0/1", "0,0.5,0.7", 3, "."),
        ("M5mC", "C", ".", "0|0", "0.9,0", 2, "."),
        (
            "M5mC",
            "C",
            "A,T,G,ACG",
            "/3|1/0|4|0/0/3/1",
            "0.25,0.1,0.5,0.6,.",
            5,
            ".",
        ),
        ("M5mC", "C", "A", "0/0", "0.9", 1, "."),
        ("M5mC", "C", "A", "0|0", "0.9,0", 2, "."),
        ("M5mC", "C", "CTAG", "0/.", "0.9", 1, "."),
        ("M5mC", "C", "<DEL>", "0/1", "0.9", 1, "END=10"),
        ("M5mU", "T", "A", "0/1", "0.1,0.2", 2, "."),
        ("M5mN", "A", "T", "0/1", "0.1,0.2,0.3,0.4", 4, "."),
    ],
)
def test_vcf45_number_m_base_modification_cardinality(
    tmp_path: Path,
    field_id: str,
    reference: str,
    alternate: str,
    genotype: str,
    value: str,
    expected_count: int,
    info: str,
):
    path = tmp_path / "base-modification.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            f'##FORMAT=<ID={field_id},Number=M,Type=Float,Description="Base modification fraction">',
        ],
        f"1\t2\t.\t{reference}\t{alternate}\t.\tPASS\t{info}\tGT:{field_id}\t{genotype}:{value}\n",
        sample=True,
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1
    assert len(value.split(",")) == expected_count


def test_vcf45_number_m_accepts_integer_depth_fields(tmp_path: Path):
    path = tmp_path / "base-modification-depth.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=DPM5mC,Number=M,Type=Integer,Description="Modification-callable depth">',
            '##FORMAT=<ID=ADM5mC,Number=M,Type=Integer,Description="Modified-base depth">',
        ],
        "1\t2\t.\tC\tCTAG\t.\tPASS\t.\tGT:DPM5mC:ADM5mC\t0/1:10,20,30:1,2,3\n",
        sample=True,
        version="VCFv4.5",
    )

    assert validate_vcf_strict(path)["records"] == 1


def test_vcf45_number_m_rejects_wrong_cardinality(tmp_path: Path):
    path = tmp_path / "base-modification-wrong-cardinality.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5-methylcytosine fraction">',
        ],
        "1\t2\t.\tC\tCTAG\t.\tPASS\t.\tGT:M5mC\t0/1:0.5,0.7\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


@pytest.mark.parametrize(
    ("version", "metadata", "expected_code"),
    [
        (
            "VCFv4.4",
            ['##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5mC">'],
            "VCF_HEADER_DEFINITION_INVALID",
        ),
        (
            "VCFv4.5",
            ['##INFO=<ID=M5mC,Number=M,Type=Float,Description="5mC">'],
            "VCF_HEADER_DEFINITION_INVALID",
        ),
        (
            "VCFv4.5",
            ['##FORMAT=<ID=M5mX,Number=M,Type=Float,Description="invalid base suffix">'],
            "VCF_HEADER_DEFINITION_INVALID",
        ),
        (
            "VCFv4.5",
            ['##FORMAT=<ID=M5mC,Number=M,Type=String,Description="invalid type">'],
            "VCF_HEADER_DEFINITION_INVALID",
        ),
    ],
)
def test_number_m_is_vcf45_format_only_with_valid_base_and_numeric_type(
    tmp_path: Path,
    version: str,
    metadata: list[str],
    expected_code: str,
):
    path = tmp_path / "invalid-number-m.vcf"
    write_vcf_with_metadata(
        path,
        metadata,
        "1\t2\t.\tC\tA\t.\tPASS\t.\tGT\t0/1\n",
        sample=True,
        version=version,
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == expected_code


def test_vcf45_base_modification_fields_require_sample_gt(tmp_path: Path):
    path = tmp_path / "base-modification-no-gt.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5mC">'],
        "1\t2\t.\tC\tA\t.\tPASS\t.\tM5mC\t0.5\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_BASE_MODIFICATION_GT_MISSING"


def test_vcf45_base_modification_missing_gt_allele_contributes_no_values(tmp_path: Path):
    path = tmp_path / "base-modification-partial-gt.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5-methylcytosine fraction">',
        ],
        "1\t2\t.\tC\tCTAG\t.\tPASS\t.\tGT:M5mC\t0/.:0.9\n",
        sample=True,
        version="VCFv4.5",
    )

    assert validate_vcf_strict(path)["records"] == 1


def test_vcf45_reserved_base_modification_aliases_need_no_header_definitions(tmp_path: Path):
    path = tmp_path / "reserved-base-modifications-no-definitions.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\t2\t.\tC\tCTAG\t.\tPASS\t.\tGT:M5mC\t0/1:0,0.5,0.7\n",
        sample=True,
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(path)
    assert profile["records"] == 1
    assert profile["base_modification_format_fields"] == ["M5mC"]


def test_vcf45_reserved_depth_aliases_need_no_header_definitions(tmp_path: Path):
    path = tmp_path / "reserved-base-modification-depth-no-definitions.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\t2\t.\tC\tCTAG\t.\tPASS\t.\tGT:DPM5mC:ADM5mC\t0/1:10,20,30:1,2,3\n",
        sample=True,
        version="VCFv4.5",
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    "field_id",
    ["MXaoN", "MxaoN", "DPMXaoN", "DPMxaoN", "ADMXaoN", "ADMxaoN"],
)
def test_vcf45_ambiguous_xanthosine_aliases_are_blocked_without_header_definition(
    tmp_path: Path, field_id: str
):
    path = tmp_path / "ambiguous-xanthosine-alias.vcf"
    write_vcf_with_metadata(
        path,
        [],
        f"1\t2\t.\tC\tT\t.\tPASS\t.\tGT:{field_id}\t0/1:1\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_BASE_MODIFICATION_ALIAS_AMBIGUOUS"


@pytest.mark.parametrize(
    ("field_id", "field_type"),
    [
        ("MXaoN", "Float"),
        ("MxaoN", "Float"),
        ("DPMXaoN", "Integer"),
        ("DPMxaoN", "Integer"),
        ("ADMXaoN", "Integer"),
        ("ADMxaoN", "Integer"),
    ],
)
def test_vcf45_ambiguous_xanthosine_aliases_are_blocked_in_header_definitions(
    tmp_path: Path, field_id: str, field_type: str
):
    path = tmp_path / "ambiguous-xanthosine-alias-header.vcf"
    write_vcf_with_metadata(
        path,
        [
            f'##FORMAT=<ID={field_id},Number=M,Type={field_type},Description="Ambiguous upstream alias">'
        ],
        f"1\t2\t.\tC\tT\t.\tPASS\t.\tGT:{field_id}\t0/1:1\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_BASE_MODIFICATION_ALIAS_AMBIGUOUS"


def test_vcf45_reserved_base_modification_fraction_must_be_between_zero_and_one(
    tmp_path: Path,
):
    path = tmp_path / "base-modification-out-of-range.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\t2\t.\tC\tA\t.\tPASS\t.\tGT:M5mC\t0/1:1.01\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


def test_vcf45_reserved_base_modification_depth_must_be_nonnegative(tmp_path: Path):
    path = tmp_path / "base-modification-negative-depth.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\t2\t.\tC\tCTAG\t.\tPASS\t.\tGT:DPM5mC\t0/1:-1,20,30\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


def test_vcf45_reserved_base_modification_header_cannot_override_builtin_type_or_number(
    tmp_path: Path,
):
    path = tmp_path / "base-modification-overridden-definition.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=M5mC,Number=1,Type=Float,Description="Incorrect override">'],
        "1\t2\t.\tC\tA\t.\tPASS\t.\tGT:M5mC\t0/1:0.5\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


def test_vcf45_len_only_reference_block_is_accepted_and_counted_per_sample(tmp_path: Path):
    path = tmp_path / "vcf45-len-only.vcf"
    write_vcf_with_metadata(
        path,
        ['##contig=<ID=1,length=200>', '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">'],
        "1\t100\t.\tA\t<*>\t.\tPASS\t.\tGT:LEN\t0/0:50\n",
        sample=True,
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(path)

    assert profile["vcf45_reference_span_records"] == 1
    assert profile["vcf45_reference_block_sample_count"] == 1
    assert profile["vcf45_max_reference_end"] == 149


def test_vcf45_non_ref_is_alias_for_star_reference_block_len(tmp_path: Path):
    path = tmp_path / "vcf45-non-ref-len-only.vcf"
    write_vcf_with_metadata(
        path,
        ['##contig=<ID=1,length=200>', '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">'],
        "1\t100\t.\tA\t<NON_REF>\t.\tPASS\t.\tGT:LEN\t0/0:25\n",
        sample=True,
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(path)

    assert profile["vcf45_max_reference_end"] == 124
    assert profile["vcf45_reference_block_sample_count"] == 1


def test_vcf45_end_must_equal_maximum_sample_len_end(tmp_path: Path):
    path = tmp_path / "vcf45-len-end.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "##contig=<ID=1,length=200>\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\tSAMPLE2\n"
        "1\t100\t.\tA\t<*>\t.\tPASS\tEND=124\tGT:LEN\t0/0:10\t0/0:25\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["vcf45_max_reference_end"] == 124
    assert profile["vcf45_reference_block_sample_count"] == 2


@pytest.mark.parametrize("end_value", ["123", "125"])
def test_vcf45_end_rejects_mismatch_with_complete_sample_len_values(tmp_path: Path, end_value: str):
    path = tmp_path / "vcf45-len-end-mismatch.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">'],
        f"1\t100\t.\tA\t<*>\t.\tPASS\tEND={end_value}\tGT:LEN\t0/0:25\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_END_MISMATCH"


@pytest.mark.parametrize("length", ["0", "-1", "abc", "0.5", "2147483648"])
def test_vcf45_len_rejects_invalid_integer_or_range(tmp_path: Path, length: str):
    path = tmp_path / "vcf45-invalid-len.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">'],
        f"1\t100\t.\tA\t<*>\t.\tPASS\t.\tGT:LEN\t0/0:{length}\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError):
        validate_vcf_strict(path)


def test_vcf45_len_requires_reference_genotype(tmp_path: Path):
    path = tmp_path / "vcf45-len-invalid-gt.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">'],
        "1\t100\t.\tA\t<*>\t.\tPASS\t.\tGT:LEN\t0/1:10\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_LEN_GENOTYPE_INVALID"


def test_vcf45_len_must_include_star_in_laa_when_laa_is_present(tmp_path: Path):
    path = tmp_path / "vcf45-len-laa-invalid.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">'],
        "1\t100\t.\tA\tC,<*>\t.\tPASS\t.\tGT:LAA:LEN\t0/0:1:10\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_GVCF_BLOCK_LAA_INVALID"


def test_vcf45_records_inside_reference_block_require_missing_gt_and_empty_other_fields(tmp_path: Path):
    path = tmp_path / "vcf45-block-coverage-valid.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Depth">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t100\t.\tA\t<*>\t.\tPASS\t.\tGT:LEN\t0/0:10\n"
        "1\t105\t.\tA\tC\t.\tPASS\t.\tGT:DP\t.:.\n"
        "1\t110\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 3


@pytest.mark.parametrize(("genotype", "depth"), [("0/1", "."), (".", "20")])
def test_vcf45_records_inside_reference_block_reject_populated_sample_fields(
    tmp_path: Path, genotype: str, depth: str
):
    path = tmp_path / "vcf45-block-coverage-invalid.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Depth">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t100\t.\tA\t<*>\t.\tPASS\t.\tGT:LEN\t0/0:10\n"
        f"1\t105\t.\tA\tC\t.\tPASS\t.\tGT:DP\t{genotype}:{depth}\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_GVCF_BLOCK_OVERLAP_INVALID"


def test_vcf45_reference_blocks_are_tracked_per_sample_with_different_lengths(tmp_path: Path):
    path = tmp_path / "vcf45-multisample-blocks.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Depth">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\tSAMPLE2\n"
        "1\t100\t.\tA\t<*>\t.\tPASS\tEND=119\tGT:LEN\t0/0:10\t0/0:20\n"
        "1\t110\t.\tA\tC\t.\tPASS\t.\tGT:DP\t0/1:30\t.:.\n"
        "1\t120\t.\tA\tG\t.\tPASS\t.\tGT:DP\t0/1:30\t0/1:30\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 3
    assert profile["vcf45_reference_block_sample_count"] == 2


def test_vcf45_len_derived_span_must_fit_declared_contig_length(tmp_path: Path):
    path = tmp_path / "vcf45-len-out-of-bounds.vcf"
    write_vcf_with_metadata(
        path,
        ['##contig=<ID=1,length=120>', '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">'],
        "1\t100\t.\tA\t<*>\t.\tPASS\t.\tGT:LEN\t0/0:50\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_REFERENCE_SPAN_OUT_OF_BOUNDS"


def test_vcf44_non_ref_reference_block_still_requires_end(tmp_path: Path):
    path = tmp_path / "vcf44-non-ref-no-end.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">'],
        "1\t100\t.\tA\t<NON_REF>\t.\tPASS\t.\tGT\t0/0\n",
        sample=True,
        version="VCFv4.4",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_GVCF_BLOCK_INVALID"


def test_vcf45_len_derived_reference_span_is_checked_against_selected_reference(tmp_path: Path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1\n" + "A" * 30 + "\n", encoding="ascii", newline="\n")
    (tmp_path / "reference.fa.fai").write_text("1\t30\t3\t30\t31\n", encoding="ascii")
    source = tmp_path / "vcf45-len-out-of-bounds-reference.vcf"
    write_vcf_with_metadata(
        source,
        [],
        "1\t20\t.\tA\t<*>\t.\tPASS\t.\tGT:LEN\t0/0:15\n",
        sample=True,
        version="VCFv4.5",
    )
    validate_vcf_strict(source)

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_reference_alleles(source, fasta)

    assert exc.value.code == "VCF_REFERENCE_SPAN_OUT_OF_BOUNDS"


def test_vcf45_symbolic_insertion_svleng_contributes_to_computed_end(tmp_path: Path):
    path = tmp_path / "vcf45-insertion-svlen.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\t100\t.\tA\t<INS>\t.\tPASS\tSVLEN=5\n",
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(path)

    assert profile["vcf45_max_reference_end"] == 105


def test_vcf45_end_must_match_symbolic_insertion_svleng(tmp_path: Path):
    path = tmp_path / "vcf45-insertion-end.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\t100\t.\tA\t<INS>\t.\tPASS\tSVLEN=5;END=105\n",
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(path)

    assert profile["vcf45_max_reference_end"] == 105


def test_vcf45_svleng_must_be_missing_for_sequence_alt(tmp_path: Path):
    path = tmp_path / "vcf45-svlen-sequence-alt.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\t100\t.\tA\tG\t.\tPASS\tSVLEN=5\n",
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_SVLEN_INVALID"


@pytest.mark.parametrize(
    "version",
    ["VCFv4.0", "VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"],
)
def test_core_info_and_format_cardinality_contract_is_stable_across_vcf_versions(
    tmp_path: Path, version: str
):
    """Exercise shared Number=A/R/G semantics across every accepted VCF 4.x version."""
    path = tmp_path / f"core-cardinality-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        '##INFO=<ID=AF,Number=A,Type=Float,Description="Allele frequency">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC,G\t.\tPASS\tAF=0.1,0.2\tGT:AD:PL\t1/2:10,4,6:0,10,20,30,40,50\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["fileformat"] == version
    assert profile["records"] == 1
    assert profile["multiallelic_records"] == 1


@pytest.mark.parametrize(
    "version",
    ["VCFv4.0", "VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"],
)
def test_core_multiallelic_cardinality_mismatch_is_rejected_across_vcf_versions(
    tmp_path: Path, version: str
):
    """A version label must not weaken allele-indexed field validation."""
    path = tmp_path / f"bad-core-cardinality-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        '##INFO=<ID=AF,Number=A,Type=Float,Description="Allele frequency">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC,G\t.\tPASS\tAF=0.1\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"



@pytest.mark.parametrize(
    ("alt", "expected"),
    [
        ("a", ["A"]),
        ("<del>", ["<del>"]),
        ("<DEL>,<del>", ["<DEL>", "<del>"]),
        ("A]chr1:123]", ["A]chr1:123]"]),
        ("a]chr1:123]", ["a]chr1:123]"]),
    ],
)
def test_alt_case_normalization_preserves_symbolic_ids_and_breakend_contigs(
    alt: str, expected: list[str]
):
    fields = ["1", "100", ".", "A", alt, ".", "PASS", "END=100" if "<" in alt else "SVTYPE=BND" if "[" in alt or "]" in alt else "."]

    _chrom, _position, observed = _validate_record(fields, 1, None, "VCFv4.5")

    assert observed == expected


@pytest.mark.parametrize(
    ("alt", "info"),
    [
        ("C,C", "."),
        ("<DEL>,<DEL>", "SVLEN=-10,-10"),
        ("<CNV:TR>,<CNV:TR>", "SVLEN=100,100"),
    ],
)
def test_vcf45_repeated_alt_values_preserve_distinct_allele_indexes(alt: str, info: str):
    fields = ["1", "100", ".", "A", alt, ".", "PASS", info]

    _validate_record(fields, 1, None, "VCFv4.5")


@pytest.mark.parametrize("alt", ["<DEL,FOO>", "<DEL FOO>", "<<DEL>>", "A]chr 1:123]"])
def test_malformed_symbolic_and_breakend_alt_identifiers_are_rejected(alt: str):
    fields = ["1", "100", ".", "A", alt, ".", "PASS", "."]

    with pytest.raises(StrictVCFValidationError) as exc:
        _validate_record(fields, 1, None, "VCFv4.5")

    assert exc.value.code == "VCF_ALT_INVALID"


def test_vcf45_local_allele_array_must_include_each_called_gt_alt(tmp_path: Path):
    path = tmp_path / "vcf45-laa-omits-called-alt.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">',
            '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">',
        ],
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:LAA:LAD\t0/1:2:20,10\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_LOCAL_ALLELE_INVALID"


def test_vcf45_empty_laa_cannot_describe_called_alt_genotype(tmp_path: Path):
    path = tmp_path / "vcf45-empty-laa-called-alt.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">',
            '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">',
        ],
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:LAA:LAD\t0/1:.:20\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_LOCAL_ALLELE_INVALID"


@pytest.mark.parametrize(
    "metadata,kind,identifier",
    [
        ('##FORMAT=<ID=LAA,Number=1,Type=Integer,Description="Local ALT indices">', "FORMAT", "LAA"),
        ('##FORMAT=<ID=GT,Number=2,Type=String,Description="Genotype">', "FORMAT", "GT"),
        ('##FORMAT=<ID=PSL,Number=P,Type=Integer,Description="Phase set list">', "FORMAT", "PSL"),
        ('##INFO=<ID=AF,Number=1,Type=Float,Description="Allele frequency">', "INFO", "AF"),
        ('##INFO=<ID=DP,Number=1,Type=Float,Description="Read depth">', "INFO", "DP"),
        ('##INFO=<ID=MQ,Number=1,Type=Integer,Description="RMS mapping quality">', "INFO", "MQ"),
    ],
)
def test_vcf45_reserved_field_definitions_enforce_spec_number_and_type(
    tmp_path: Path, metadata: str, kind: str, identifier: str
):
    path = tmp_path / f"vcf45-reserved-{kind.lower()}-{identifier}.vcf"
    write_vcf_with_metadata(
        path,
        [metadata],
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


@pytest.mark.parametrize(
    ("info", "expected_code"),
    [
        ("DP=not-an-integer", "VCF_FIELD_TYPE_INVALID"),
        ("AF=0.1,0.2", "VCF_FIELD_CARDINALITY_INVALID"),
        ("DB=1", "VCF_FIELD_CARDINALITY_INVALID"),
    ],
)
def test_vcf45_implicit_reserved_info_definitions_validate_record_values(
    tmp_path: Path, info: str, expected_code: str
):
    path = tmp_path / "vcf45-implicit-info.vcf"
    write_vcf(path, f"1\t2\t.\tA\tC\t.\tPASS\t{info}\n", version="VCFv4.5")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == expected_code


def test_vcf45_ps_must_be_nonnegative(tmp_path: Path):
    path = tmp_path / "vcf45-negative-ps.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=PS,Number=1,Type=Integer,Description="Phase set">'],
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:PS\t0|1:-1\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


def test_vcf45_ps_and_psl_cannot_both_be_populated_for_one_sample(tmp_path: Path):
    path = tmp_path / "vcf45-ps-and-psl.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=PS,Number=1,Type=Integer,Description="Phase set">',
            '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">',
        ],
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:PS:PSL\t0|1:10:chr1*2*1,.\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_PHASE_SET_INVALID"


@pytest.mark.parametrize(
    "gt,psl",
    [
        ("0/1", "chr1*2*1,."),
        ("|0/1", "chr1*2*1,chr1*2*1"),
    ],
)
def test_vcf45_psl_requires_missing_value_for_unphased_gt_alleles(
    tmp_path: Path, gt: str, psl: str
):
    path = tmp_path / "vcf45-psl-unphased-allele.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">'],
        f"1\t2\t.\tA\tC\t.\tPASS\t.\tGT:PSL\t{gt}:{psl}\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_PHASE_SET_INVALID"


def test_vcf45_psl_accepts_phase_set_only_for_explicitly_phased_gt_allele(tmp_path: Path):
    path = tmp_path / "vcf45-psl-partially-phased.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">'],
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:PSL\t|0/1:chr1*2*1,.\n",
        sample=True,
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 1


@pytest.mark.parametrize("version", ["VCFv4.0", "VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4"])
def test_duplicate_alt_entries_are_not_rejected_by_legacy_version_contracts(version: str):
    fields = ["1", "100", ".", "A", "C,c", ".", "PASS", "."]

    _chrom, _position, observed = _validate_record(fields, 1, None, version)

    assert observed == ["C", "C"]


def test_variable_number_info_fields_still_validate_declared_value_type(tmp_path: Path):
    path = tmp_path / "variable-number-info-invalid-type.vcf"
    write_vcf_with_metadata(
        path,
        ['##INFO=<ID=CUSTOM,Number=.,Type=Integer,Description="Variable integer list">'],
        "1\t2\t.\tA\tC\t.\tPASS\tCUSTOM=1,not-an-integer\n",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


def test_variable_number_format_fields_still_validate_declared_value_type(tmp_path: Path):
    path = tmp_path / "variable-number-format-invalid-type.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=CUSTOM,Number=.,Type=Integer,Description="Variable integer list">'],
        "1\t2\t.\tA\tC\t.\tPASS\t.\tCUSTOM\t1,not-an-integer\n",
        sample=True,
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


def test_number_g_fields_without_gt_still_validate_declared_value_type(tmp_path: Path):
    path = tmp_path / "unresolved-number-g-invalid-type.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">'],
        "1\t2\t.\tA\tC\t.\tPASS\t.\tPL\t0,not-an-integer,2\n",
        sample=True,
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


def test_vcf45_cipos_requires_two_offsets_per_alt_and_interval_spanning_zero(tmp_path: Path):
    valid = tmp_path / "vcf45-cipos-valid.vcf"
    write_vcf(valid, "1\t2\t.\tA\t<DEL>,<DUP>\t.\tPASS\tSVLEN=-4,-2;CIPOS=-2,2,0,0\n", version="VCFv4.5")

    profile = validate_vcf_strict(valid)
    assert profile["records"] == 1

    invalid = tmp_path / "vcf45-cipos-invalid.vcf"
    write_vcf(invalid, "1\t2\t.\tA\tC\t.\tPASS\tCIPOS=1,2\n", version="VCFv4.5")
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(invalid)
    assert exc.value.code == "VCF_SV_INFO_INTERVAL_INVALID"


def test_vcf45_imprecise_requires_cipos_for_precise_alt_but_allows_unspecified_symbolic_sv(tmp_path: Path):
    missing_cipos = tmp_path / "vcf45-imprecise-precise-alt-missing-cipos.vcf"
    write_vcf(
        missing_cipos,
        "1\t2\t.\tA\tC\t.\tPASS\tIMPRECISE\n",
        version="VCFv4.5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(missing_cipos)
    assert exc.value.code == "VCF_SV_IMPRECISE_CIPOS_MISSING"

    explicit_precise_cipos = tmp_path / "vcf45-imprecise-precise-alt-explicit-cipos.vcf"
    write_vcf(
        explicit_precise_cipos,
        "1\t2\t.\tA\tC\t.\tPASS\tIMPRECISE;CIPOS=0,0\n",
        version="VCFv4.5",
    )
    assert validate_vcf_strict(explicit_precise_cipos)["records"] == 1

    unspecified_symbolic_sv = tmp_path / "vcf45-imprecise-symbolic-sv-unspecified-cipos.vcf"
    write_vcf(
        unspecified_symbolic_sv,
        "1\t100\t.\tN\t<DEL>\t.\tPASS\tIMPRECISE;SVTYPE=DEL;END=110\n",
        version="VCFv4.5",
    )
    assert validate_vcf_strict(unspecified_symbolic_sv)["records"] == 1


def test_vcf45_ciend_must_be_missing_for_non_symbolic_alleles(tmp_path: Path):
    path = tmp_path / "vcf45-ciend-on-sequence-allele.vcf"
    write_vcf(path, "1\t2\t.\tA\tC\t.\tPASS\tCIEND=-1,1\n", version="VCFv4.5")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_SV_INFO_INTERVAL_INVALID"


def test_vcf45_meinfo_accepts_empty_string_missing_values_and_checks_cardinality(tmp_path: Path):
    valid = tmp_path / "vcf45-meinfo-empty-values.vcf"
    write_vcf(
        valid,
        "1\t100\t.\tN\t<INS>\t.\tPASS\tSVTYPE=INS;END=110;MEINFO=,,,\n",
        version="VCFv4.5",
    )
    profile = validate_vcf_strict(valid)
    assert profile["records"] == 1

    invalid = tmp_path / "vcf45-meinfo-wrong-cardinality.vcf"
    write_vcf(
        invalid,
        "1\t100\t.\tN\t<INS>\t.\tPASS\tSVTYPE=INS;END=110;MEINFO=foo,bar\n",
        version="VCFv4.5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(invalid)
    assert exc.value.code == "VCF_SV_INFO_CARDINALITY_INVALID"


@pytest.mark.parametrize(
    "metadata",
    [
        '##INFO=<ID=CIPOS,Number=2,Type=Integer,Description="Confidence interval">',
        '##INFO=<ID=MEINFO,Number=A,Type=String,Description="Mobile element information">',
        '##INFO=<ID=IMPRECISE,Number=1,Type=Flag,Description="Imprecise structural variation">',
        '##INFO=<ID=CILEN,Number=2,Type=Integer,Description="Confidence interval for SVLEN">',
    ],
)
def test_vcf45_reserved_structural_info_definitions_are_enforced(tmp_path: Path, metadata: str):
    path = tmp_path / "vcf45-invalid-structural-info-definition.vcf"
    write_vcf_with_metadata(path, [metadata], "1\t2\t.\tA\tC\t.\tPASS\t.\n", version="VCFv4.5")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


@pytest.mark.parametrize(
    "info",
    ["DP=-1", "AC=-1", "AF=1.01", "BQ=-0.1", "MQ=-1"],
)
def test_vcf45_reserved_info_numeric_domains_are_enforced(tmp_path: Path, info: str):
    path = tmp_path / "vcf45-invalid-info-domain.vcf"
    write_vcf(path, f"1\t2\t.\tA\tC\t.\tPASS\t{info}\n", version="VCFv4.5")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


@pytest.mark.parametrize(
    "format_key,number,field_type,sample_value",
    [
        ("DP", "1", "Integer", "-1"),
        ("AD", "R", "Integer", "10,-1"),
        ("GP", "G", "Float", "1.1,0.0,0.0"),
        ("PL", "G", "Integer", "0,-1,2"),
        ("GQ", "1", "Integer", "-1"),
    ],
)
def test_vcf45_reserved_format_numeric_domains_are_enforced(
    tmp_path: Path, format_key: str, number: str, field_type: str, sample_value: str
):
    path = tmp_path / "vcf45-invalid-format-domain.vcf"
    write_vcf_with_metadata(
        path,
        [f'##FORMAT=<ID={format_key},Number={number},Type={field_type},Description="Reserved field">'],
        f"1\t2\t.\tA\tC\t.\tPASS\t.\tGT:{format_key}\t0/1:{sample_value}\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


@pytest.mark.parametrize("chrom", ["chr[1]", "chr,1", "=chr1", "*chr1", 'chr"1'])
def test_vcf43_plus_chrom_must_follow_sam_reference_name_grammar(chrom: str):
    fields = [chrom, "100", ".", "A", "C", ".", "PASS", "."]

    with pytest.raises(StrictVCFValidationError) as exc:
        _validate_record(fields, 1, None, "VCFv4.5")

    assert exc.value.code == "VCF_CHROM_INVALID"


def test_vcf43_plus_external_assembly_contig_is_explicitly_unsupported():
    fields = ["<contigA>", "100", ".", "A", "C", ".", "PASS", "."]

    with pytest.raises(StrictVCFValidationError) as exc:
        _validate_record(fields, 1, None, "VCFv4.5")

    assert exc.value.code == "VCF_EXTERNAL_ASSEMBLY_CONTIG_UNSUPPORTED"


def test_vcf43_plus_contig_header_id_must_follow_sam_reference_name_grammar(tmp_path: Path):
    path = tmp_path / "vcf45-invalid-contig-header.vcf"
    write_vcf_with_metadata(
        path,
        ['##contig=<ID=chr[1],length=100>'],
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_CONTIG_HEADER_INVALID"


def test_vcf43_plus_breakend_mate_contig_must_follow_sam_reference_name_grammar(tmp_path: Path):
    path = tmp_path / "vcf45-invalid-breakend-contig.vcf"
    write_vcf(
        path,
        '1\t100\t.\tA\tA]chr"1:123]\t.\tPASS\tSVTYPE=BND\n',
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_BREAKEND_ALT_INVALID"


def test_vcf45_meta_values_list_is_parsed_without_splitting_inner_commas(tmp_path: Path):
    path = tmp_path / "vcf45-meta-list.vcf"
    write_vcf_with_metadata(
        path,
        ["##META=<ID=Assay,Type=String,Number=.,Values=[WES, WGS]>"],
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(path)
    assert profile["records"] == 1


def test_vcf45_arbitrary_structured_header_requires_unique_id(tmp_path: Path):
    missing_id = tmp_path / "vcf45-structured-header-no-id.vcf"
    write_vcf_with_metadata(
        missing_id,
        ["##CUSTOM=<Name=custom>"],
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        version="VCFv4.5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(missing_id)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"

    duplicate_id = tmp_path / "vcf45-structured-header-duplicate-id.vcf"
    write_vcf_with_metadata(
        duplicate_id,
        ["##CUSTOM=<ID=custom>", "##CUSTOM=<ID=custom>"],
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        version="VCFv4.5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(duplicate_id)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


def test_vcf45_pedigree_structured_header_with_id_is_valid(tmp_path: Path):
    path = tmp_path / "vcf45-pedigree-header.vcf"
    write_vcf_with_metadata(
        path,
        ["##PEDIGREE=<ID=child1,Original=father1>"],
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(path)
    assert profile["records"] == 1


def test_vcf45_structured_header_rejects_attributes_without_values(tmp_path: Path):
    path = tmp_path / "vcf45-malformed-structured-header.vcf"
    write_vcf_with_metadata(
        path,
        ["##contig=<ID=chr1,length>"],
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


def test_vcf_contig_md5_is_verified_against_selected_reference(tmp_path: Path):
    import hashlib

    sequence = "ACGTACGT"
    fasta = tmp_path / "md5-reference.fa"
    fasta.write_text(f">1\n{sequence}\n", encoding="ascii", newline="\n")
    (tmp_path / "md5-reference.fa.fai").write_text(
        "1\t8\t3\t8\t9\n", encoding="ascii"
    )
    digest = hashlib.md5(sequence.encode("ascii"), usedforsecurity=False).hexdigest()
    source = tmp_path / "md5-match.vcf"
    write_vcf_with_metadata(
        source,
        [f"##contig=<ID=1,length=8,md5={digest}>"],
        "1\t1\t.\tA\tC\t.\tPASS\t.\n",
        version="VCFv4.5",
    )

    profile = validate_vcf_strict(source)
    assert profile["declared_contig_md5s"] == {"1": digest}
    assert validate_vcf_reference_alleles(source, fasta)["result"] == "PASS"

    mismatch = tmp_path / "md5-mismatch.vcf"
    write_vcf_with_metadata(
        mismatch,
        ["##contig=<ID=1,length=8,md5=00000000000000000000000000000000>"],
        "1\t1\t.\tA\tC\t.\tPASS\t.\n",
        version="VCFv4.5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_reference_alleles(mismatch, fasta)
    assert exc.value.code == "VCF_CONTIG_MD5_MISMATCH"


def test_vcf_contig_md5_must_be_32_lowercase_hex_characters(tmp_path: Path):
    path = tmp_path / "invalid-contig-md5.vcf"
    write_vcf_with_metadata(
        path,
        ["##contig=<ID=1,length=8,md5=NOT_A_DIGEST>"],
        "1\t1\t.\tA\tC\t.\tPASS\t.\n",
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_CONTIG_MD5_INVALID"


def test_vcf45_standard_and_local_allele_depth_fields_must_project_identically(tmp_path: Path):
    metadata = [
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">',
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allele depths">',
        '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">',
    ]
    valid = tmp_path / "vcf45-ad-lad-match.vcf"
    write_vcf_with_metadata(
        valid,
        metadata,
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:LAA:AD:LAD\t0/2:2:10,5,7:10,7\n",
        sample=True,
        version="VCFv4.5",
    )
    assert validate_vcf_strict(valid)["records"] == 1

    invalid = tmp_path / "vcf45-ad-lad-mismatch.vcf"
    write_vcf_with_metadata(
        invalid,
        metadata,
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:LAA:AD:LAD\t0/2:2:10,5,7:10,5\n",
        sample=True,
        version="VCFv4.5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(invalid)
    assert exc.value.code == "VCF_LOCAL_FIELD_EQUIVALENCE_INVALID"


def test_vcf45_standard_and_local_genotype_likelihoods_use_vcf_genotype_order(tmp_path: Path):
    metadata = [
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">',
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">',
        '##FORMAT=<ID=LPL,Number=LG,Type=Integer,Description="Local genotype likelihoods">',
    ]
    valid = tmp_path / "vcf45-pl-lpl-match.vcf"
    write_vcf_with_metadata(
        valid,
        metadata,
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:LAA:PL:LPL\t0/2:2:0,1,2,3,4,5:0,3,5\n",
        sample=True,
        version="VCFv4.5",
    )
    assert validate_vcf_strict(valid)["records"] == 1

    invalid = tmp_path / "vcf45-pl-lpl-mismatch.vcf"
    write_vcf_with_metadata(
        invalid,
        metadata,
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:LAA:PL:LPL\t0/2:2:0,1,2,3,4,5:0,3,4\n",
        sample=True,
        version="VCFv4.5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(invalid)
    assert exc.value.code == "VCF_LOCAL_FIELD_EQUIVALENCE_INVALID"


def test_vcf45_missing_standard_or_local_equivalent_is_permitted(tmp_path: Path):
    path = tmp_path / "vcf45-missing-local-equivalent.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">',
            '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allele depths">',
            '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">',
        ],
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:LAA:AD:LAD\t0/2:2:10,5,7:.\n",
        sample=True,
        version="VCFv4.5",
    )

    assert validate_vcf_strict(path)["records"] == 1


def test_vcf45_pso_psq_follow_psl_missing_positions(tmp_path: Path):
    path = tmp_path / "vcf45-psl-pso-psq-valid.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">',
            '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">',
            '##FORMAT=<ID=PSQ,Number=P,Type=Integer,Description="Phase set qualities">',
        ],
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:PSL:PSO:PSQ\t|0/1:chr1*2*1,.:3,.:40,.\n",
        sample=True,
        version="VCFv4.5",
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("format_keys", "sample_value"),
    [
        ("GT:PSL:PSQ", "|0/1:phaseA,.:40,5"),
        ("GT:PSL:PSO", "|0/1:phaseA,.:3,4"),
        ("PSQ", "40"),
        ("PSO", "3"),
        ("GT:PSL", ".:phaseA"),
    ],
)
def test_vcf45_phase_set_dependent_fields_reject_inconsistent_context(
    tmp_path: Path, format_keys: str, sample_value: str
):
    path = tmp_path / "vcf45-invalid-phase-set-dependency.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">',
            '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">',
            '##FORMAT=<ID=PSQ,Number=P,Type=Integer,Description="Phase set qualities">',
        ],
        f"1\t2\t.\tA\tC\t.\tPASS\t.\t{format_keys}\t{sample_value}\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_PHASE_SET_INVALID"


def test_vcf45_empty_gt_value_is_not_treated_as_unknown_ploidy(tmp_path: Path):
    path = tmp_path / "vcf45-empty-gt.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">'],
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:PL\t:0,1,2\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_GENOTYPE_INVALID"



def test_vcf_feature_qualification_matrix_is_explicit_and_conservative(tmp_path: Path):
    vcf45 = tmp_path / "vcf45-feature-matrix.vcf"
    write_vcf(vcf45, "1\t2\t.\tA\tC\t.\tPASS\t.\n", version="VCFv4.5")
    profile = validate_vcf_strict(vcf45)
    matrix = {
        item["feature_id"]: item
        for item in profile["format_compatibility"]["feature_matrix"]
    }

    assert matrix["local_allele_encoding"]["status"] == "NATIVE_VALIDATED"
    assert matrix["base_modification_format_fields"]["status"] == "NATIVE_VALIDATED"
    assert matrix["reserved_info_format_definitions"]["status"] == "NATIVE_VALIDATED"
    assert matrix["structured_meta_headers"]["status"] == "NATIVE_VALIDATED"
    assert matrix["unspecified_allele_reference_block_len"]["status"] == "NATIVE_VALIDATED"
    assert matrix["external_assembly_contig_references"]["status"] == "UNSUPPORTED"
    assert matrix["breakend_replacement_and_mate_links"]["status"] == "NATIVE_VALIDATED"
    assert matrix["genotype_ploidy_number_g_cardinality"]["status"] == "NATIVE_VALIDATED"
    assert matrix["symbolic_structural_variant_span"]["status"] == "NATIVE_VALIDATED"
    assert matrix["symbolic_sv_confidence_intervals"]["status"] == "NATIVE_VALIDATED"
    assert "CILEN" in matrix["symbolic_sv_confidence_intervals"]["implementation"]
    # GATK gVCF is a producer dialect, not a normative VCFv4.5 feature.
    # Its interoperability qualification is intentionally limited to the
    # separately fixture-tested VCFv4.3 profile.
    assert matrix["gatk_gvcf_non_ref_end_interoperability"]["status"] == "NOT_QUALIFIED"
    assert matrix["gatk_gvcf_non_ref_end_interoperability"]["specification_scope"].startswith("GATK producer interoperability")

    gatk_profile = {
        item["feature_id"]: item
        for item in feature_compatibility_for_version("VCFv4.3")
    }
    assert gatk_profile["gatk_gvcf_non_ref_end_interoperability"]["status"] == "PRODUCER_INTEROPERABILITY_VALIDATED"

    older = {
        item["feature_id"]: item
        for item in feature_compatibility_for_version("VCFv4.4")
    }
    assert older["local_allele_encoding"]["status"] == "NOT_APPLICABLE_TO_DECLARED_VERSION"
    assert older["symbolic_sv_confidence_intervals"]["status"] == "NOT_APPLICABLE_TO_DECLARED_VERSION"
    assert older["external_assembly_contig_references"]["status"] == "UNSUPPORTED"
    assert older["gatk_gvcf_non_ref_end_interoperability"]["status"] == "NOT_QUALIFIED"

    legacy = {
        item["feature_id"]: item
        for item in feature_compatibility_for_version("VCFv4.0")
    }
    assert legacy["breakend_replacement_and_mate_links"]["status"] == "NOT_APPLICABLE_TO_DECLARED_VERSION"
    assert legacy["genotype_ploidy_number_g_cardinality"]["status"] == "NOT_APPLICABLE_TO_DECLARED_VERSION"


def test_vcf_feature_qualification_rejects_unknown_specification_versions():
    with pytest.raises(ValueError, match="Unsupported VCF specification version"):
        feature_compatibility_for_version("VCFv4.6")

def test_vcf_specification_profiles_use_official_documents_and_label_legacy_scope():
    legacy = get_vcf_specification_profile("VCFv4.0")
    assert legacy.support_status == "PARTIAL_LEGACY_SPECIFICATION_QUALIFICATION"
    assert legacy.validation_mode == "VERSION_AWARE_PARTIAL"
    assert legacy.specification_document == (
        "https://www.internationalgenome.org/wiki/Analysis/vcf4.0/"
    )

    for minor in range(1, 6):
        version = f"VCFv4.{minor}"
        profile = get_vcf_specification_profile(version)
        assert profile.support_status == "PARTIAL_FEATURE_QUALIFICATION"
        assert profile.specification_document == (
            f"https://samtools.github.io/hts-specs/{version}.pdf"
        )
        assert "requirement traceability matrix" in profile.notes


def test_unknown_future_vcf_specification_does_not_get_an_implicit_profile():
    with pytest.raises(ValueError, match="Unsupported VCF specification version"):
        get_vcf_specification_profile("VCFv4.6")




def test_strict_validation_accepts_crlf_line_endings(tmp_path: Path):
    path = tmp_path / "crlf.vcf"
    path.write_bytes(
        b"##fileformat=VCFv4.5\r\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\r\n"
        b"1\t2\t.\tA\tC\t.\tPASS\t.\r\n"
    )
    result = validate_vcf_strict(path)
    assert result["fileformat"] == "VCFv4.5"
    assert result["records"] == 1


def test_strict_validation_rejects_bare_carriage_return_line_endings(tmp_path: Path):
    path = tmp_path / "bare-cr.vcf"
    path.write_bytes(
        b"##fileformat=VCFv4.5\r"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\r"
        b"1\t2\t.\tA\tC\t.\tPASS\t.\r"
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_LINE_ENDING_INVALID"


def test_strict_validation_rejects_embedded_carriage_return(tmp_path: Path):
    path = tmp_path / "embedded-cr.vcf"
    path.write_bytes(
        b"##fileformat=VCFv4.5\n"
        b"##source=producer\rname\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"1\t2\t.\tA\tC\t.\tPASS\t.\n"
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_LINE_ENDING_INVALID"




@pytest.mark.parametrize("version", ["VCFv4.3", "VCFv4.4", "VCFv4.5"])
def test_structured_custom_metadata_requires_an_id_and_accepts_id_only(
    tmp_path: Path, version: str
):
    valid = tmp_path / f"{version}-custom-valid.vcf"
    valid.write_text(
        f'##fileformat={version}\n'
        '##CUSTOM=<ID=ProducerMetadata>\n'
        '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
        '1\t2\t.\tA\tC\t.\tPASS\t.\n',
        encoding="utf-8",
    )
    assert validate_vcf_strict(valid)["records"] == 1

    invalid = tmp_path / f"{version}-custom-no-id.vcf"
    invalid.write_text(
        f'##fileformat={version}\n'
        '##CUSTOM=<Description="missing identifier">\n'
        '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
        '1\t2\t.\tA\tC\t.\tPASS\t.\n',
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(invalid)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


@pytest.mark.parametrize("version", ["VCFv4.1", "VCFv4.2"])
def test_legacy_custom_structured_metadata_is_not_upgraded_to_v43_id_rule(
    tmp_path: Path, version: str
):
    path = tmp_path / f"{version}-custom-legacy.vcf"
    path.write_text(
        f'##fileformat={version}\n'
        '##CUSTOM=<Description="legacy custom value">\n'
        '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
        '1\t2\t.\tA\tC\t.\tPASS\t.\n',
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("kind", ["FILTER", "ALT"])
def test_filter_and_alt_structured_headers_require_quoted_description(
    tmp_path: Path, kind: str
):
    path = tmp_path / f"missing-{kind.lower()}-description.vcf"
    path.write_text(
        '##fileformat=VCFv4.5\n'
        f'##{kind}=<ID=custom>\n'
        '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
        '1\t2\t.\tA\tC\t.\tPASS\t.\n',
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


@pytest.mark.parametrize("metadata", ["##source", "##source=", "##=producer"])
def test_unstructured_meta_information_must_have_nonempty_key_and_value(
    tmp_path: Path, metadata: str
):
    path = tmp_path / "malformed-meta.vcf"
    path.write_text(
        '##fileformat=VCFv4.5\n'
        f'{metadata}\n'
        '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
        '1\t2\t.\tA\tC\t.\tPASS\t.\n',
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


@pytest.mark.parametrize("attribute", ["Source=ClinVar", "Version=20260101"])
def test_info_optional_source_and_version_attributes_must_be_quoted(
    tmp_path: Path, attribute: str
):
    path = tmp_path / "unquoted-info-optional-attribute.vcf"
    path.write_text(
        '##fileformat=VCFv4.5\n'
        f'##INFO=<ID=AF,Number=A,Type=Float,Description="Allele frequency",{attribute}>\n'
        '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
        '1\t2\t.\tA\tC\t.\tPASS\tAF=0.5\n',
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"





def test_info_description_accepts_escaped_quote_and_backslash(tmp_path: Path):
    path = tmp_path / "escaped-description.vcf"
    header = (
        r'##INFO=<ID=DP,Number=1,Type=Integer,Description="depth with \"quoted\" text and \\ path">'
        + "\n"
    )
    path.write_text(
        "##fileformat=VCFv4.5\n"
        + header
        + "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "1\t2\t.\tA\tC\t.\tPASS\tDP=10\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_custom_structured_header_accepts_escaped_quote_and_backslash(tmp_path: Path):
    path = tmp_path / "escaped-custom-header.vcf"
    header = (
        r'##CUSTOM=<ID=Producer,Description="producer said \"valid\" and path \\data">'
        + "\n"
    )
    path.write_text(
        "##fileformat=VCFv4.5\n"
        + header
        + "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    "header",
    [
        r'##INFO=<ID=DP,Number=1,Type=Integer,Description="bad \q escape">',
        r'##CUSTOM=<ID=Producer,Description="bad \q escape">',
    ],
)
def test_structured_header_rejects_unsupported_escape_sequences(
    tmp_path: Path, header: str
):
    path = tmp_path / "unsupported-escape.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        + header
        + "\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"



@pytest.mark.parametrize(
    "header, expected_code",
    [
        ('##FILTER=<ID=bad id,Description="bad filter">', "VCF_HEADER_DEFINITION_INVALID"),
        ('##FILTER=<ID=0,Description="reserved filter">', "VCF_HEADER_DEFINITION_INVALID"),
        ('##ALT=<ID=bad id,Description="bad symbolic allele">', "VCF_HEADER_DEFINITION_INVALID"),
        ('##ALT=<ID=bad<type>,Description="bad symbolic allele">', "VCF_HEADER_DEFINITION_INVALID"),
    ],
)
def test_filter_and_alt_header_ids_obey_version_specific_grammar(
    tmp_path: Path, header: str, expected_code: str
):
    path = tmp_path / "invalid-header-id.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        + header
        + "\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == expected_code




def test_vcf41_vcf42_preserve_legacy_info_and_format_identifier_grammar(tmp_path: Path):
    path = tmp_path / "legacy-field-identifiers.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=DP-raw,Number=1,Type=Integer,Description="Raw depth">\n'
        '##FORMAT=<ID=F-tag,Number=1,Type=Integer,Description="Custom field">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\tDP-raw=10\tGT:F-tag\t0/1:5\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("version", ["VCFv4.3", "VCFv4.4", "VCFv4.5"])
def test_vcf43_plus_enforces_info_and_format_tag_name_regex(
    tmp_path: Path, version: str
):
    path = tmp_path / f"invalid-tag-name-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        '##INFO=<ID=DP-raw,Number=1,Type=Integer,Description="Raw depth">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC\t.\tPASS\tDP-raw=10\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"



@pytest.mark.parametrize("version", ["VCFv4.3", "VCFv4.4", "VCFv4.5"])
def test_vcf43_plus_rejects_nonconforming_format_tag_name(
    tmp_path: Path, version: str
):
    path = tmp_path / f"invalid-format-tag-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        '##FORMAT=<ID=F-tag,Number=1,Type=Integer,Description="Custom field">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:F-tag\t0/1:5\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"



@pytest.mark.parametrize(
    "kind, identifier",
    [
        ("CUSTOM", "bad id"),
        ("SAMPLE", "bad id"),
        ("PEDIGREE", "bad id"),
        ("META", "bad id"),
    ],
)
def test_vcf43_plus_all_structured_ids_reject_whitespace(
    tmp_path: Path, kind: str, identifier: str
):
    path = tmp_path / f"invalid-{kind.lower()}-id.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        f'##{kind}=<ID={identifier}>\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"



@pytest.mark.parametrize("integer_value", ["-2147483640", "2147483647"])
def test_vcf_integer_accepts_specified_lower_and_upper_boundaries(
    tmp_path: Path, integer_value: str
):
    path = tmp_path / "int32-boundary.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##INFO=<ID=X,Number=1,Type=Integer,Description="Signed integer">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t2\t.\tA\tC\t.\tPASS\tX={integer_value}\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("integer_value", ["-2147483641", "2147483648"])
def test_vcf_integer_rejects_values_outside_specified_range(
    tmp_path: Path, integer_value: str
):
    path = tmp_path / "int32-out-of-range.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##INFO=<ID=X,Number=1,Type=Integer,Description="Signed integer">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t2\t.\tA\tC\t.\tPASS\tX={integer_value}\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"



@pytest.mark.parametrize(
    "pos,ref,alt",
    [
        (2, "A", "AT"),
        (2, "AT", "A"),
        (1, "AT", "T"),
        (1, "T", "AT"),
        (1, "A", "AT"),
        (1, "AT", "A"),
        (0, "A", "TA"),
        (2, "ATC", "AC"),
    ],
)
def test_simple_indels_obey_vcf_padding_rules(
    tmp_path: Path, pos: int, ref: str, alt: str
):
    path = tmp_path / "valid-indel-padding.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t{pos}\t.\t{ref}\t{alt}\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    "pos,ref,alt",
    [
        (2, "AT", "T"),
        (0, "AT", "A"),
    ],
)
def test_simple_indels_reject_wrong_padding_side(
    tmp_path: Path, pos: int, ref: str, alt: str
):
    path = tmp_path / "invalid-indel-padding.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t{pos}\t.\t{ref}\t{alt}\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_INDEL_PADDING_INVALID"



@pytest.mark.parametrize("qual", [".5", "1e3", "+INF", "NAN"])
def test_vcf43_plus_qual_accepts_specified_float_tokens(tmp_path: Path, qual: str):
    path = tmp_path / "valid-qual.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t2\t.\tA\tC\t{qual}\tPASS\t.\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("qual", ["1.", "1_0", "InfinityX", " 1.0"])
def test_vcf43_plus_qual_rejects_nonconforming_float_tokens(tmp_path: Path, qual: str):
    path = tmp_path / "invalid-qual.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t2\t.\tA\tC\t{qual}\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_QUAL_INVALID"


@pytest.mark.parametrize("pos", ["+2", "02x", "-1", "1.0"])
def test_vcf_position_requires_unsigned_decimal_token(tmp_path: Path, pos: str):
    path = tmp_path / "invalid-pos-token.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t{pos}\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_POS_INVALID"



@pytest.mark.parametrize("identifier", ["id,comma", "id<angle", "id>angle"])
def test_vcf43_plus_record_ids_reject_forbidden_characters(
    tmp_path: Path, identifier: str
):
    path = tmp_path / "invalid-record-id.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        f"1\t2\t{identifier}\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_ID_INVALID"


def test_vcf42_record_id_preserves_legacy_comma_behavior(tmp_path: Path):
    path = tmp_path / "legacy-comma-id.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\tlegacy,id\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1



def test_vcf42_sample_metadata_preserves_unquoted_description_list(tmp_path: Path):
    path = tmp_path / "sample-description-list.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "##SAMPLE=<ID=Blood,Genomes=Germline;Tumor,Mixture=.3;.7,Description=Germline;Tumor>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tBlood\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_vcf43_custom_structured_metadata_does_not_assume_description_schema(
    tmp_path: Path,
):
    path = tmp_path / "custom-unquoted-description.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##CUSTOM=<ID=Producer,Description=UnquotedExtensionValue>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1



@pytest.mark.parametrize("version", ["VCFv4.2", "VCFv4.3", "VCFv4.5"])
def test_sample_metadata_ids_must_match_sample_columns(tmp_path: Path, version: str):
    valid = tmp_path / f"sample-metadata-valid-{version}.vcf"
    valid.write_text(
        f"##fileformat={version}\n"
        '##SAMPLE=<ID=Blood,Description="Blood sample">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tBlood\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(valid)["records"] == 1

    invalid = tmp_path / f"sample-metadata-mismatch-{version}.vcf"
    invalid.write_text(
        f"##fileformat={version}\n"
        '##SAMPLE=<ID=OtherSample,Description="Different sample">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tBlood\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(invalid)
    assert exc.value.code == "VCF_SAMPLE_METADATA_MISMATCH"


def test_sample_metadata_is_invalid_for_sites_only_vcf(tmp_path: Path):
    path = tmp_path / "sites-only-with-sample-metadata.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##SAMPLE=<ID=Blood,Description="Blood sample">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_SAMPLE_METADATA_MISMATCH"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("CN", "2.0"),
        ("CICN", "1.5,2.5"),
        ("CNQ", "30.0"),
        ("CNL", "-1.0,-2.0,-3.0"),
        ("CNP", "0.2,0.3,0.5"),
        ("NQ", "30"),
        ("HAP", "1"),
        ("AHAP", "1"),
    ],
)
def test_vcf45_implicit_reserved_copy_number_and_haplotype_format_fields(
    tmp_path: Path, field: str, value: str
):
    path = tmp_path / f"vcf45-implicit-{field.lower()}.vcf"
    write_vcf_with_metadata(
        path,
        [],
        f"1\t2\t.\tA\t<CNV>\t.\tPASS\tEND=10\tGT:{field}\t0/1:{value}\n",
        sample=True,
        version="VCFv4.5",
    )
    profile = validate_vcf_strict(path)
    assert profile["records"] == 1


def test_vcf45_implicit_reserved_cnp_values_must_be_probabilities(tmp_path: Path):
    path = tmp_path / "vcf45-implicit-cnp-out-of-range.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\t2\t.\tA\t<CNV>\t.\tPASS\tEND=10\tGT:CNP\t0/1:0.2,0.3,1.2\n",
        sample=True,
        version="VCFv4.5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


def test_vcf45_reserved_cnp_header_cannot_override_builtin_definition(tmp_path: Path):
    path = tmp_path / "vcf45-cnp-header-override.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=CNP,Number=1,Type=Float,Description="Incorrect CNP definition">'],
        "1\t2\t.\tA\t<CNV>\t.\tPASS\tEND=10\tGT:CNP\t0/1:0.2,0.3,0.5\n",
        sample=True,
        version="VCFv4.5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


def _write_vcf_with_sample_and_pedigree_metadata(
    path: Path,
    metadata: list[str],
    sample_columns: list[str],
    *,
    version: str = "VCFv4.5",
) -> None:
    header = (
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t"
        + "\t".join(sample_columns)
    )
    record = (
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT\t"
        + "\t".join("0/1" for _ in sample_columns)
    )
    path.write_text(
        "\n".join([f"##fileformat={version}", *metadata, header, record, ""]),
        encoding="utf-8",
    )


def test_sample_mixture_metadata_accepts_parallel_genome_and_fraction_lists(tmp_path: Path):
    path = tmp_path / "sample-mixture-valid.vcf"
    _write_vcf_with_sample_and_pedigree_metadata(
        path,
        [
            '##SAMPLE=<ID=TissueSample,Genomes=Germline;Tumor,Mixture=.3;.7,Description="Germline;Tumor">',
        ],
        ["TissueSample"],
    )

    profile = validate_vcf_strict(path)

    assert profile["sample_genome_count"] == 2
    assert profile["sample_mixture_count"] == 1
    assert profile["sample_genome_mapping_complete"] is True


@pytest.mark.parametrize(
    "sample_definition",
    [
        '##SAMPLE=<ID=Sample1,Genomes=Germline;Tumor,Mixture=.3>',
        '##SAMPLE=<ID=Sample1,Genomes=Germline;Tumor,Mixture=.3;1.2>',
        '##SAMPLE=<ID=Sample1,Genomes=Germline;Tumor,Mixture=.3;-.1>',
        '##SAMPLE=<ID=Sample1,Genomes=Germline;Tumor,Mixture=.3;.6>',
        '##SAMPLE=<ID=Sample1,Genomes=Germline;Tumor,Mixture=.3;NAN>',
        '##SAMPLE=<ID=Sample1,Genomes=Germline;Tumor,Mixture=.3; .7>',
    ],
)
def test_sample_mixture_metadata_rejects_invalid_cardinality_or_proportions(
    tmp_path: Path, sample_definition: str
):
    path = tmp_path / "sample-mixture-invalid.vcf"
    _write_vcf_with_sample_and_pedigree_metadata(
        path, [sample_definition], ["Sample1"]
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_SAMPLE_MIXTURE_INVALID"


def test_sample_mixture_metadata_preserves_unknown_proportions(tmp_path: Path):
    path = tmp_path / "sample-mixture-missing.vcf"
    _write_vcf_with_sample_and_pedigree_metadata(
        path,
        ['##SAMPLE=<ID=Sample1,Genomes=Germline;Tumor,Mixture=.;.>'],
        ["Sample1"],
    )

    profile = validate_vcf_strict(path)

    assert profile["sample_mixture_count"] == 1


def test_pedigree_relationships_accept_family_trio_and_validate_genome_references(
    tmp_path: Path,
):
    path = tmp_path / "pedigree-trio-valid.vcf"
    _write_vcf_with_sample_and_pedigree_metadata(
        path,
        [
            '##SAMPLE=<ID=FatherSample,Genomes=Father>',
            '##SAMPLE=<ID=MotherSample,Genomes=Mother>',
            '##SAMPLE=<ID=ChildSample,Genomes=Child>',
            '##PEDIGREE=<ID=Child,Mother=Mother,Father=Father>',
        ],
        ["FatherSample", "MotherSample", "ChildSample"],
    )

    profile = validate_vcf_strict(path)

    assert profile["pedigree_relationship_count"] == 2
    assert profile["pedigree_node_count"] == 3
    assert profile["pedigree_validation_status"] == "VALIDATED"


def test_pedigree_relationships_reject_directed_ancestry_cycles(tmp_path: Path):
    path = tmp_path / "pedigree-cycle.vcf"
    _write_vcf_with_sample_and_pedigree_metadata(
        path,
        [
            '##PEDIGREE=<ID=GenomeA,Original=GenomeB>',
            '##PEDIGREE=<ID=GenomeB,Original=GenomeA>',
        ],
        ["Sample1"],
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_PEDIGREE_CYCLE"


def test_pedigree_relationships_reject_self_ancestry(tmp_path: Path):
    path = tmp_path / "pedigree-self-reference.vcf"
    _write_vcf_with_sample_and_pedigree_metadata(
        path,
        ['##PEDIGREE=<ID=GenomeA,Original=GenomeA>'],
        ["Sample1"],
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_PEDIGREE_INVALID"


def test_pedigree_relationships_route_external_genome_references_for_review(
    tmp_path: Path,
):
    path = tmp_path / "pedigree-external-genome.vcf"
    _write_vcf_with_sample_and_pedigree_metadata(
        path,
        [
            '##SAMPLE=<ID=ChildSample,Genomes=Child>',
            '##SAMPLE=<ID=MotherSample,Genomes=Mother>',
            '##PEDIGREE=<ID=Child,Mother=MissingGenome>',
        ],
        ["ChildSample", "MotherSample"],
    )

    profile = validate_vcf_strict(path)

    assert profile["pedigree_validation_status"] == "REVIEW_REQUIRED"
    assert "VCF_PEDIGREE_REFERENCE_UNRESOLVED" in profile["warning_codes"]


def test_legacy_vcf42_pedigree_without_id_remains_compatible(tmp_path: Path):
    path = tmp_path / "pedigree-v42-legacy.vcf"
    _write_vcf_with_sample_and_pedigree_metadata(
        path,
        ["##PEDIGREE=<Name_0=Child,Name_1=Parent>"],
        ["Sample1"],
        version="VCFv4.2",
    )

    profile = validate_vcf_strict(path)

    assert profile["pedigree_validation_status"] == "PARTIAL_LEGACY"


def test_pedigree_relationships_accept_consanguineous_ancestry_dag(tmp_path: Path):
    path = tmp_path / "pedigree-consanguineous-dag.vcf"
    _write_vcf_with_sample_and_pedigree_metadata(
        path,
        [
            '##PEDIGREE=<ID=ParentA,Original=SharedAncestor>',
            '##PEDIGREE=<ID=ParentB,Original=SharedAncestor>',
            '##PEDIGREE=<ID=Child,Mother=ParentA,Father=ParentB>',
        ],
        ["Sample1"],
    )

    profile = validate_vcf_strict(path)

    assert profile["pedigree_relationship_count"] == 4
    assert profile["pedigree_node_count"] == 4
    assert profile["pedigree_validation_status"] == "VALIDATED"


@pytest.mark.parametrize(
    "version",
    ["VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"],
)
def test_strict_validation_accepts_breakend_mates_without_optional_svtype(tmp_path, version):
    mate_number = "A" if version in {"VCFv4.4", "VCFv4.5"} else "."
    path = tmp_path / f"breakend-no-svtype-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        f'##INFO=<ID=MATEID,Number={mate_number},Type=String,Description="Breakend mate ID">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tMATEID=bnd2\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tMATEID=bnd1\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(path)

    assert profile["records"] == 2


def test_vcf45_reserved_lec_requires_laa_even_without_header_definition(tmp_path: Path):
    path = tmp_path / "vcf45-lec-without-laa.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\\t2\\t.\\tA\\tC,G\\t.\\tPASS\\t.\\tGT:LEC\\t0/1:5,6\\n",
        sample=True,
        version="VCFv4.5",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_LOCAL_ALLELE_HEADER_INVALID"


def test_vcf45_reserved_lec_accepts_laa_scoped_cardinality(tmp_path: Path):
    path = tmp_path / "vcf45-lec-with-laa.vcf"
    write_vcf_with_metadata(
        path,
        [],
        "1\\t2\\t.\\tA\\tC,G\\t.\\tPASS\\t.\\tGT:LAA:LEC\\t0/1:2:5\\n",
        sample=True,
        version="VCFv4.5",
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("gt", "value", "valid"),
    [
        ("0|1/0", "0.2,0.3", True),
        ("0|1/0", "0.2,0.3,0.4", False),
        ("0/1|0", "0.2,0.3,0.4", True),
        ("0/1|0", "0.2,0.3", False),
        ("/0/1", "0.2,0.3", True),
    ],
)
def test_vcf45_number_m_uses_implicit_first_phase_indicator(
    tmp_path: Path, gt: str, value: str, valid: bool
):
    path = tmp_path / "vcf45-number-m-prefix-phasing.vcf"
    write_vcf_with_metadata(
        path,
        [
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
            '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5-methylcytosine fraction">',
        ],
        f"1\\t2\\t.\\tC\\tG\\t.\\tPASS\\t.\\tGT:M5mC\\t{gt}:{value}\\n",
        sample=True,
        version="VCFv4.5",
    )

    if valid:
        assert validate_vcf_strict(path)["records"] == 1
    else:
        with pytest.raises(StrictVCFValidationError) as exc:
            validate_vcf_strict(path)
        assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


@pytest.mark.parametrize(
    ("gt", "values", "valid"),
    [
        ("0", "10", True),
        ("0/1", "10,20", True),
        ("0/1/1", "10,20,30", True),
        (".", "10", True),
        ("./.", "10,20", True),
        ("0/1/1", "10,20", False),
    ],
)
def test_vcf45_number_p_cardinality_tracks_sample_ploidy(
    tmp_path: Path, gt: str, values: str, valid: bool
):
    path = tmp_path / "vcf45-number-p-ploidy.vcf"
    write_vcf_with_metadata(
        path,
        ['##FORMAT=<ID=CUSTOM_P,Number=P,Type=Integer,Description="Per-allele values">'],
        f"1\\t2\\t.\\tA\\tC\\t.\\tPASS\\t.\\tGT:CUSTOM_P\\t{gt}:{values}\\n",
        sample=True,
        version="VCFv4.5",
    )

    if valid:
        assert validate_vcf_strict(path)["records"] == 1
    else:
        with pytest.raises(StrictVCFValidationError) as exc:
            validate_vcf_strict(path)
        assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"
