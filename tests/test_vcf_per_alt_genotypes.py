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


def test_multiallelic_genotypes_are_projected_per_alternate_and_source_is_retained(tmp_path: Path):
    path = tmp_path / "multiallelic.vcf"
    _write_multiallelic_vcf(path)

    records = list(parse_vcf(str(path)))

    assert [record.alt for record in records] == ["C", "G"]
    first, second = records

    assert first.sample_calls["SAMPLE_A"]["source_genotype"] == "1/2"
    assert first.sample_calls["SAMPLE_A"]["source_alt_index"] == 1
    assert first.sample_calls["SAMPLE_A"]["source_alt_count"] == 2
    assert first.sample_calls["SAMPLE_A"]["genotype"] == "1/0"
    assert first.sample_calls["SAMPLE_A"]["zygosity"] == "HETEROZYGOUS"
    assert first.sample_calls["SAMPLE_B"]["genotype"] == "0|0"
    assert first.sample_calls["SAMPLE_B"]["zygosity"] == "HOMOZYGOUS_REFERENCE"

    assert second.sample_calls["SAMPLE_A"]["source_genotype"] == "1/2"
    assert second.sample_calls["SAMPLE_A"]["source_alt_index"] == 2
    assert second.sample_calls["SAMPLE_A"]["genotype"] == "0/1"
    assert second.sample_calls["SAMPLE_A"]["zygosity"] == "HETEROZYGOUS"
    assert second.sample_calls["SAMPLE_B"]["genotype"] == "1|1"
    assert second.sample_calls["SAMPLE_B"]["zygosity"] == "HOMOZYGOUS_ALTERNATE"


def test_multiallelic_partial_and_missing_calls_remain_missing_after_projection(tmp_path: Path):
    path = tmp_path / "multiallelic-missing.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPARTIAL\tMISSING\n"
        "1\t101\trsMissing\tA\tC,G\t.\tPASS\t.\tGT\t1/.\t./.\n",
        encoding="utf-8",
    )

    records = list(parse_vcf(str(path)))

    assert records[0].sample_calls["PARTIAL"]["genotype"] == "1/."
    assert records[1].sample_calls["PARTIAL"]["genotype"] == "0/."
    assert records[0].sample_calls["PARTIAL"]["zygosity"] == "PARTIAL_CALL"
    assert records[1].sample_calls["PARTIAL"]["zygosity"] == "PARTIAL_CALL"
    assert records[0].sample_calls["MISSING"]["genotype"] == "./."
    assert records[1].sample_calls["MISSING"]["genotype"] == "./."
    assert records[0].sample_calls["MISSING"]["zygosity"] == "NO_CALL"
    assert records[1].sample_calls["MISSING"]["zygosity"] == "NO_CALL"
