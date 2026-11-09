#!/usr/bin/env python3
"""Create a candidate VEP lock from native Carton and Conda resolution outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

ARCHES = {"x86_64", "aarch64"}
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".zip")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", required=True, choices=sorted(ARCHES))
    parser.add_argument("--cpanfile", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--conda-lock", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    actual_arch = platform.machine()
    if actual_arch != args.architecture:
        raise SystemExit(f"native architecture mismatch: expected {args.architecture}, got {actual_arch}")

    snapshot = args.snapshot.read_text(encoding="utf-8")
    if "DISTRIBUTIONS\\n" not in snapshot or "CHECKSUM\\n" not in snapshot:
        raise SystemExit("Carton snapshot is incomplete: missing DISTRIBUTIONS or CHECKSUM section")
    conda_lock = args.conda_lock.read_text(encoding="utf-8")
    if "@EXPLICIT" not in conda_lock:
        raise SystemExit("Conda lock is not an explicit artifact-level lock")

    archives = []
    for path in sorted(args.cache_dir.iterdir()):
        if path.is_file() and path.name.endswith(ARCHIVE_SUFFIXES):
            archives.append({
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            })
    if not archives:
        raise SystemExit("Carton vendor/cache contains no distribution archives")

    perl_version = __import__("subprocess").check_output(
        ["perl", "-e", "print $^V"], text=True
    ).strip()
    if not perl_version.startswith("v5.38."):
        raise SystemExit(f"unsupported Perl candidate; expected 5.38.x, got {perl_version}")

    payload = {
        "schema": "siraloom.vep-dependency-lock.v1",
        "tool": "ensembl-vep",
        "software_version": "115.2",
        "cache_release": "115",
        "architecture": args.architecture,
        "platform": "linux-64" if args.architecture == "x86_64" else "linux-aarch64",
        "qualification_status": "CANDIDATE",
        "lock_scope": "native_conda_and_cpan_runtime_resolution",
        "perl_version": perl_version,
        "cpanfile_sha256": sha256(args.cpanfile),
        "cpanfile": args.cpanfile.read_text(encoding="utf-8"),
        "carton_snapshot": snapshot,
        "carton_snapshot_sha256": sha256(args.snapshot),
        "conda_explicit_lock": conda_lock,
        "conda_explicit_lock_sha256": sha256(args.conda_lock),
        "cpan_distribution_archives": archives,
        "archive_count": len(archives),
        "limitations": [
            "Candidate dependency lock only; not a VEP image or scientific qualification.",
            "Bio::DB::HTS and HTSlib must pass native build and runtime tests.",
            "GRCh37/GRCh38 cache manifests, plugin locks, annotation fixtures, offline execution, and recovery qualification remain separate gates.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    print(f"wrote {args.output} with {len(archives)} hashed CPAN archives for {args.architecture}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
