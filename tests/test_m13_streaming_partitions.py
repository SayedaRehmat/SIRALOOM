from pathlib import Path
from uuid import uuid4

from backend.app.domain.normalization import iter_normalized_vcf, normalize_vcf_file
from backend.app.domain.reference import FastaReference
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
    assert metadata["schema_version"] == 2
    assert metadata["genome_build"] == "GRCh38"
    assert metadata["sample_calls"] == [{
        "variant_id": str(variant_id),
        "status": "AVAILABLE",
        "sample_name": "LAB_SAMPLE_1",
        "genotype": "0|1",
        "zygosity": "HETEROZYGOUS",
        "phase": "PHASED",
        "phase_set": "42",
        "format_values": {"DP": "35", "GQ": "99", "AD": "20,15", "PS": "42"},
    }]


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
        "1\t14\t.\tA\tG\t.\tPASS\t.\tGT\t0/.\n",
        encoding="utf-8",
    )

    calls = [variant.sample_call for _, batch in _iter_variant_batches(path, "GRCh38", 50) for variant in batch]
    assert [call["zygosity"] for call in calls] == [
        "HOMOZYGOUS_REFERENCE",
        "HOMOZYGOUS_ALTERNATE",
        "HAPLOID_ALTERNATE",
        "NO_CALL",
        "PARTIAL_CALL",
    ]
