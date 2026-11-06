#!/usr/bin/env python3
"""Capture reproducible context for known HG001 GIAB spanning-deletion records.

This is a diagnostic, not a clinical qualification or a policy change. It runs
the current production strict validator against the complete public benchmark
VCF and records the exact target record, nearby records, overlapping deletion
candidates, genotype-carrier indices, and validator outcome. Sample identifiers are never copied; only the target and
bounded nearby records needed to explain its context are retained.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    _deleted_reference_interval,
    _info_values,
    validate_vcf_strict,
)

TARGETS = {
    "GRCh37": {"contig": "3", "position": 30_804_994},
    "GRCh38": {"contig": "chr3", "position": 30_763_502},
}
WINDOW = 10_000
MAX_NEARBY_RECORDS = 100


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_text(path: Path) -> TextIO:
    if path.suffix.lower() in {".gz", ".bgz"}:
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("rt", encoding="utf-8", newline="")


def _carrier_indexes(fields: list[str], format_keys: list[str], allele_index: int) -> list[int] | None:
    if len(fields) <= 9 or "GT" not in format_keys:
        return None
    gt_index = format_keys.index("GT")
    carriers: list[int] = []
    for sample_index, sample in enumerate(fields[9:]):
        values = sample.split(":")
        if gt_index >= len(values):
            continue
        genotype = values[gt_index]
        if genotype in {"", "."}:
            continue
        try:
            alleles = {int(token) for token in re.split(r"[/|]", genotype) if token not in {"", "."}}
        except ValueError:
            continue
        if allele_index in alleles:
            carriers.append(sample_index)
    return carriers


def _record_summary(
    fields: list[str], line_number: int, format_keys: list[str], sample_count: int
) -> dict[str, Any]:
    genotype_values: list[dict[str, Any]] = []
    if len(fields) > 9 and "GT" in format_keys:
        gt_index = format_keys.index("GT")
        for sample_index, sample in enumerate(fields[9:]):
            values = sample.split(":")
            if gt_index < len(values):
                genotype_values.append({"sample_index": sample_index, "GT": values[gt_index]})
    return {
        "line_number": line_number,
        "contig": fields[0],
        "position": int(fields[1]),
        "id": fields[2],
        "ref": fields[3],
        "alt": fields[4],
        "filter": fields[6],
        "info": fields[7],
        "format": fields[8] if len(fields) > 8 else None,
        "sample_count": sample_count,
        "genotypes": genotype_values,
    }


def collect_context(vcf_path: Path, reference_build: str) -> dict[str, Any]:
    target = TARGETS[reference_build]
    target_contig = target["contig"]
    target_position = target["position"]
    target_record: dict[str, Any] | None = None
    sample_count = 0
    fileformat: str | None = None
    nearby: list[tuple[int, dict[str, Any]]] = []
    deletion_candidates: list[dict[str, Any]] = []
    deletion_candidate_carriers: list[list[int] | None] = []
    star_carriers: list[int] | None = None
    star_allele_index: int | None = None

    with _open_text(vcf_path) as handle:
        for line_number, raw in enumerate(handle, start=1):
            if raw.startswith("##fileformat="):
                fileformat = raw.rstrip("\r\n").split("=", 1)[1]
                continue
            if raw.startswith("#CHROM"):
                header = raw.rstrip("\r\n").split("\t")
                sample_count = max(0, len(header) - 9)
                continue
            if raw.startswith("#"):
                continue
            fields = raw.rstrip("\r\n").split("\t")
            if len(fields) < 8 or fields[0] != target_contig:
                continue
            try:
                position = int(fields[1])
            except ValueError:
                continue
            alts = fields[4].split(",")
            format_keys = fields[8].split(":") if len(fields) > 8 else []

            if position == target_position and "*" in alts:
                star_allele_index = alts.index("*") + 1
                star_carriers = _carrier_indexes(fields, format_keys, star_allele_index)
                target_record = _record_summary(fields, line_number, format_keys, sample_count)

            if abs(position - target_position) <= WINDOW:
                nearby.append(
                    (abs(position - target_position),
                     _record_summary(fields, line_number, format_keys, sample_count))
                )

            for allele_index, alt in enumerate(alts, start=1):
                interval: tuple[int, int] | None = None
                if re.fullmatch(r"[ACGTNacgtn]+", alt):
                    interval = _deleted_reference_interval(position, fields[3].upper(), alt.upper())
                elif alt == "<DEL>":
                    end_value = _info_values(fields[7]).get("END")
                    if end_value is not None:
                        end = int(end_value)
                        if end > position:
                            interval = (position + 1, end)
                if interval is not None and interval[0] <= target_position <= interval[1]:
                    deletion_candidates.append(
                        _record_summary(fields, line_number, format_keys, sample_count)
                    )
                    deletion_candidate_carriers.append(
                        _carrier_indexes(fields, format_keys, allele_index)
                    )

    if target_record is None:
        raise RuntimeError(
            f"Expected spanning-deletion record {target_contig}:{target_position} was not found"
        )

    carrier_matches: list[bool | None] = []
    for candidate_carriers in deletion_candidate_carriers:
        if star_carriers is None or candidate_carriers is None:
            carrier_matches.append(None)
        else:
            carrier_matches.append(bool(set(star_carriers) & set(candidate_carriers)))

    nearby.sort(key=lambda item: (item[0], item[1]["position"], item[1]["line_number"]))
    return {
        "reference_build": reference_build,
        "target": {"contig": target_contig, "position": target_position},
        "sample_count": sample_count,
        "fileformat": fileformat,
        "target_record": target_record,
        "target_star_allele_index": star_allele_index,
        "target_star_carrier_sample_indexes": star_carriers,
        "nearby_window_bp": WINDOW,
        "nearby_record_count": len(nearby),
        "nearby_records_nearest_first": [record for _, record in nearby[:MAX_NEARBY_RECORDS]],
        "overlapping_deletion_candidate_count": len(deletion_candidates),
        "overlapping_deletion_candidates": deletion_candidates,
        "candidate_carrier_matches": carrier_matches,
        "same_sample_deletion_context_found": any(match is True for match in carrier_matches),
        "same_sample_deletion_context_indeterminate": any(
            match is None for match in carrier_matches
        ) or star_carriers is None,
    }


def diagnose(vcf_path: Path, reference_build: str, expected_md5: str) -> dict[str, Any]:
    observed_md5 = md5_file(vcf_path)
    if observed_md5.lower() != expected_md5.lower():
        raise RuntimeError(
            f"Official MD5 mismatch: expected {expected_md5.lower()}, observed {observed_md5.lower()}"
        )
    context = collect_context(vcf_path, reference_build)
    try:
        profile = validate_vcf_strict(vcf_path)
        validation = {
            "status": "ACCEPTED",
            "profile_records": profile["records"],
            "error_code": None,
            "error": None,
        }
    except StrictVCFValidationError as exc:
        validation = {
            "status": "REJECTED",
            "profile_records": None,
            "error_code": exc.code,
            "error": str(exc),
        }
    return {
        "schema_version": "1",
        "diagnostic_status": "COMPLETE",
        "created_at": datetime.now(UTC).isoformat(),
        "asset": {
            "filename": vcf_path.name,
            "size_bytes": vcf_path.stat().st_size,
            "official_md5": expected_md5.lower(),
            "observed_md5": observed_md5.lower(),
            "sha256": sha256_file(vcf_path),
        },
        "context": context,
        "production_validator": validation,
        "interpretation": (
            "Diagnostic evidence only. A validator rejection is not silently accepted, "
            "and this report does not qualify a clinical assay or authorize clinical use."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vcf", required=True, type=Path)
    parser.add_argument("--reference-build", required=True, choices=sorted(TARGETS))
    parser.add_argument("--expected-md5", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = diagnose(args.vcf, args.reference_build, args.expected_md5)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")

    validation = report["production_validator"]
    print(json.dumps({
        "reference_build": args.reference_build,
        "diagnostic_status": report["diagnostic_status"],
        "validator_status": validation["status"],
        "validator_error_code": validation["error_code"],
        "overlapping_deletion_candidate_count": report["context"]["overlapping_deletion_candidate_count"],
        "same_sample_deletion_context_found": report["context"]["same_sample_deletion_context_found"],
        "evidence": str(args.output),
        "context": report["context"],
        "production_validator": validation,
    }, sort_keys=True))
    if validation["status"] == "REJECTED" and validation["error_code"] != "VCF_SPANNING_DELETION_CONTEXT_MISSING":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
