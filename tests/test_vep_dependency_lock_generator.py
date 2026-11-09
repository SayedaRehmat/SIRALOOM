from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_vep_dependency_lock as generator


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    cpanfile = tmp_path / "cpanfile"
    cpanfile.write_text("requires 'JSON';\n", encoding="utf-8")
    snapshot = tmp_path / "cpanfile.snapshot"
    snapshot.write_text("DISTRIBUTIONS\nJSON 4.11\nCHECKSUM\nabc\n", encoding="utf-8")
    manifest = tmp_path / "native-build-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "architecture": "x86_64",
                "downloaded_debs": [
                    {"filename": "build-essential.deb", "sha256": "a" * 64}
                ],
            }
        ),
        encoding="utf-8",
    )
    cache = tmp_path / "vendor" / "cache"
    (cache / "modules" / "J" / "JS").mkdir(parents=True)
    (cache / "modules" / "J" / "JS" / "JSON-4.11.tar.gz").write_bytes(b"cpan-archive")
    output = tmp_path / "out" / "lock.json"
    return cpanfile, snapshot, manifest, cache, output


def test_lock_generator_hashes_nested_carton_archives(tmp_path, monkeypatch):
    cpanfile, snapshot, manifest, cache, output = _inputs(tmp_path)
    monkeypatch.setattr(generator.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        generator.subprocess,
        "check_output",
        lambda command, text=True: "v5.38.5" if command[1] == "-e" else "carton v1.0.35",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_vep_dependency_lock.py",
            "--architecture", "x86_64",
            "--cpanfile", str(cpanfile),
            "--snapshot", str(snapshot),
            "--build-manifest", str(manifest),
            "--cache-dir", str(cache),
            "--output", str(output),
        ],
    )

    assert generator.main() == 0
    lock = json.loads(output.read_text(encoding="utf-8"))
    archive = cache / "modules" / "J" / "JS" / "JSON-4.11.tar.gz"
    assert lock["archive_count"] == 1
    assert lock["cpan_distribution_archives"][0]["relative_path"] == "modules/J/JS/JSON-4.11.tar.gz"
    assert lock["cpan_distribution_archives"][0]["sha256"] == hashlib.sha256(
        archive.read_bytes()
    ).hexdigest()


def test_lock_generator_rejects_cache_without_distribution_archives(tmp_path, monkeypatch):
    cpanfile, snapshot, manifest, cache, output = _inputs(tmp_path)
    for path in cache.rglob("*.tar.gz"):
        path.unlink()
    monkeypatch.setattr(generator.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_vep_dependency_lock.py",
            "--architecture", "x86_64",
            "--cpanfile", str(cpanfile),
            "--snapshot", str(snapshot),
            "--build-manifest", str(manifest),
            "--cache-dir", str(cache),
            "--output", str(output),
        ],
    )
    with pytest.raises(SystemExit, match="contains no distribution archives"):
        generator.main()
