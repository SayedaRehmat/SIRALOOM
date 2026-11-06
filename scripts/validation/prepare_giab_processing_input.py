#!/usr/bin/env python3
"""Create a provenance-preserving SNV/INDEL processing derivative from GIAB truth VCF.

Any source record containing ALT='*' is quarantined whole. No ALT is removed
from a multiallelic record and no genotype is rewritten. The exact source line,
line number, record ordinal, and SHA-256 are retained in a restricted JSONL
sidecar so the derivative cannot be mistaken for the complete truth set.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO


class DerivationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_vcf(path: Path) -> TextIO:
    if path.name.lower().endswith((".gz", ".bgz")):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("rt", encoding="utf-8", newline="")


def _new_temp(destination: Path) -> tuple[int, Path]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise DerivationError(f"Refusing to overwrite existing evidence: {destination}")
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.fchmod(fd, 0o600)
    return fd, Path(name)


def derive(source_vcf: Path, output_vcf: Path, excluded_jsonl: Path, provenance_json: Path) -> dict:
    source_vcf = source_vcf.resolve(strict=True)
    if not source_vcf.is_file():
        raise DerivationError("Source VCF must be a regular file.")
    destinations = (output_vcf, excluded_jsonl, provenance_json)
    if len({str(p.resolve()) for p in destinations}) != 3:
        raise DerivationError("Output paths must be distinct.")
    fds: list[int] = []
    fd_provenance: int | None = None
    temps: list[Path] = []
    published: list[Path] = []
    try:
        for destination in destinations:
            fd, temp = _new_temp(destination)
            fds.append(fd)
            temps.append(temp)
        source_hash_before = sha256_file(source_vcf)
        source_records = 0
        eligible_records = 0
        excluded_records = 0
        sample_names: list[str] = []
        header_seen = False
        fd_vcf, fd_excluded, fd_provenance = fds
        fds = []
        with open_vcf(source_vcf) as source, os.fdopen(fd_vcf, "w", encoding="utf-8", newline="") as out_vcf, os.fdopen(fd_excluded, "w", encoding="utf-8", newline="") as out_excluded:
            for line_number, raw in enumerate(source, start=1):
                if raw.startswith("#CHROM"):
                    columns = raw.rstrip("\r\n").split("\t")
                    if len(columns) < 8:
                        raise DerivationError("Malformed #CHROM header: fewer than eight columns.")
                    sample_names = columns[9:]
                    header_seen = True
                    out_vcf.write(raw)
                    continue
                if raw.startswith("#"):
                    out_vcf.write(raw)
                    continue
                if not header_seen:
                    raise DerivationError(f"VCF data encountered before #CHROM header at line {line_number}.")
                fields = raw.rstrip("\r\n").split("\t")
                if len(fields) < 8:
                    raise DerivationError(f"Malformed source VCF record at line {line_number}.")
                source_records += 1
                alts = fields[4].split(",")
                if "*" in alts:
                    excluded_records += 1
                    entry = {
                        "schema_version": "1",
                        "source_line_number": line_number,
                        "source_record_index": source_records,
                        "reason_code": "SPANNING_DELETION_RECORD_QUARANTINED_WHOLE",
                        "chrom": fields[0],
                        "pos": fields[1],
                        "id": fields[2],
                        "ref": fields[3],
                        "alt": fields[4],
                        "format": fields[8] if len(fields) > 8 else None,
                        "sample_count": len(sample_names),
                        "source_record_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                        "raw_source_record": raw.rstrip("\r\n"),
                    }
                    out_excluded.write(json.dumps(entry, sort_keys=True) + "\n")
                    continue
                eligible_records += 1
                out_vcf.write(raw)
            if not header_seen:
                raise DerivationError("Source VCF has no #CHROM header.")
            out_vcf.flush()
            os.fsync(out_vcf.fileno())
            out_excluded.flush()
            os.fsync(out_excluded.fileno())
        if source_hash_before != sha256_file(source_vcf):
            raise DerivationError("Source VCF changed while the derivative was being generated.")
        report = {
            "schema_version": "1",
            "status": "DERIVATIVE_CREATED_REVIEW_REQUIRED",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source": {
                "filename": source_vcf.name,
                "size_bytes": source_vcf.stat().st_size,
                "sha256": source_hash_before,
                "record_count": source_records,
                "sample_count": len(sample_names),
                "selected_sample_identifier_recorded": False,
            },
            "derivative": {
                "filename": output_vcf.name,
                "eligible_record_count": eligible_records,
                "sha256": sha256_file(temps[0]),
                "excluded_sidecar_filename": excluded_jsonl.name,
                "excluded_record_count": excluded_records,
                "excluded_sidecar_sha256": sha256_file(temps[1]),
                "exclusion_policy": "Exclude entire source record if any ALT allele is '*'; do not strip ALT alleles or rewrite GT/FORMAT values.",
            },
            "qualification_boundary": "The derivative is not the complete GIAB truth VCF and is not suitable for GIAB caller concordance. It exists only to exercise independent eligible input-processing paths while retaining every excluded source record and its exact provenance.",
        }
        with os.fdopen(fd_provenance, "w", encoding="utf-8", newline="") as out_report:
            fd_provenance = None
            json.dump(report, out_report, indent=2, sort_keys=True)
            out_report.write("\n")
            out_report.flush()
            os.fsync(out_report.fileno())
        for temp, destination in zip(temps, destinations, strict=True):
            if destination.exists() or destination.is_symlink():
                raise DerivationError(f"Refusing to overwrite existing evidence: {destination}")
            # Hard-link publication is atomic and fails rather than overwriting a
            # destination created concurrently after the preflight check.
            os.link(temp, destination)
            temp.unlink()
            published.append(destination)
        return report
    except Exception:
        for fd in fds + ([fd_provenance] if fd_provenance is not None else []):
            try:
                os.close(fd)
            except OSError:
                pass
        for temp in temps:
            temp.unlink(missing_ok=True)
        # Never leave a partially published three-file evidence set.
        for destination in published:
            destination.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-vcf", required=True, type=Path)
    parser.add_argument("--output-vcf", required=True, type=Path)
    parser.add_argument("--excluded-records", required=True, type=Path)
    parser.add_argument("--provenance-out", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = derive(args.source_vcf, args.output_vcf, args.excluded_records, args.provenance_out)
    except (DerivationError, OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"GIAB derivative preparation failed: {type(exc).__name__}: {exc}")
        return 2
    print(json.dumps({
        "status": result["status"],
        "source_records": result["source"]["record_count"],
        "eligible_records": result["derivative"]["eligible_record_count"],
        "whole_records_quarantined": result["derivative"]["excluded_record_count"],
        "source_sha256": result["source"]["sha256"],
        "derivative_sha256": result["derivative"]["sha256"],
        "excluded_sidecar_sha256": result["derivative"]["excluded_sidecar_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
