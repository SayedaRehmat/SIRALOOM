#!/usr/bin/env python3
"""Acquire pinned GIAB HG001 assets and construct a matching BGZF reference package.

Upstream compressed reference bytes and GIAB benchmark assets are verified
against pinned official MD5 values. The FASTA is then streamed through gzip
decompression and pinned-environment bgzip; samtools faidx generates matching
FAI/GZI indexes. SHA-256 is calculated for every source and derived artifact.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AcquisitionError(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = dict(details or {})


def digest_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_failure_provenance(
    path: Path,
    *,
    build: str,
    dataset: str | None,
    failed_stage: str,
    failed_asset: str | None,
    error: Exception,
) -> None:
    """Persist safe, structured diagnostics when public asset acquisition fails."""
    payload = {
        "schema_version": "1",
        "status": "FAILED",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset": dataset,
        "reference_build": build,
        "failed_stage": failed_stage,
        "failed_asset": failed_asset,
        "exception_type": type(error).__name__,
        "error": str(error),
        "details": getattr(error, "details", {}) or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


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
        try:
            response_context = urllib.request.urlopen(request, timeout=180)
        except urllib.error.HTTPError as exc:
            raise AcquisitionError(f"HTTP {exc.code} fetching pinned asset URL: {url}") from exc
        response_metadata: dict[str, Any] = {}
        with os.fdopen(fd, "wb") as output, response_context as response:
            response_metadata = {
                "requested_url": url,
                "final_url": response.geturl(),
                "http_status": response.status,
                "content_length": response.headers.get("Content-Length"),
                "content_encoding": response.headers.get("Content-Encoding"),
                "content_type": response.headers.get("Content-Type"),
            }
            if response.status != 200:
                raise AcquisitionError(
                    f"Unexpected HTTP status {response.status} for pinned asset URL: {url}",
                    details={"stage": "asset_download", "response": response_metadata},
                )
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
        content_length = response_metadata.get("content_length")
        if content_length and content_length.isdigit() and int(content_length) != size:
            raise AcquisitionError(
                f"Downloaded asset size does not match HTTP Content-Length for {url}: "
                f"expected {content_length}, observed {size}",
                details={
                    "stage": "asset_transfer_integrity",
                    "url": url,
                    "expected_content_length": int(content_length),
                    "observed_size_bytes": size,
                    "observed_md5": md5.hexdigest(),
                    "observed_sha256": sha256.hexdigest(),
                    "response": response_metadata,
                },
            )
        observed_md5 = md5.hexdigest()
        if observed_md5.lower() != expected_md5.lower():
            raise AcquisitionError(
                f"Official MD5 mismatch for {url}: expected {expected_md5}, observed {observed_md5}",
                details={
                    "stage": "asset_checksum_verification",
                    "url": url,
                    "expected_md5": expected_md5.lower(),
                    "observed_md5": observed_md5,
                    "observed_sha256": sha256.hexdigest(),
                    "size_bytes": size,
                    "response": response_metadata,
                },
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


def _write_fai_from_plain_fasta(fasta_path: Path, fai_path: Path) -> int:
    """Write a standard FAI using uncompressed FASTA byte offsets."""
    entries: list[tuple[str, int, int, int, int]] = []
    with fasta_path.open("rb") as handle:
        name: str | None = None
        length = 0
        offset = 0
        line_bases = 0
        line_width = 0
        previous_bases: int | None = None
        previous_width: int | None = None
        for raw_line in handle:
            if raw_line.startswith(b">"):
                if name is not None:
                    if length <= 0:
                        raise AcquisitionError(f"Reference contig {name!r} has no sequence.")
                    entries.append((name, length, offset, line_bases, line_width))
                header = raw_line[1:].strip().split()
                if not header:
                    raise AcquisitionError("Reference contains an empty FASTA sequence identifier.")
                name = header[0].decode("utf-8")
                if any(entry[0] == name for entry in entries):
                    raise AcquisitionError(f"Duplicate reference contig identifier: {name}")
                length = 0
                offset = handle.tell()
                line_bases = 0
                line_width = 0
                previous_bases = None
                previous_width = None
                continue
            if name is None:
                raise AcquisitionError("Reference sequence occurs before first FASTA header.")
            sequence = raw_line.rstrip(b"\r\n")
            if not sequence or any(base in b" \t" for base in sequence):
                raise AcquisitionError(f"Invalid sequence line in reference contig {name!r}.")
            bases = len(sequence)
            width = len(raw_line)
            if line_bases == 0:
                line_bases, line_width = bases, width
            elif previous_bases != line_bases or previous_width != line_width or bases > line_bases:
                raise AcquisitionError(f"Inconsistent FASTA line wrapping in contig {name!r}.")
            previous_bases, previous_width = bases, width
            length += bases
        if name is not None:
            if length <= 0:
                raise AcquisitionError(f"Reference contig {name!r} has no sequence.")
            entries.append((name, length, offset, line_bases, line_width))
    with fai_path.open("x", encoding="utf-8", newline="") as output:
        for entry in entries:
            output.write("\t".join(map(str, entry)) + "\n")
    return len(entries)


def build_bgzf_reference(source_gzip: Path, output_fasta: Path) -> dict[str, Any]:
    """Recompress source FASTA as BGZF and build its paired FAI/GZI."""
    output_fasta.parent.mkdir(parents=True, exist_ok=True)
    if output_fasta.exists():
        raise AcquisitionError(f"Refusing to overwrite derived reference: {output_fasta}")
    fai = Path(str(output_fasta) + ".fai")
    gzi = Path(str(output_fasta) + ".gzi")
    try:
        with tempfile.TemporaryDirectory(prefix="siraloom-reference-build-") as temporary:
            plain = Path(temporary) / "reference.fa"
            try:
                with gzip.open(source_gzip, "rb") as source, plain.open("xb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
            except (OSError, EOFError) as exc:
                raise AcquisitionError("Reference source gzip stream failed integrity/decompression.") from exc
            contig_count = _write_fai_from_plain_fasta(plain, fai)
            if contig_count <= 0:
                raise AcquisitionError("Reference FASTA contains no contigs.")
            with output_fasta.open("xb") as output:
                completed = subprocess.run(
                    ["bgzip", "-@", "2", "-i", "-I", str(gzi), "-c", str(plain)],
                    check=False,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=7200,
                )
                output.flush()
                os.fsync(output.fileno())
            if completed.returncode != 0:
                raise AcquisitionError(f"bgzip failed: {completed.stderr[-2000:]}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        output_fasta.unlink(missing_ok=True)
        fai.unlink(missing_ok=True)
        gzi.unlink(missing_ok=True)
        raise AcquisitionError("Unable to build BGZF reference and matching FAI/GZI.") from exc
    if not output_fasta.is_file() or not fai.is_file() or not gzi.is_file():
        output_fasta.unlink(missing_ok=True)
        fai.unlink(missing_ok=True)
        gzi.unlink(missing_ok=True)
        raise AcquisitionError("BGZF reference publication is incomplete: FASTA, FAI and GZI are all required.")
    return {
        "fasta": {"path": str(output_fasta), "size_bytes": output_fasta.stat().st_size, "sha256": digest_file(output_fasta, "sha256")},
        "fai": {"path": str(fai), "size_bytes": fai.stat().st_size, "sha256": digest_file(fai, "sha256")},
        "gzi": {"path": str(gzi), "size_bytes": gzi.stat().st_size, "sha256": digest_file(gzi, "sha256")},
        "contig_count": contig_count,
        "construction": "gzip source decompressed; bgzip -i generated BGZF and GZI; FAI generated from source FASTA byte geometry",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--build", choices=("GRCh37", "GRCh38"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--provenance-out", type=Path, required=True)
    args = parser.parse_args()
    manifest: dict[str, Any] = {}
    current_stage = "manifest_validation"
    current_asset: str | None = None
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise AcquisitionError("Public asset manifest root must be a JSON object.")
        if manifest.get("schema_version") != "2" or manifest.get("dataset") != "NIST_GIAB_HG001_NISTv4.2.1":
            raise AcquisitionError("Unexpected public asset manifest identity/schema.")
        if args.output_dir.exists() and any(args.output_dir.iterdir()):
            raise AcquisitionError("Asset output directory must be empty; preserve prior run assets.")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        entries = manifest["assets"][args.build]
        if len(entries) != 4:
            raise AcquisitionError(f"{args.build} must declare reference FASTA, truth VCF, TBI and BED.")
        acquired: dict[str, Any] = {}
        current_stage = "asset_download_and_checksum_verification"
        for key, url, expected_md5 in entries:
            current_asset = key
            if key in acquired or not isinstance(expected_md5, str) or len(expected_md5) != 32:
                raise AcquisitionError(f"Invalid or duplicate asset declaration: {key}")
            filename = Path(urllib.parse.urlparse(url).path).name
            if key == "reference_source_fasta":
                filename = f"{args.build}.source.{filename}"
            acquired[key] = download_verified(url, args.output_dir / filename, expected_md5)
        current_asset = None
        current_stage = "reference_package_construction"
        source_fasta = Path(acquired["reference_source_fasta"]["path"])
        reference_name = "GRCh37_hs37d5.bgz" if args.build == "GRCh37" else "GRCh38_no_alt.bgz"
        reference = build_bgzf_reference(source_fasta, args.output_dir / reference_name)
        current_stage = "provenance_publication"
        report = {
            "schema_version": "2",
            "status": "ASSETS_ACQUIRED_AND_CHECKSUM_VERIFIED",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "dataset": manifest["dataset"],
            "sample": manifest["sample"],
            "reference_build": args.build,
            "release": manifest["source_release"],
            "checksum_policy": "Upstream source bytes verified against pinned official MD5; local SHA-256 recorded for every source and derived asset.",
            "assets": acquired,
            "reference_pair": reference,
            "qualification_boundary": (
                "Asset provenance and byte integrity only. The derived BGZF reference preserves source sequence bytes "
                "but requires independent biological/reference-package qualification; this does not qualify a caller, "
                "clinical interpretation, or laboratory intended use."
            ),
        }
        args.provenance_out.parent.mkdir(parents=True, exist_ok=True)
        args.provenance_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "build": args.build, "assets": len(acquired), "provenance": str(args.provenance_out)}, indent=2))
        return 0
    except (AcquisitionError, OSError, KeyError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        failure_path = args.provenance_out.with_name("acquisition-failure.json")
        try:
            write_failure_provenance(
                failure_path,
                build=args.build,
                dataset=manifest.get("dataset") if isinstance(manifest, dict) else None,
                failed_stage=current_stage,
                failed_asset=current_asset,
                error=exc,
            )
        except OSError as write_error:
            print(
                f"Unable to write acquisition failure provenance: {type(write_error).__name__}: {write_error}",
                file=sys.stderr,
            )
        print(f"GIAB asset acquisition failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
