from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from backend.app.domain import resource_qualification as qualification


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_hgnc_qualification_verifies_pinned_artifact_bytes_and_manifest(tmp_path, monkeypatch):
    complete = tmp_path / "hgnc_complete_set.txt"
    withdrawn = tmp_path / "withdrawn.txt"
    complete.write_text("approved gene fixture", encoding="utf-8")
    withdrawn.write_text("withdrawn fixture", encoding="utf-8")
    manifest = {
        "schema": "siraloom.hgnc-acquisition.v1",
        "publisher": "HUGO Gene Nomenclature Committee",
        "release": "2026-10-06",
        "license": "CC0-1.0",
        "checksum_semantics": "LOCAL_SHA256; HGNC_DOES_NOT_PUBLISH_FILE_CHECKSUMS",
        "files": [
            {
                "filename": "hgnc_complete_set.txt",
                "source_url": "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/quarterly/tsv/hgnc_complete_set_2026-10-06.txt",
                "sha256": _sha(complete),
                "size_bytes": complete.stat().st_size,
            },
            {
                "filename": "withdrawn.txt",
                "source_url": "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/quarterly/tsv/withdrawn_2026-10-06.txt",
                "sha256": _sha(withdrawn),
                "size_bytes": withdrawn.stat().st_size,
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class FakeResolver:
        _approved = {f"HGNC:{i}": {} for i in range(10001)}
        _approved_symbols = {"A": {"HGNC:1"}}
        _alias_index = {"OLD_A": {"HGNC:1"}}
        _previous = {"PREV_A": {"HGNC:1"}}
        _ensembl = {"ENSG00000123456": {"HGNC:1"}}
        _withdrawn = {"OLD_X": []}
        complete_sha256 = _sha(complete)
        withdrawn_sha256 = _sha(withdrawn)

        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(qualification, "HGNCResolver", FakeResolver)
    blockers: list[str] = []
    checks: dict = {}
    resource = SimpleNamespace(version="2026-10-06")
    qualification._qualify_hgnc(resource, manifest_path, blockers, checks)

    assert blockers == []
    assert checks["hgnc_crosswalk"]["status"] == "QUALIFICATION_CHECKS_PASSED"
    assert checks["hgnc_crosswalk"]["approved_gene_count"] == 10001
    assert checks["hgnc_crosswalk"]["upstream_checksums_published"] is False


def test_hgnc_qualification_blocks_artifact_digest_mismatch(tmp_path, monkeypatch):
    complete = tmp_path / "hgnc_complete_set.txt"
    withdrawn = tmp_path / "withdrawn.txt"
    complete.write_text("actual bytes", encoding="utf-8")
    withdrawn.write_text("withdrawn bytes", encoding="utf-8")
    manifest = {
        "schema": "siraloom.hgnc-acquisition.v1",
        "publisher": "HUGO Gene Nomenclature Committee",
        "release": "2026-10-06",
        "license": "CC0-1.0",
        "files": [
            {
                "filename": "hgnc_complete_set.txt",
                "source_url": "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/quarterly/tsv/hgnc_complete_set_2026-10-06.txt",
                "sha256": "0" * 64,
                "size_bytes": complete.stat().st_size,
            },
            {
                "filename": "withdrawn.txt",
                "source_url": "https://storage.googleapis.com/public-download-files/hgnc/archive/archive/quarterly/tsv/withdrawn_2026-10-06.txt",
                "sha256": _sha(withdrawn),
                "size_bytes": withdrawn.stat().st_size,
            },
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    blockers: list[str] = []
    checks: dict = {}
    qualification._qualify_hgnc(SimpleNamespace(version="2026-10-06"), path, blockers, checks)
    assert "HGNC_CROSSWALK_QUALIFICATION_FAILED" in blockers
    assert checks["hgnc_crosswalk"]["status"] == "BLOCKED"
