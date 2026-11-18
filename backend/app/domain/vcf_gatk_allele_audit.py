"""Lossless record partitioning for GATK's extra-strict ALLELES validation."""
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


def partition_vcf_by_alt_observation(path: str | Path, *, output_dir: str | Path) -> dict:
    """Partition records unchanged by whether every ALT occurs in a sample GT.

    Records are not allele-split or otherwise rewritten. The full-strict
    partition is eligible for GATK ALLELES; the exception partition runs every
    other GATK strict check with ALLELES excluded only for those exact records.
    """
    source, outdir = Path(path), Path(output_dir)
    if not source.is_file():
        raise VCFAlleleObservationAuditError(f"VCF input does not exist: {source}")
    outdir.mkdir(parents=True, exist_ok=True)
    strict_path = outdir / "all-alt-observed.vcf"
    exception_path = outdir / "unobserved-alt-records.vcf"
    findings_path = outdir / "unobserved-alt-alleles.jsonl"
    opener = gzip.open if source.name.lower().endswith((".gz", ".bgz")) else open
    version, columns = None, None
    total = strict_count = exception_count = alt_count = unobserved_count = 0
    finding_digest = hashlib.sha256()
    examples = []
    with strict_path.open("w", encoding="utf-8", newline="\n") as strict_out, \
         exception_path.open("w", encoding="utf-8", newline="\n") as exception_out, \
         findings_path.open("w", encoding="utf-8", newline="\n") as findings_out:
        with opener(source, "rt", encoding="utf-8-sig") as handle:
            for line_no, raw in enumerate(handle, 1):
                line = raw.rstrip("\r\n")
                if line.startswith("##fileformat="):
                    version = line.split("=", 1)[1].strip()
                if line.startswith("#CHROM\t"):
                    columns = line.split("\t")
                if line.startswith("#"):
                    strict_out.write(line + "\n")
                    exception_out.write(line + "\n")
                    continue
                if not line:
                    continue
                fields = line.split("\t")
                if len(fields) < 8:
                    raise VCFAlleleObservationAuditError(f"Malformed VCF record at line {line_no}.")
                if columns is not None and len(fields) != len(columns):
                    raise VCFAlleleObservationAuditError(f"Column count mismatch at line {line_no}.")
                total += 1
                alts = [] if fields[4] == "." else fields[4].split(",")
                alt_count += len(alts)
                sample_names = columns[9:] if columns and len(columns) > 9 else []
                fmt = fields[8].split(":") if len(fields) > 8 else []
                gt_i = fmt.index("GT") if "GT" in fmt else None
                observed = set()
                if gt_i is not None:
                    if len(fields) != 9 + len(sample_names):
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
                            if index > len(alts):
                                raise VCFAlleleObservationAuditError(
                                    f"GT allele index {index} exceeds ALT count {len(alts)} at line {line_no}, sample {sample_i}."
                                )
                            if index:
                                observed.add(index)
                absent = [(i, alt) for i, alt in enumerate(alts, 1) if i not in observed]
                if absent:
                    exception_out.write(line + "\n")
                    exception_count += 1
                    for index, alt in absent:
                        item = {
                            "line_number": line_no, "chrom": fields[0], "pos": fields[1],
                            "ref": fields[3], "alt_index": index, "alt": alt,
                            "observed_alt_indexes": sorted(observed),
                            "sample_count": len(sample_names), "format_gt_present": gt_i is not None,
                        }
                        encoded = json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
                        findings_out.write(encoded)
                        finding_digest.update(encoded.encode("utf-8"))
                        unobserved_count += 1
                        if len(examples) < 20:
                            examples.append(item)
                else:
                    strict_out.write(line + "\n")
                    strict_count += 1
    if total != strict_count + exception_count:
        raise VCFAlleleObservationAuditError(
            f"Record partition is unbalanced: source={total}, strict={strict_count}, exception={exception_count}."
        )
    return {
        "status": "PASS" if unobserved_count == 0 else "PASS_WITH_REVIEW_REQUIRED",
        "method": "LOSSLESS_RECORD_PARTITION_BY_ALT_GT_OBSERVATION",
        "source_sha256": _sha256(source),
        "source_record_count": total,
        "all_alt_observed_record_count": strict_count,
        "unobserved_alt_record_count": exception_count,
        "source_alt_allele_count": alt_count,
        "unobserved_alt_allele_count": unobserved_count,
        "partition_reconciliation": {
            "source_records": total,
            "partitioned_records": strict_count + exception_count,
            "delta": total - strict_count - exception_count,
            "balanced": total == strict_count + exception_count,
        },
        "all_alt_observed_path": str(strict_path.resolve()),
        "all_alt_observed_sha256": _sha256(strict_path),
        "unobserved_alt_path": str(exception_path.resolve()),
        "unobserved_alt_sha256": _sha256(exception_path),
        "findings_path": str(findings_path.resolve()),
        "findings_bytes": findings_path.stat().st_size,
        "findings_sha256": finding_digest.hexdigest(),
        "examples": examples,
    }
