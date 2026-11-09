#!/usr/bin/env python3
"""Create a candidate VEP lock from native Carton and OS package resolution outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ARCHES = {"x86_64", "aarch64"}
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".zip")
PERL_VERSION = "5.38.5"
PERL_SOURCE_URL = "https://www.cpan.org/src/5.0/perl-5.38.5.tar.gz"
PERL_SOURCE_SHA256 = "b7667d3ff309068852af7853910aaccec26c839d717402121b664ac705e07bfe"


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
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    actual_arch = platform.machine()
    if actual_arch != args.architecture:
        raise SystemExit(f"native architecture mismatch: expected {args.architecture}, got {actual_arch}")

    snapshot = args.snapshot.read_text(encoding="utf-8")
    if "DISTRIBUTIONS\\n" not in snapshot or "CHECKSUM\\n" not in snapshot:
        raise SystemExit("Carton snapshot is incomplete: missing DISTRIBUTIONS or CHECKSUM section")

    build_manifest = json.loads(args.build_manifest.read_text(encoding="utf-8"))
    if build_manifest.get("architecture") != args.architecture:
        raise SystemExit("native build-package manifest architecture mismatch")
    if not build_manifest.get("downloaded_debs"):
        raise SystemExit("native build-package manifest has no hashed Debian packages")

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

    perl_version = subprocess.check_output(["perl", "-e", "print $^V"], text=True).strip()
    if perl_version != "v" + PERL_VERSION:
        raise SystemExit(f"Perl source build mismatch: expected v{PERL_VERSION}, got {perl_version}")
    carton_version = subprocess.check_output(["carton", "--version"], text=True).strip()

    payload = {
        "schema": "siraloom.vep-dependency-lock.v1",
        "tool": "ensembl-vep",
        "software_version": "115.2",
        "cache_release": "115",
        "architecture": args.architecture,
        "platform": "linux-64" if args.architecture == "x86_64" else "linux-aarch64",
        "qualification_status": "CANDIDATE",
        "lock_scope": "native_perl_cpan_and_os_build_dependency_resolution",
        "perl": {
            "version": perl_version,
            "source_url": PERL_SOURCE_URL,
            "source_sha256": PERL_SOURCE_SHA256,\n            "lifecycle_status": "end_of_life",
        },
        "carton_version": carton_version,
        "cpanfile_sha256": sha256(args.cpanfile),
        "cpanfile": args.cpanfile.read_text(encoding="utf-8"),
        "carton_snapshot": snapshot,
        "carton_snapshot_sha256": sha256(args.snapshot),
        "native_build_manifest": build_manifest,
        "native_build_manifest_sha256": sha256(args.build_manifest),
        "cpan_distribution_archives": archives,
        "archive_count": len(archives),
        "limitations": [
            "Candidate dependency lock only; not a VEP image or scientific qualification.",\n            "Perl 5.38 reached end of life on 2025-08-03; this compatibility candidate cannot be production-promoted without an approved security exception or a separately qualified supported Perl release.",
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
