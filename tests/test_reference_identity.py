from pathlib import Path

import pytest

from backend.app.domain.reference_identity import (
    ReferenceIdentityError,
    ga4gh_digest_bytes,
    inspect_fasta_sequence_identity,
    seqcol_digest,
    validate_sequence_dictionary,
)


def test_refget_sequence_digest_matches_ga4gh_reference_example():
    assert ga4gh_digest_bytes(b"ACGT") == "SQ.aKF498dAxcJAqme6QYQ7EZ07-fiw8Kw2"


def test_seqcol_minimal_schema_digest_matches_ga4gh_reference_example():
    names = ["chr1", "chr2", "chr3"]
    lengths = [248956422, 242193529, 198295559]
    sequences = [
        "SQ.2YnepKM7OkBoOrKmvHbGqguVfF9amCST",
        "SQ.lwDyBi432Py-7xnAISyQlnlhWDEaBPv2",
        "SQ.Eqk6_SvMMDCc6C-uEfickOUWTatLMDQZ",
    ]
    assert seqcol_digest(names, lengths, sequences) == "sjNNwm4zov3Dl0FRWbRTcZwzqrTQKIqL"


def test_fasta_sequence_identity_is_per_contig_and_ordered(tmp_path: Path):
    fasta = tmp_path / "identity.fa"
    fasta.write_text(">chr1 description\nACGT\n>chrM\nacgt\n", encoding="ascii")
    identity = inspect_fasta_sequence_identity(fasta)

    assert [entry["name"] for entry in identity["sequences"]] == ["chr1", "chrM"]
    assert identity["sequences"][0]["ga4gh"] == identity["sequences"][1]["ga4gh"]
    assert identity["sequences"][0]["md5"] == identity["sequences"][1]["md5"]
    assert identity["sequence_collection_digest"].startswith("")


def test_sequence_dictionary_must_match_order_length_and_md5(tmp_path: Path):
    fasta = tmp_path / "identity.fa"
    fasta.write_text(">chr1\nACGT\n>chrM\nTGCA\n", encoding="ascii")
    identity = inspect_fasta_sequence_identity(fasta)
    dictionary = tmp_path / "identity.dict"
    dictionary.write_text(
        "@HD\\tVN:1.6\\tSO:unsorted\n"
        + "".join(
            f"@SQ\\tSN:{entry['name']}\\tLN:{entry['length']}\\tM5:{entry['md5']}\\n"
            for entry in identity["sequences"]
        ),
        encoding="ascii",
    )
    result = validate_sequence_dictionary(dictionary, identity["sequences"])
    assert result["status"] == "VERIFIED"
    assert result["contig_count"] == 2


def test_sequence_dictionary_rejects_mismatched_m5(tmp_path: Path):
    fasta = tmp_path / "identity.fa"
    fasta.write_text(">chr1\nACGT\n", encoding="ascii")
    identity = inspect_fasta_sequence_identity(fasta)
    dictionary = tmp_path / "identity.dict"
    dictionary.write_text(
        "@HD\\tVN:1.6\\tSO:unsorted\n"
        "@SQ\\tSN:chr1\\tLN:4\\tM5:00000000000000000000000000000000\n",
        encoding="ascii",
    )
    with pytest.raises(ReferenceIdentityError) as exc:
        validate_sequence_dictionary(dictionary, identity["sequences"])
    assert exc.value.code == "REFERENCE_DICTIONARY_MISMATCH"
