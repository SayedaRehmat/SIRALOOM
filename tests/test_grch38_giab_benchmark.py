from __future__ import annotations

import pytest

from scripts.validation.run_grch38_giab_three_caller_benchmark import (
    GIAB_BASE,
    GIAB_BED,
    GIAB_TBI,
    GIAB_VCF,
    STRAT_URL,
    build_fai,
    fasta_sequence,
    http_error_context,
)


def test_build_fai_tracks_wrapped_sequences_and_byte_offsets(tmp_path):
    fasta = tmp_path / "toy.fa"
    fasta.write_bytes(b">chr1 description\nACGT\nTGCA\n>chr2\nNN\n")
    entries = build_fai(fasta)

    assert entries == [
        {"name": "chr1", "length": 8, "offset": 18, "line_bases": 4, "line_width": 5},
        {"name": "chr2", "length": 2, "offset": 34, "line_bases": 2, "line_width": 3},
    ]
    assert (tmp_path / "toy.fa.fai").read_text() == (
        "chr1\t8\t18\t4\t5\n"
        "chr2\t2\t34\t2\t3\n"
    )
    assert fasta_sequence(fasta, "chr1") == "ACGTTGCA"


def test_build_fai_accounts_for_crlf_line_endings(tmp_path):
    fasta = tmp_path / "crlf.fa"
    fasta.write_bytes(b">chr1\r\nACGT\r\nTGCA\r\n")
    entries = build_fai(fasta)
    assert entries[0]["offset"] == 7
    assert entries[0]["line_bases"] == 4
    assert entries[0]["line_width"] == 6
    assert entries[0]["length"] == 8


def test_build_fai_rejects_inconsistent_nonterminal_wrapping(tmp_path):
    fasta = tmp_path / "invalid.fa"
    fasta.write_bytes(b">chr1\nAAAA\nAA\nGGGG\n")
    with pytest.raises(RuntimeError, match="inconsistent width"):
        build_fai(fasta)


def test_build_fai_rejects_duplicate_contig_names(tmp_path):
    fasta = tmp_path / "duplicate.fa"
    fasta.write_bytes(b">chr1\nAAAA\n>chr1 duplicate\nCCCC\n")
    with pytest.raises(RuntimeError, match="duplicate"):
        build_fai(fasta)



def test_giab_resources_use_ncbi_giab_release_paths_individually():
    expected_base = (
        "https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/"
        "AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38"
    )
    assert GIAB_BASE == expected_base
    assert GIAB_VCF == f"{expected_base}/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
    assert GIAB_TBI == f"{GIAB_VCF}.tbi"
    assert GIAB_BED == (
        f"{expected_base}/HG002_GRCh38_1_22_v4.2.1_benchmark_noinconsistent.bed"
    )
    assert "/ReferenceSamples/" not in STRAT_URL
    assert "/giab/ftp/release/genome-stratifications/" in STRAT_URL


def test_http_error_context_identifies_exact_resource_url_and_destination(tmp_path):
    url = "https://example.invalid/HG002_truth.vcf.gz"
    destination = tmp_path / "HG002_truth.vcf.gz"
    message = http_error_context(url, destination, 404, "Not Found")
    assert "status=404" in message
    assert url in message
    assert str(destination) in message
