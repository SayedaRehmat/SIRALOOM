"""Exhaustive record-level audit for GATK's extra-strict ALLELES check."""
from __future__ import annotations
import gzip
import hashlib
import json
import re
from pathlib import Path


class VCFAlleleObservationAuditError(ValueError):
    """GT data cannot safely support the GATK ALLELES policy decision."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_vcf_alt_observation(path: str | Path, *, evidence_path: str | Path) -> dict:
    source, evidence = Path(path), Path(evidence_path)
    if not source.is_file():
        raise VCFAlleleObservationAuditError(f"VCF input does not exist: {source}")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if source.name.lower().endswith((".gz", ".bgz")) else open
    version, samples = None, []
    records = alts_total = unobserved_total = unobserved_records = missing_gt = 0
    finding_digest = hashlib.sha256()
    examples = []
    with evidence.open("w", encoding="utf-8", newline="\n") as out:
        with opener(source, "rt", encoding="utf-8-sig") as handle:
            for line_no, raw in enumerate(handle, 1):
                line = raw.rstrip("\r\n")
                if line.startswith("##fileformat="):
                    version = line.split("=", 1)[1].strip()
                    continue
                if line.startswith("#CHROM\t"):
                    columns = line.split("\t")
                    samples = columns[9:] if len(columns) > 9 else []
                    continue
                if not line or line.startswith("#"):
                    continue
                fields = line.split("\t")
                if len(fields) < 8:
                    raise VCFAlleleObservationAuditError(f"Malformed VCF record at line {line_no}.")
                records += 1
                alt_list = [] if fields[4] == "." else fields[4].split(",")
                alts_total += len(alt_list)
                fmt = fields[8].split(":") if len(fields) > 8 else []
                gt_i = fmt.index("GT") if "GT" in fmt else None
                observed = set()
                if gt_i is None and samples:
                    missing_gt += 1
                if gt_i is not None:
                    if len(fields) != 9 + len(samples):
                        raise VCFAlleleObservationAuditError(f"Sample-column count mismatch at line {line_no}.")
                    for sample_i, sample in enumerate(fields[9:], 1):
                        values = sample.split(":")
                        gt = values[gt_i] if gt_i < len(values) else "."
                        if gt in {"", "."}:
                            continue
                        if version in {"VCFv4.4", "VCFv4.5"} and gt[:1] in {"/", "|"}:
                            gt = gt[1:]
                        tokens = re.split(r"[/|]", gt)
                        if not gt or any(token == "" for token in tokens):
                            raise VCFAlleleObservationAuditError(f"Malformed GT at line {line_no}, sample {sample_i}.")
                        for token in tokens:
                            if token == ".":
                                continue
                            if not token.isdigit():
                                raise VCFAlleleObservationAuditError(f"Non-integer GT allele at line {line_no}, sample {sample_i}.")
                            index = int(token)
                            if index > len(alt_list):
                                raise VCFAlleleObservationAuditError(
                                    f"GT allele index {index} exceeds ALT count {len(alt_list)} at line {line_no}, sample {sample_i}."
                                )
                            if index:
                                observed.add(index)
                absent = [(i, alt) for i, alt in enumerate(alt_list, 1) if i not in observed]
                if absent:
                    unobserved_records += 1
                    for index, alt in absent:
                        item = {
                            "line_number": line_no, "chrom": fields[0], "pos": fields[1],
                            "ref": fields[3], "alt_index": index, "alt": alt,
                            "observed_alt_indexes": sorted(observed),
                            "sample_count": len(samples), "format_gt_present": gt_i is not None,
                        }
                        encoded = json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
                        out.write(encoded)
                        finding_digest.update(encoded.encode("utf-8"))
                        unobserved_total += 1
                        if len(examples) < 20:
                            examples.append(item)
    return {
        "status": "PASS" if unobserved_total == 0 else "PASS_WITH_UNOBSERVED_ALT_ALLELES",
        "method": "STREAMING_RECORD_ALT_VS_ALL_SAMPLE_GT_INDEX_AUDIT",
        "source_sha256": _sha256(source), "source_record_count": records,
        "source_alt_allele_count": alts_total, "sample_count": len(samples),
        "unobserved_alt_allele_count": unobserved_total,
        "records_with_unobserved_alt_alleles": unobserved_records,
        "records_missing_gt": missing_gt, "evidence_path": str(evidence.resolve()),
        "evidence_bytes": evidence.stat().st_size,
        "evidence_sha256": finding_digest.hexdigest(), "examples": examples,
    }
