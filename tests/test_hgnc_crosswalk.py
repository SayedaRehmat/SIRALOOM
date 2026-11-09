from __future__ import annotations

import csv
from pathlib import Path

import pytest

from backend.app.domain.hgnc_crosswalk import (
    HGNC_ARCHIVE_RELEASE,
    HGNCResolutionStatus as Status,
    HGNCResolver,
    HGNCResourceError,
)


GENE_FIELDS = ["hgnc_id", "symbol", "alias_symbol", "prev_symbol", "ensembl_gene_id"]
WITHDRAWN_FIELDS = ["HGNC_ID", "STATUS", "WITHDRAWN_SYMBOL", "MERGED_INTO_REPORT(S) i.e. HGNC_ID|SYMBOL|STATUS"]


def _write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def resolver(tmp_path):
    complete = tmp_path / "hgnc_complete_set.txt"
    withdrawn = tmp_path / "withdrawn.txt"
    _write_tsv(complete, GENE_FIELDS, [
        {"hgnc_id": "HGNC:1", "symbol": "GENEA", "alias_symbol": "OLD_A|SHARED", "prev_symbol": "PREV_A", "ensembl_gene_id": "ENSG00000123456"},
        {"hgnc_id": "HGNC:2", "symbol": "GENEB", "alias_symbol": "SHARED", "prev_symbol": "PREV_B", "ensembl_gene_id": "ENSG00000654321"},
        {"hgnc_id": "HGNC:3", "symbol": "GENEC", "alias_symbol": "SPLIT_X", "prev_symbol": "", "ensembl_gene_id": ""},
    ])
    _write_tsv(withdrawn, WITHDRAWN_FIELDS, [
        {"HGNC_ID": "HGNC:90", "STATUS": "Merged/Split", "WITHDRAWN_SYMBOL": "RETIRED_A", "MERGED_INTO_REPORT(S) i.e. HGNC_ID|SYMBOL|STATUS": "HGNC:1|GENEA|Approved"},
        {"HGNC_ID": "HGNC:91", "STATUS": "Entry Withdrawn", "WITHDRAWN_SYMBOL": "RETIRED_X", "MERGED_INTO_REPORT(S) i.e. HGNC_ID|SYMBOL|STATUS": ""},
        {"HGNC_ID": "HGNC:92", "STATUS": "Merged/Split", "WITHDRAWN_SYMBOL": "SPLIT_X", "MERGED_INTO_REPORT(S) i.e. HGNC_ID|SYMBOL|STATUS": "HGNC:1|GENEA|Approved,HGNC:2|GENEB|Approved"},
    ])
    return HGNCResolver(complete, withdrawn, release=HGNC_ARCHIVE_RELEASE)


def test_approved_symbol_and_case_normalization(resolver):
    result = resolver.resolve(" genea ")
    assert result.status == Status.APPROVED_SYMBOL
    assert result.hgnc_id == "HGNC:1"
    assert result.approved_symbol == "GENEA"


def test_alias_symbol_resolves_exactly(resolver):
    result = resolver.resolve("old_a")
    assert result.status == Status.ALIAS_SYMBOL
    assert result.hgnc_id == "HGNC:1"


def test_ambiguous_alias_is_not_arbitrarily_selected(resolver):
    result = resolver.resolve("SHARED")
    assert result.status == Status.AMBIGUOUS
    assert result.hgnc_id is None
    assert result.candidate_hgnc_ids == ("HGNC:1", "HGNC:2")


def test_previous_symbol_resolves_exactly(resolver):
    result = resolver.resolve("PREV_B")
    assert result.status == Status.PREVIOUS_SYMBOL
    assert result.hgnc_id == "HGNC:2"


def test_ensembl_gene_id_resolves_without_transcript_mapping(resolver):
    result = resolver.resolve("ENSG00000123456.7")
    assert result.status == Status.ENSEMBL_GENE_ID
    assert result.hgnc_id == "HGNC:1"


def test_hgnc_accession_must_be_currently_approved(resolver):
    assert resolver.resolve("HGNC:2").hgnc_id == "HGNC:2"
    assert resolver.resolve("HGNC:90").status == Status.NOT_FOUND


def test_single_target_withdrawn_symbol_resolves_to_explicit_approved_merge(resolver):
    result = resolver.resolve("RETIRED_A")
    assert result.status == Status.WITHDRAWN_MERGED
    assert result.hgnc_id == "HGNC:1"


@pytest.mark.parametrize("symbol", ["RETIRED_X", "SPLIT_X"])
def test_withdrawn_or_split_symbol_remains_unresolved(resolver, symbol):
    result = resolver.resolve(symbol)
    assert result.status == Status.WITHDRAWN_UNRESOLVED
    assert result.hgnc_id is None


def test_unknown_and_invalid_identifiers_are_not_fuzzy_matched(resolver):
    assert resolver.resolve("GENE-A").status == Status.NOT_FOUND
    assert resolver.resolve("").status == Status.INVALID
    assert resolver.resolve("ENST00000123456").status == Status.NOT_FOUND


def test_duplicate_release_identity_is_rejected(tmp_path):
    complete = tmp_path / "complete.tsv"
    withdrawn = tmp_path / "withdrawn.tsv"
    _write_tsv(complete, GENE_FIELDS, [
        {"hgnc_id": "HGNC:1", "symbol": "A", "alias_symbol": "", "prev_symbol": "", "ensembl_gene_id": ""},
        {"hgnc_id": "HGNC:1", "symbol": "B", "alias_symbol": "", "prev_symbol": "", "ensembl_gene_id": ""},
    ])
    _write_tsv(withdrawn, WITHDRAWN_FIELDS, [
        {"HGNC_ID": "HGNC:90", "STATUS": "Entry Withdrawn", "WITHDRAWN_SYMBOL": "OLD", "MERGED_INTO_REPORT(S) i.e. HGNC_ID|SYMBOL|STATUS": ""},
    ])
    with pytest.raises(HGNCResourceError, match="duplicate approved HGNC ID"):
        HGNCResolver(complete, withdrawn, release=HGNC_ARCHIVE_RELEASE)


def test_unsupported_release_is_rejected(tmp_path):
    with pytest.raises(HGNCResourceError, match="unsupported HGNC release"):
        HGNCResolver(tmp_path / "missing", tmp_path / "missing2", release="latest")


def test_pinned_acquisition_preserves_both_artifacts_and_local_digests(tmp_path, monkeypatch):
    import io
    import json

    from backend.app.domain import hgnc_crosswalk

    payloads = {
        hgnc_crosswalk.HGNC_COMPLETE_URL: b"complete-set-bytes",
        hgnc_crosswalk.HGNC_WITHDRAWN_URL: b"withdrawn-bytes",
    }

    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(request, timeout):
        assert timeout == 120
        return Response(payloads[request.full_url])

    monkeypatch.setattr(hgnc_crosswalk, "urlopen", fake_urlopen)
    manifest = hgnc_crosswalk.acquire_hgnc_release(tmp_path)

    assert manifest["release"] == HGNC_ARCHIVE_RELEASE
    assert manifest["checksum_semantics"] == "LOCAL_SHA256; HGNC_DOES_NOT_PUBLISH_FILE_CHECKSUMS"
    assert (tmp_path / "hgnc_complete_set.txt").read_bytes() == payloads[hgnc_crosswalk.HGNC_COMPLETE_URL]
    assert (tmp_path / "withdrawn.txt").read_bytes() == payloads[hgnc_crosswalk.HGNC_WITHDRAWN_URL]
    persisted = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert persisted == manifest
    assert len({item["sha256"] for item in manifest["files"]}) == 2


def test_acquisition_failure_cleans_partial_temporary_files(tmp_path, monkeypatch):
    import io

    from backend.app.domain import hgnc_crosswalk

    calls = 0

    class Response(io.BytesIO):
        def __init__(self, data, status):
            super().__init__(data)
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        return Response(b"first-artifact" if calls == 1 else b"", 200 if calls == 1 else 503)

    monkeypatch.setattr(hgnc_crosswalk, "urlopen", fake_urlopen)
    with pytest.raises(HGNCResourceError, match="HTTP 503"):
        hgnc_crosswalk.acquire_hgnc_release(tmp_path)
    assert list(tmp_path.iterdir()) == []
