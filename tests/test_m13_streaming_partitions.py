from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.domain.normalization import iter_normalized_vcf, normalize_vcf_file
from backend.app.domain.reference import FastaReference
from backend.app.domain.vcf import parse_vcf
from backend.app.workflows.variant import _iter_variant_batches, _normalized_partition_metadata


def make_reference(tmp_path: Path):
    fasta = tmp_path / "ref.fa"
    seq = "C" + "A" * 1999
    # FAI offsets are byte offsets; avoid Windows text-mode newline translation.
    fasta.write_bytes((">1\n" + seq + "\n").encode("ascii"))
    fai = tmp_path / "ref.fa.fai"
    fai.write_text(f"1\t{len(seq)}\t3\t{len(seq)}\t{len(seq)+1}\n", encoding="utf-8")
    return fasta, fai


def make_vcf(tmp_path: Path, n: int = 1200):
    path = tmp_path / "input.vcf"
    with path.open("w", encoding="utf-8") as fh:
        fh.write("##fileformat=VCFv4.3\n")
        fh.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        for pos in range(1, n + 1):
            fh.write(f"1\t{pos}\t.\t{'C' if pos == 1 else 'A'}\t{'G' if pos == 1 else 'C'}\t.\tPASS\t.\n")
    return path


def test_normalizer_can_skip_variant_materialization(tmp_path):
    fasta, fai = make_reference(tmp_path)
    source = make_vcf(tmp_path, 1200)
    output = tmp_path / "normalized.vcf"
    with FastaReference(fasta, fai) as ref:
        result = normalize_vcf_file(source, output, genome_build="GRCh38", reference=ref, collect_variants=False)
    assert result["variants"] is None
    assert result["record_count"] == 1200
    assert sum(1 for _ in iter_normalized_vcf(output, "GRCh38")) == 1200


def test_streamed_batches_have_bounded_partition_size(tmp_path):
    fasta, fai = make_reference(tmp_path)
    source = make_vcf(tmp_path, 1200)
    output = tmp_path / "normalized.vcf"
    with FastaReference(fasta, fai) as ref:
        normalize_vcf_file(source, output, genome_build="GRCh38", reference=ref, collect_variants=False)
    batches = list(_iter_variant_batches(output, "GRCh38", 500))
    assert [start for start, _ in batches] == [0, 500, 1000]
    assert [len(batch) for _, batch in batches] == [500, 500, 200]
    assert max(len(batch) for _, batch in batches) == 500


def test_normalized_vcf_stream_preserves_sample_call_and_quality_fields(tmp_path):
    path = tmp_path / "sample-calls.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PS,Number=1,Type=Integer,Description="Phase set">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n'
        '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tLAB_SAMPLE_1\n"
        "1\t10\t.\tA\tG\t50\tPASS\t.\tGT:PS:DP:GQ:AD\t0|1:42:35:99:20,15\n",
        encoding="utf-8",
    )

    (start, variants), = list(_iter_variant_batches(path, "GRCh38", 50))
    variant_id = uuid4()
    metadata = _normalized_partition_metadata([variant_id], variants)

    assert start == 0
    assert metadata["schema_version"] == 4
    assert metadata["genotype_projection_contract"] == "SOURCE_GT_AND_PER_ALT_DOSAGE_V1"
    assert metadata["genome_build"] == "GRCh38"
    assert metadata["sample_calls"] == [{
        "variant_id": str(variant_id),
        "status": "AVAILABLE",
        "sample_name": "LAB_SAMPLE_1",
        "genotype": "0|1",
        "zygosity": "HETEROZYGOUS",
        "normalized_genotype": "0|1",
        "normalized_zygosity": "HETEROZYGOUS",
        "normalized_phase": "PHASED",
        "source_genotype": "0|1",
        "source_genotype_stage": "INPUT_RECORD",
        "source_zygosity": "HETEROZYGOUS",
        "source_alt_index": 1,
        "source_alt_count": 1,
        "original_source_alt_index": None,
        "original_source_alt_count": None,
        "source_record_index": None,
        "source_record_sha256": None,
        "projection_status": "AVAILABLE",
        "projected_genotype": "0|1",
        "projected_zygosity": "HETEROZYGOUS",
        "reference_allele_dosage": 1,
        "selected_alt_dosage": 1,
        "other_alt_dosage": 0,
        "missing_allele_count": 0,
        "phase": "PHASED",
        "projected_phase": "PHASED",
        "phase_set": "42",
        "format_values": {"DP": "35", "GQ": "99", "AD": "20,15", "PS": "42"},
    }]
    assert metadata["source_record_mappings"] == []


def test_partition_metadata_persists_analysis_scoped_original_allele_mapping(tmp_path):
    path = tmp_path / "source-mapping.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##INFO=<ID=SIRALOOM_ORIG,Number=.,Type=String,Description="Original source record">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC\t.\tPASS\tSIRALOOM_ORIG=1|10|AA|A,AT|2\n",
        encoding="utf-8",
    )
    variant = next(iter_normalized_vcf(path, "GRCh38"))
    variant_id = uuid4()
    metadata = _normalized_partition_metadata([variant_id], [variant])

    assert metadata["source_record_mappings"] == [{
        "variant_id": str(variant_id),
        "source_chromosome": "1",
        "source_position": 10,
        "source_reference": "AA",
        "source_alternate": "A,AT",
        "source_alt_index": 2,
        "original_source_alt_index": None,
        "original_source_alt_count": None,
        "routed_source_alt_index": None,
        "routed_source_alt_count": None,
        "source_record_index": None,
        "source_record_sha256": None,
    }]


def test_normalized_vcf_rejects_malformed_source_allele_index(tmp_path):
    path = tmp_path / "bad-source-mapping.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##INFO=<ID=SIRALOOM_ORIG,Number=.,Type=String,Description="Original source record">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC\t.\tPASS\tSIRALOOM_ORIG=1|10|AA|A,AT|3\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid source-record mapping"):
        next(iter_normalized_vcf(path, "GRCh38"))


def test_vcf_call_parser_distinguishes_reference_alt_haploid_and_no_calls(tmp_path):
    path = tmp_path / "genotypes.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "1\t10\t.\tA\tG\t.\tPASS\t.\tGT\t0/0\n"
        "1\t11\t.\tA\tG\t.\tPASS\t.\tGT\t1/1\n"
        "1\t12\t.\tA\tG\t.\tPASS\t.\tGT\t1\n"
        "1\t13\t.\tA\tG\t.\tPASS\t.\tGT\t./.\n"
        "1\t14\t.\tA\tG\t.\tPASS\t.\tGT\t0/.\n"
        "1\t15\t.\tA\tG\t.\tPASS\t.\tGT\t0\n",
        encoding="utf-8",
    )

    calls = [record.sample_calls["SAMPLE"] for record in parse_vcf(str(path))]
    assert [call["zygosity"] for call in calls] == [
        "HOMOZYGOUS_REFERENCE",
        "HOMOZYGOUS_ALTERNATE",
        "HAPLOID_ALTERNATE",
        "NO_CALL",
        "PARTIAL_CALL",
        "REFERENCE_CALL",
    ]


def test_homozygous_reference_records_are_excluded_from_candidates_and_counted(tmp_path):
    path = tmp_path / "reference-only.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
        "1\t10\t.\tA\tG\t50\tPASS\t.\tGT\t0/0\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\tGT\t0\n"
        "1\t11\t.\tA\tC\t50\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    exclusion_stats = {}

    batches = list(
        _iter_variant_batches(
            path, "GRCh38", 50, exclusion_stats=exclusion_stats
        )
    )

    assert [variant.position for _, batch in batches for variant in batch] == [11]
    assert exclusion_stats == {
        "normalized_allele_records": 3,
        "reference_only_genotype_alleles": 2,
    }
