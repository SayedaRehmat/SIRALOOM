#!/usr/bin/env python3
"""Diagnose known HG001 orphan-star loci against the paired GIAB confidence BED."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

from backend.app.domain.vcf_validation import _deleted_reference_interval, _info_values

TARGETS = {
    "GRCh37": ("3", 30_804_994),
    "GRCh38": ("chr3", 30_763_502),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix.lower() in {".gz", ".bgz"} else path.open("rt", encoding="utf-8")


def bed_membership(bed_path: Path, contig: str, pos: int, ref_length: int) -> dict:
    # VCF POS is 1-based; BED is 0-based, half-open. Require the complete
    # REF span to be contained in one high-confidence interval for FULL status.
    start0 = pos - 1
    end0 = start0 + ref_length
    overlapping = []
    containing = []
    rows = 0
    with _open(bed_path) as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip() or raw.startswith(("#", "track", "browser")):
                continue
            fields = raw.rstrip("\r\n").split("\t")
            if len(fields) < 3:
                raise ValueError(f"Malformed BED row at line {line_no}")
            if fields[0] != contig:
                continue
            try:
                left, right = int(fields[1]), int(fields[2])
            except ValueError as exc:
                raise ValueError(f"Non-integer BED coordinates at line {line_no}") from exc
            if left < 0 or right <= left:
                raise ValueError(f"Invalid BED interval at line {line_no}")
            rows += 1
            if left < end0 and start0 < right:
                interval = {"start0": left, "end0": right, "line_number": line_no}
                overlapping.append(interval)
                if left <= start0 and end0 <= right:
                    containing.append(interval)
    if containing:
        status = "FULLY_CONTAINED"
    elif overlapping:
        status = "PARTIAL_OVERLAP"
    else:
        status = "OUTSIDE"
    return {
        "status": status,
        "coordinate_convention": "VCF 1-based closed REF span compared with BED 0-based half-open intervals",
        "vcf_ref_span_1based_closed": [pos, pos + ref_length - 1],
        "bed_query_0based_half_open": [start0, end0],
        "matching_contig_interval_count": rows,
        "overlapping_interval_count": len(overlapping),
        "containing_interval_count": len(containing),
        "overlapping_intervals": overlapping[:20],
        "bed_sha256": sha256_file(bed_path),
    }


def _gt_carriers(fields: list[str], allele_index: int) -> list[int] | None:
    if len(fields) <= 9:
        return None
    keys = fields[8].split(":") if fields[8] not in {"", "."} else []
    if "GT" not in keys:
        return None
    gt_index = keys.index("GT")
    result = []
    for sample_index, sample in enumerate(fields[9:]):
        values = sample.split(":")
        if gt_index >= len(values):
            continue
        gt = values[gt_index]
        if gt in {"", "."}:
            continue
        try:
            alleles = {int(token) for token in re.split(r"[/|]", gt) if token not in {"", "."}}
        except ValueError:
            continue
        if allele_index in alleles:
            result.append(sample_index)
    return result


def diagnose(vcf_path: Path, bed_path: Path, build: str) -> dict:
    contig, position = TARGETS[build]
    target = None
    star_carriers = None
    deletion_candidates = []
    symbolic_deletion_candidates = []
    breakend_deletion_evidence = []
    sample_count = 0
    with _open(vcf_path) as handle:
        for line_number, raw in enumerate(handle, 1):
            if raw.startswith("#CHROM"):
                sample_count = max(0, len(raw.rstrip("\r\n").split("\t")) - 9)
                continue
            if raw.startswith("#"):
                continue
            fields = raw.rstrip("\r\n").split("\t")
            if len(fields) < 8 or fields[0] != contig:
                continue
            try:
                pos = int(fields[1])
            except ValueError:
                continue
            alts = fields[4].split(",")
            info = _info_values(fields[7])
            if pos == position and "*" in alts:
                target = {
                    "line_number": line_number,
                    "chrom": fields[0],
                    "pos": pos,
                    "id": fields[2],
                    "ref": fields[3],
                    "alt": fields[4],
                    "format": fields[8] if len(fields) > 8 else None,
                    "genotypes_by_sample_index": [
                        {"sample_index": i, "value": sample}
                        for i, sample in enumerate(fields[9:])
                    ],
                }
                star_carriers = _gt_carriers(fields, alts.index("*") + 1)
            for allele_index, alt in enumerate(alts, 1):
                interval = None
                if re.fullmatch(r"[ACGTNacgtn]+", alt):
                    interval = _deleted_reference_interval(pos, fields[3].upper(), alt.upper())
                if interval and interval[0] <= position <= interval[1]:
                    deletion_candidates.append({
                        "line_number": line_number,
                        "pos": pos,
                        "ref": fields[3],
                        "alt": alt,
                        "deleted_reference_interval_1based_closed": list(interval),
                        "carrier_sample_indexes": _gt_carriers(fields, allele_index),
                    })
                if (
                    info.get("SVTYPE", "").upper() == "DEL"
                    or alt.upper() == "<DEL>"
                ):
                    end = info.get("END")
                    if end is not None:
                        try:
                            end_value = int(end)
                        except ValueError:
                            continue
                        interval = (pos + 1, end_value)
                        if interval[0] <= position <= interval[1]:
                            symbolic_deletion_candidates.append({
                                "line_number": line_number,
                                "pos": pos,
                                "alt": alt,
                                "svtype": info.get("SVTYPE"),
                                "end": end_value,
                                "carrier_sample_indexes": _gt_carriers(fields, allele_index),
                            })
                if abs(pos - position) <= 10_000 and ("[" in alt or "]" in alt):
                    if "MATEID" in info or info.get("SVTYPE", "").upper() == "DEL":
                        breakend_deletion_evidence.append({
                            "line_number": line_number,
                            "pos": pos,
                            "alt": alt,
                            "mateid_present": "MATEID" in info,
                            "svtype": info.get("SVTYPE"),
                            "carrier_sample_indexes": _gt_carriers(fields, allele_index),
                        })
    if target is None:
        raise RuntimeError(f"Expected target star record not found at {contig}:{position}")
    bed = bed_membership(bed_path, contig, position, len(target["ref"]))
    def same_sample(candidate):
        carriers = candidate.get("carrier_sample_indexes")
        return None if carriers is None or star_carriers is None else bool(set(carriers) & set(star_carriers))
    return {
        "schema_version": "1",
        "reference_build": build,
        "sample_count": sample_count,
        "target_record": target,
        "target_star_carrier_sample_indexes": star_carriers,
        "confidence_bed_membership": bed,
        "sequence_deletion_candidates_spanning_target": deletion_candidates,
        "symbolic_deletion_candidates_spanning_target": symbolic_deletion_candidates,
        "same_sample_sequence_candidate_matches": [same_sample(x) for x in deletion_candidates],
        "same_sample_symbolic_candidate_matches": [same_sample(x) for x in symbolic_deletion_candidates],
        "nearby_breakend_deletion_evidence_requires_haplotype_review": breakend_deletion_evidence,
        "interpretation": "This diagnostic reports representation-level evidence only. BED membership does not establish that an individual variant is true. Breakend evidence is not automatically interpreted as a spanning deletion.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vcf", required=True, type=Path)
    parser.add_argument("--bed", required=True, type=Path)
    parser.add_argument("--reference-build", required=True, choices=sorted(TARGETS))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = diagnose(args.vcf, args.bed, args.reference_build)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite diagnostic evidence: {args.output}")
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "reference_build": args.reference_build,
        "target": result["target_record"],
        "bed_status": result["confidence_bed_membership"]["status"],
        "sequence_deletion_candidates": len(result["sequence_deletion_candidates_spanning_target"]),
        "symbolic_deletion_candidates": len(result["symbolic_deletion_candidates_spanning_target"]),
        "breakend_evidence_count": len(result["nearby_breakend_deletion_evidence_requires_haplotype_review"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
