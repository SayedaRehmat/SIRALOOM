import hashlib
import json

import pytest

from scripts.generate_vep_cache_manifest import build_manifest, write_manifest


def test_manifest_generation_is_deterministic_and_matches_cache_contents(tmp_path):
    cache = tmp_path / "vep-cache"
    nested = cache / "homo_sapiens" / "115_GRCh38"
    nested.mkdir(parents=True)
    (nested / "transcript_cache.gz").write_bytes(b"cache fixture")
    output = tmp_path / "vep-cache-manifest.json"
    source_digest = "a" * 64

    document = build_manifest(
        cache,
        cache_version="115",
        species="homo_sapiens",
        assembly="hg38",
        source_artifact_sha256=source_digest,
    )
    first_digest = write_manifest(document, output)
    second = build_manifest(
        cache,
        cache_version="115",
        species="homo_sapiens",
        assembly="GRCh38",
        source_artifact_sha256=source_digest,
    )

    assert second == document
    assert first_digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads(output.read_text(encoding="utf-8")) == document
    assert document["files"] == [{
        "path": "homo_sapiens/115_GRCh38/transcript_cache.gz",
        "sha256": hashlib.sha256(b"cache fixture").hexdigest(),
        "size_bytes": len(b"cache fixture"),
    }]


def test_manifest_writer_does_not_replace_existing_approval_artifact(tmp_path):
    output = tmp_path / "manifest.json"
    output.write_text("approved", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_manifest({"schema": "fixture"}, output)

    assert output.read_text(encoding="utf-8") == "approved"


def test_manifest_rejects_symlinked_cache_entries(tmp_path):
    cache = tmp_path / "vep-cache"
    cache.mkdir()
    target = tmp_path / "outside"
    target.write_text("not part of cache", encoding="utf-8")
    (cache / "outside-link").symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        build_manifest(
            cache,
            cache_version="115",
            species="homo_sapiens",
            assembly="GRCh38",
            source_artifact_sha256="a" * 64,
        )


def test_manifest_writer_rejects_symlinked_output(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("preserve", encoding="utf-8")
    output = tmp_path / "manifest.json"
    output.symlink_to(target)

    with pytest.raises(ValueError, match="cannot be a symlink"):
        write_manifest({"schema": "fixture"}, output, overwrite=True)

    assert target.read_text(encoding="utf-8") == "preserve"
