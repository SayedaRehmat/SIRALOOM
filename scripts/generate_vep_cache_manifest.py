#!/usr/bin/env python3
"""Create an integrity manifest for a locally installed Ensembl VEP cache.

This records cache bytes; it does not qualify annotation accuracy. The laboratory
must independently verify and approve the source artifact digest and manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "siraloom.vep-cache-manifest.v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assembly(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"grch37", "hg19"}:
        return "GRCh37"
    if normalized in {"grch38", "hg38"}:
        return "GRCh38"
    raise ValueError("assembly must be GRCh37 or GRCh38")


def build_manifest(
    cache_dir: str | Path,
    *,
    cache_version: str,
    species: str,
    assembly: str,
    source_artifact_sha256: str,
) -> dict[str, Any]:
    root = Path(cache_dir).expanduser()
    if root.is_symlink():
        raise ValueError("cache directory cannot be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("cache directory must exist and be a directory")
    if not cache_version.strip() or not species.strip():
        raise ValueError("cache_version and species are required")
    source_digest = source_artifact_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise ValueError("source_artifact_sha256 must be a 64-character SHA-256 digest")

    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"cache contains a symlink: {path.relative_to(root)}")
        mode = path.stat(follow_symlinks=False).st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(f"cache contains a non-regular entry: {path.relative_to(root)}")
        files.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        })
    if not files:
        raise ValueError("cache directory contains no regular files")
    return {
        "schema": SCHEMA,
        "cache_version": cache_version.strip(),
        "species": species.strip(),
        "assembly": _assembly(assembly),
        "source_artifact_sha256": source_digest,
        "files": files,
    }


def write_manifest(document: dict[str, Any], output: str | Path, *, overwrite: bool = False) -> str:
    output_path = Path(output).expanduser()
    if output_path.is_symlink():
        raise ValueError("manifest output cannot be a symlink")
    destination = output_path.resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    digest = hashlib.sha256(rendered).hexdigest()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{destination.name}.", suffix=".tmp",
            dir=destination.parent, delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary_path, destination)
            temporary_path = None
        else:
            os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--cache-version", required=True)
    parser.add_argument("--species", default="homo_sapiens")
    parser.add_argument("--assembly", required=True, choices=("GRCh37", "GRCh38", "hg19", "hg38"))
    parser.add_argument("--source-artifact-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        root = args.cache_dir.expanduser().resolve(strict=True)
        output = args.output.expanduser().resolve(strict=False)
        if output == root or root in output.parents:
            raise ValueError("manifest output must be outside the cache directory")
        document = build_manifest(
            args.cache_dir,
            cache_version=args.cache_version,
            species=args.species,
            assembly=args.assembly,
            source_artifact_sha256=args.source_artifact_sha256,
        )
        digest = write_manifest(document, args.output, overwrite=args.overwrite)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
