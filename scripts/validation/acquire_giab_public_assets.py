#!/usr/bin/env python3
"""Acquire pinned NIST GIAB HG001 assets and preserve byte-level provenance.

Every downloaded byte is checked against the release-pinned official MD5 before
it is accepted. SHA-256 is calculated locally for durable evidence. There is no
fallback mirror and no automatic checksum refresh: source drift fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MANIFEST_VERSION = "1"


class AcquisitionError(RuntimeError):
    pass


def digest_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url: str, destination: Path, expected_md5: str) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise AcquisitionError(f"Refusing to overwrite existing asset: {destination}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        md5 = hashlib.md5(usedforsecurity=False)
        sha256 = hashlib.sha256()
        size = 0
        request = urllib.request.Request(url, headers={"User-Agent": "SIRALOOM-GIAB-qualification/1.0"})
        with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 200:
                raise AcquisitionError(f"Unexpected HTTP status {response.status} for {url}")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                md5.update(chunk)
                sha256.update(chunk)
                size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        observed_md5 = md5.hexdigest()
        if observed_md5.lower() != expected_md5.lower():
            raise AcquisitionError(
                f"Official MD5 mismatch for {url}: expected {expected_md5}, observed {observed_md5}"
            )
        os.replace(temporary, destination)
        return {
            "url": url,
            "path": str(destination),
            "size_bytes": size,
            "official_md5_expected": expected_md5.lower(),
            "official_md5_observed": observed_md5,
            "official_md5_verified": True,
            "sha256": sha256.hexdigest(),
        }
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--build", choices=("GRCh37", "GRCh38"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provenance-out", type=Path, required=True)
    args = parser.parse_args()

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != MANIFEST_VERSION:
            raise AcquisitionError("Unsupported public asset manifest schema.")
        if manifest.get("dataset") != "NIST_GIAB_HG001_NISTv4.2.1":
            raise AcquisitionError("Unexpected benchmark dataset identity.")
        if args.output_dir.exists() and any(args.output_dir.iterdir()):
            raise AcquisitionError("Asset output directory must be empty; preserve prior run assets.")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        entries = manifest["assets"][args.build]
        if len(entries) != 6:
            raise AcquisitionError(f"{args.build} manifest must declare six required assets.")
        acquired: dict[str, Any] = {}
        for key, relative_path, expected_md5 in entries:
            if key in acquired or not isinstance(expected_md5, str) or len(expected_md5) != 32:
                raise AcquisitionError(f"Invalid or duplicate asset declaration: {key}")
            root = manifest["reference_root"] if relative_path.startswith("references/") else manifest["source_root"]
            url = f"{root.rstrip('/')}/{relative_path.removeprefix('references/') if root == manifest['reference_root'] else relative_path}"
            filename = Path(relative_path).name
            acquired[key] = download_verified(url, args.output_dir / filename, expected_md5)

        fasta = Path(acquired["reference_fasta"]["path"])
        fai = Path(acquired["reference_fai"]["path"])
        gzi = Path(acquired["reference_gzi"]["path"])
        if fai.name != f"{fasta.name}.fai" or gzi.name != f"{fasta.name}.gzi":
            raise AcquisitionError("Reference FAI/GZI names do not match the selected compressed FASTA.")
        if acquired["truth_vcf"]["path"].endswith(".vcf.gz") is False:
            raise AcquisitionError("GIAB truth VCF must be BGZF-compressed VCF.")
        report = {
            "schema_version": "1",
            "status": "ASSETS_ACQUIRED_AND_CHECKSUM_VERIFIED",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "dataset": manifest["dataset"],
            "sample": manifest["sample"],
            "reference_build": args.build,
            "release": manifest["source_release"],
            "checksum_policy": "Official NIST MD5 verified before atomic publication; local SHA-256 recorded.",
            "assets": acquired,
            "reference_pair": {
                "fasta": acquired["reference_fasta"]["path"],
                "fai": acquired["reference_fai"]["path"],
                "gzi": acquired["reference_gzi"]["path"],
                "fasta_sha256": acquired["reference_fasta"]["sha256"],
                "fai_sha256": acquired["reference_fai"]["sha256"],
                "gzi_sha256": acquired["reference_gzi"]["sha256"],
            },
            "qualification_boundary": (
                "Asset provenance and byte integrity only. This does not establish reference biological "
                "qualification, caller qualification, clinical validity, or laboratory acceptance."
            ),
        }
        args.provenance_out.parent.mkdir(parents=True, exist_ok=True)
        args.provenance_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "build": args.build, "assets": len(acquired), "provenance": str(args.provenance_out)}, indent=2))
        return 0
    except (AcquisitionError, OSError, KeyError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"GIAB asset acquisition failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
