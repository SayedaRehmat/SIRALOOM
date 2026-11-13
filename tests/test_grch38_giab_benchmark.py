from __future__ import annotations

import pytest

from scripts.validation.run_grch38_giab_three_caller_benchmark import build_fai, fasta_sequence


def test_build_fai_tracks_wrapped_sequences_and_byte_offsets(tmp_path):
    fasta = tmp_path / "toy.fa"
    fasta.write_bytes(b">chr1 description\nACGT\nTGCA\n>chr2\nNN\n")
    entries = build_fai(fasta)

    assert entries == [
        {"name": "chr1", "length": 8, "offset": 19, "line_bases": 4, "line_width": 5},
        {"name": "chr2", "length": 2, "offset": 38, "line_bases": 2, "line_width": 3},
    ]
    assert (tmp_path / "toy.fa.fai").read_text() == (
        "chr1\t8\t19\t4\t5\n"
        "chr2\t2\t38\t2\t3\n"
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
