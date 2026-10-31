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
    assert records[1].sample_calls["PARTIAL"]["projection_status"] == "CONTAINS_OTHER_ALT"
    assert records[0].sample_calls["MISSING"]["projected_genotype"] == "./."
    assert records[0].sample_calls["MISSING"]["projection_status"] == "NO_CALL"
    assert records[1].sample_calls["MISSING"]["projected_genotype"] == "./."
    assert records[1].sample_calls["MISSING"]["projection_status"] == "NO_CALL"


def test_normalized_split_records_recover_source_gt_and_per_alt_dosage(tmp_path: Path):
    path = tmp_path / "normalized-multiallelic.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##INFO=<ID=SIRALOOM_ORIG,Number=.,Type=String,Description="Original source record">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=SIRALOOM_SOURCE_GT,Number=1,Type=String,Description="Original source genotype">\n'
        '##FORMAT=<ID=SIRALOOM_SOURCE_ALT_COUNT,Number=1,Type=Integer,Description="Original ALT count">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "1\t100\t.\tA\tC\t.\tPASS\tSIRALOOM_ORIG=1|100|A|C,G|1\t"
        "GT:SIRALOOM_SOURCE_GT:SIRALOOM_SOURCE_ALT_COUNT\t1/.:1/2:2\n"
        "1\t100\t.\tA\tG\t.\tPASS\tSIRALOOM_ORIG=1|100|A|C,G|2\t"
        "GT:SIRALOOM_SOURCE_GT:SIRALOOM_SOURCE_ALT_COUNT\t./1:1/2:2\n",
        encoding="utf-8",
    )

    first, second = list(parse_vcf(str(path), sample_name="SAMPLE"))

    for record, expected_index in ((first, 1), (second, 2)):
        call = record.sample_calls["SAMPLE"]
        assert call["source_genotype"] == "1/2"
        assert call["source_alt_index"] == expected_index
        assert call["source_alt_count"] == 2
        assert call["selected_alt_dosage"] == 1
        assert call["other_alt_dosage"] == 1
        assert call["reference_allele_dosage"] == 0
        assert call["projection_status"] == "CONTAINS_OTHER_ALT"
        assert call["projected_genotype"] is None
