from pathlib import Path

from backend.app.domain.normalization import iter_normalized_vcf, normalize_vcf_file
from backend.app.domain.reference import FastaReference
from backend.app.workflows.variant import _iter_variant_batches


def make_reference(tmp_path: Path):
    fasta = tmp_path / "ref.fa"
    seq = "C" + "A" * 1999
    fasta.write_text(">1\n" + seq + "\n", encoding="utf-8")
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
