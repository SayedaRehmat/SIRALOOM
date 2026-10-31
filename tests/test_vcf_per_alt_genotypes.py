from pathlib import Path

from backend.app.domain.vcf import parse_vcf


def _write_multiallelic_vcf(path: Path) -> None:
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PS,Number=1,Type=Integer,Description="Phase set">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE_A\tSAMPLE_B\n"
        "1\t100\trsMulti\tA\tC,G\t.\tPASS\t.\tGT:PS\t1/2:10\t2|2:20\n",
        encoding="utf-8",
    )


def test_multiallelic_projection_never_converts_other_alt_to_reference(tmp_path: Path):
    path = tmp_path / "multiallelic.vcf"
    _write_multiallelic_vcf(path)
    first, second = list(parse_vcf(str(path), allow_unselected_multisample=True))

    first_a = first.sample_calls["SAMPLE_A"]
    assert first_a["genotype"] == first_a["source_genotype"] == "1/2"
    assert first_a["source_alt_index"] == 1
    assert first_a["source_alt_count"] == 2
    assert first_a["projected_genotype"] is None
    assert first_a["projection_status"] == "CONTAINS_OTHER_ALT"
    assert first_a["projected_allele_states"] == ["SELECTED_ALT", "OTHER_ALT"]
    assert first_a["selected_alt_dosage"] == 1
    assert first_a["other_alt_dosage"] == 1
    assert first_a["reference_allele_dosage"] == 0

    first_b = first.sample_calls["SAMPLE_B"]
    assert first_b["genotype"] == "2|2"
    assert first_b["projected_genotype"] is None
    assert first_b["projection_status"] == "CONTAINS_OTHER_ALT"
    assert first_b["projected_allele_states"] == ["OTHER_ALT", "OTHER_ALT"]
    assert first_b["selected_alt_dosage"] == 0
    assert first_b["other_alt_dosage"] == 2
    assert first_b["reference_allele_dosage"] == 0

    second_a = second.sample_calls["SAMPLE_A"]
    assert second_a["genotype"] == "1/2"
    assert second_a["projected_genotype"] is None
    assert second_a["projection_status"] == "CONTAINS_OTHER_ALT"
    assert second_a["projected_allele_states"] == ["OTHER_ALT", "SELECTED_ALT"]

    second_b = second.sample_calls["SAMPLE_B"]
    assert second_b["genotype"] == "2|2"
    assert second_b["projected_genotype"] == "1|1"
    assert second_b["projected_zygosity"] == "HOMOZYGOUS_ALTERNATE"
    assert second_b["projection_status"] == "AVAILABLE"
    assert second_b["selected_alt_dosage"] == 2
    assert second_b["other_alt_dosage"] == 0


def test_biallelic_projection_preserves_ref_selected_alt_and_phase(tmp_path: Path):
    path = tmp_path / "biallelic.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "1\t101\trsBiallelic\tA\tC,G\t.\tPASS\t.\tGT\t0|2\n",
        encoding="utf-8",
    )
    first, second = list(parse_vcf(str(path)))
    assert first.sample_calls["SAMPLE"]["projected_genotype"] is None
    assert first.sample_calls["SAMPLE"]["projection_status"] == "CONTAINS_OTHER_ALT"
    assert second.sample_calls["SAMPLE"]["projected_genotype"] == "0|1"
    assert second.sample_calls["SAMPLE"]["projected_phase"] == "PHASED"


def test_partial_and_missing_calls_remain_explicit(tmp_path: Path):
    path = tmp_path / "multiallelic-missing.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPARTIAL\tMISSING\n"
        "1\t102\trsMissing\tA\tC,G\t.\tPASS\t.\tGT\t1/.\t./.\n",
        encoding="utf-8",
    )
    records = list(parse_vcf(str(path), allow_unselected_multisample=True))
    assert records[0].sample_calls["PARTIAL"]["projected_genotype"] == "1/."
    assert records[0].sample_calls["PARTIAL"]["projection_status"] == "PARTIAL_CALL"
    assert records[1].sample_calls["PARTIAL"]["projected_genotype"] is None
    assert records[1].sample_calls["PARTIAL"]["projection_status"] == "CONTAINS_OTHER_ALT_AND_MISSING"
    assert records[0].sample_calls["MISSING"]["projected_genotype"] == "./."
    assert records[0].sample_calls["MISSING"]["projection_status"] == "NO_CALL"
    assert records[1].sample_calls["MISSING"]["projected_genotype"] == "./."
    assert records[1].sample_calls["MISSING"]["projection_status"] == "NO_CALL"


def test_normalized_split_records_recover_source_gt_and_per_alt_dosage(tmp_path: Path):
    import base64
    import json

    source_payload = {
        "schema_version": "1",
        "source_record_index": 7,
        "source_record_sha256": "a" * 64,
        "source_alt_count": 4,
        "normalized_alt_source_indexes": [2, 4],
    }
    encoded_source_payload = base64.urlsafe_b64encode(
        json.dumps(source_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    source_info = f"SIRALOOM_SOURCE={encoded_source_payload}"
    path = tmp_path / "normalized-multiallelic.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##INFO=<ID=SIRALOOM_SOURCE,Number=1,Type=String,Description="Source routing provenance">\n'
        '##INFO=<ID=SIRALOOM_ORIG,Number=.,Type=String,Description="Original source record">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=SIRALOOM_SOURCE_GT,Number=1,Type=String,Description="Original source genotype">\n'
        '##FORMAT=<ID=SIRALOOM_SOURCE_ALT_COUNT,Number=1,Type=Integer,Description="Original ALT count">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        f"1\t100\t.\tA\tC\t.\tPASS\t{source_info};SIRALOOM_ORIG=1|100|A|C,G|1\t"
        "GT:SIRALOOM_SOURCE_GT:SIRALOOM_SOURCE_ALT_COUNT\t1/.:1/2:2\n"
        f"1\t100\t.\tA\tG\t.\tPASS\t{source_info};SIRALOOM_ORIG=1|100|A|C,G|2\t"
        "GT:SIRALOOM_SOURCE_GT:SIRALOOM_SOURCE_ALT_COUNT\t./1:1/2:2\n",
        encoding="utf-8",
    )

    first, second = list(parse_vcf(str(path), sample_name="SAMPLE"))

    for record, expected_index in ((first, 1), (second, 2)):
        call = record.sample_calls["SAMPLE"]
        assert call["genotype"] == call["source_genotype"] == "1/2"
        assert call["normalized_genotype"] == ("1/." if expected_index == 1 else "./1")
        assert call["source_alt_index"] == expected_index
        assert call["source_alt_count"] == 2
        assert call["original_source_alt_index"] == expected_index * 2
        assert call["original_source_alt_count"] == 4
        assert call["source_record_index"] == 7
        assert call["source_record_sha256"] == "a" * 64
        assert call["source_genotype_stage"] == "ROUTED_SEQUENCE_INPUT_PRE_SPLIT"
        assert call["selected_alt_dosage"] == 1
        assert call["other_alt_dosage"] == 1
        assert call["reference_allele_dosage"] == 0
        assert call["projection_status"] == "CONTAINS_OTHER_ALT"
        assert call["projected_genotype"] is None

    from backend.app.domain.normalization import iter_normalized_vcf

    variants = list(iter_normalized_vcf(path, "GRCh38", sample_name="SAMPLE"))
    assert [variant.original_alt_index for variant in variants] == [2, 4]


def test_vcf44_leading_phase_indicator_is_not_a_missing_allele(tmp_path: Path):
    path = tmp_path / "vcf44-leading-phase.vcf"
    path.write_text(
        "##fileformat=VCFv4.4\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "1\t103\trsLeadingPhase\tA\tC,G\t.\tPASS\t.\tGT\t|0/1/2\n",
        encoding="utf-8",
    )

    first, second = list(parse_vcf(str(path), sample_name="SAMPLE"))

    for record, expected_index in ((first, 1), (second, 2)):
        call = record.sample_calls["SAMPLE"]
        assert call["source_genotype"] == "|0/1/2"
        assert call["source_alt_index"] == expected_index
        assert call["source_alt_count"] == 2
        assert call["reference_allele_dosage"] == 1
        assert call["selected_alt_dosage"] == 1
        assert call["other_alt_dosage"] == 1
        assert call["missing_allele_count"] == 0
        assert call["projection_status"] == "CONTAINS_OTHER_ALT"
        assert call["phase"] == "PARTIALLY_PHASED"


def test_source_and_normalized_gt_ploidy_mismatch_is_not_projected(tmp_path: Path):
    path = tmp_path / "ploidy-mismatch.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##INFO=<ID=SIRALOOM_ORIG,Number=.,Type=String,Description="Original source record">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=SIRALOOM_SOURCE_GT,Number=1,Type=String,Description="Original source genotype">\n'
        '##FORMAT=<ID=SIRALOOM_SOURCE_ALT_COUNT,Number=1,Type=Integer,Description="Original ALT count">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "1\t104\t.\tA\tC\t.\tPASS\tSIRALOOM_ORIG=1|104|A|C,G|1\t"
        "GT:SIRALOOM_SOURCE_GT:SIRALOOM_SOURCE_ALT_COUNT\t1:1/2:2\n",
        encoding="utf-8",
    )

    record = next(parse_vcf(str(path), sample_name="SAMPLE"))
    call = record.sample_calls["SAMPLE"]
    assert call["genotype"] == "1/2"
    assert call["normalized_genotype"] == "1"
    assert call["projection_status"] == "SOURCE_NORMALIZED_PLOIDY_MISMATCH"
    assert call["selected_alt_dosage"] == 0
    assert call["other_alt_dosage"] == 0
