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


def test_strict_validation_rejects_duplicate_info_keys(tmp_path: Path):
    path = tmp_path / "duplicate-info-key.vcf"
    write_vcf(path, "1\t2\t.\tA\tG\t.\tPASS\tDP=10;DP=11\n")

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_INFO_INVALID"


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
