#!/usr/bin/env python3
"""Exercise SIRALOOM's VCF stage with public, caller-produced HG002 callsets.

The full source VCF is downloaded and strictly validated. A chr20 projection
retains original record text and caller header semantics while reducing the
reference-aware routing/normalization exercise to one canonical contig.
No clinical classification or caller analytical qualification is attempted.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

from backend.app.domain.vcf_caller_profiles import inspect_caller_provenance
from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools, route_vcf_records
from backend.app.domain.vcf_validation import (
    validate_vcf_reference_alleles,
    validate_vcf_strict,
)

ZENODO_API = "https://zenodo.org/api/records"
DRAGEN_RECORD = "8350256"
CALLSET_RECORD = "10428664"
DRAGEN_KEY = "HG002_35x.hard-filtered.vcf.gz"
REFERENCE_ACCESSION = "NC_000020.11"
REFERENCE_LENGTH = 64_444_167
REFERENCE_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    f"?db=nuccore&id={REFERENCE_ACCESSION}&rettype=fasta&retmode=text"
)
EXPECTED_PROFILES = {
    "GATK_HAPLOTYPECALLER": "gatk_haplotypecaller",
    "DEEPVARIANT": "deepvariant_germline",
    "DRAGEN": "dragen_snv_germline",
}


def request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "SIRALOOM-real-vcf-validation/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def record_files(record_id: str) -> list[dict[str, Any]]:
    payload = request_json(f"{ZENODO_API}/{record_id}")
    files = payload.get("files", [])
    if isinstance(files, dict):
        files = files.get("entries", [])
    if not isinstance(files, list):
        raise TypeError(f"Unexpected Zenodo file listing for record {record_id}")
    return files


def select_callset(files: list[dict[str, Any]], caller: str) -> dict[str, Any]:
    candidates = []
    for item in files:
        key = str(item.get("key", ""))
        upper = key.upper()
        if "HG002" not in upper or not upper.endswith((".VCF.GZ", ".VCF.BGZ")):
            continue
        if any(token in upper for token in ("GVCF", "SV.", ".SV", "CNV", "REPEAT", "STR")):
            continue
        if (caller == "GATK" and "GATK" in upper) or (caller == "DEEPVARIANT" and (
            "DEEPVARIANT" in upper or re.search(r"(?:^|[_.-])DV(?:[_.-]|$)", upper)
        ) and "GIRAFFE" not in upper):
            candidates.append(item)

    if caller == "DEEPVARIANT" and len(candidates) > 1:
        bwa = [item for item in candidates if "BWA" in str(item.get("key", "")).upper()]
        if bwa:
            candidates = bwa
    if len(candidates) != 1:
        names = [str(item.get("key", "")) for item in candidates]
        available = [
            str(item.get("key", "")) for item in files
            if "HG002" in str(item.get("key", "")).upper()
            and ".VCF" in str(item.get("key", "")).upper()
        ]
        raise RuntimeError(
            f"Could not uniquely select the published HG002 {caller} small-variant VCF "
            f"from Zenodo record {CALLSET_RECORD}; candidates={names}; "
            f"available_HG002_VCFs={available}"
        )
    return candidates[0]


def file_url(item: dict[str, Any], record_id: str) -> str:
    key = quote(str(item.get("key", "")), safe="/")
    if not key:
        raise RuntimeError("Zenodo file metadata has no key")
    return f"https://zenodo.org/records/{record_id}/files/{key}?download=1"


def download(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size:
        if destination.suffix != ".gz":
            return
        try:
            with gzip.open(destination, "rb") as compressed:
                while compressed.read(1024 * 1024):
                    pass
        except (OSError, EOFError):
            destination.unlink(missing_ok=True)
        else:
            return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "SIRALOOM-real-vcf-validation/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size == 0:
            raise RuntimeError(f"Downloaded empty file: {destination}")
        if destination.suffix == ".gz":
            with gzip.open(temporary, "rb") as compressed:
                while compressed.read(1024 * 1024):
                    pass
        temporary.replace(destination)
    except (OSError, EOFError, RuntimeError) as exc:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed integrity checks for {url}: {exc}") from exc


def digest(path: Path, algorithm: str = "sha256") -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def reusable_caller_result(
    previous: dict[str, Any],
    callset: dict[str, Any],
    reference_sha256: str,
    bcftools_version: list[str],
) -> bool:
    """Reuse completed caller output only when every immutable input still matches."""
    if previous.get("caller") != callset.get("caller"):
        return False
    if previous.get("source_sha256") != callset.get("sha256"):
        return False
    if previous.get("whole_file_parser_validation", {}).get("status") != "PASS":
        return False
    if previous.get("chr20_projection", {}).get("strict_validation") != "PASS":
        return False
    if previous.get("reference_validation", {}).get("result") != "PASS":
        return False
    normalization = previous.get("normalization", {})
    if normalization.get("status") != "PASS" or normalization.get("index_exists") is not True:
        return False
    if previous.get("reference_sha256") != reference_sha256:
        return False
    if previous.get("bcftools") != bcftools_version:
        return False
    normalized = Path(str(normalization.get("output", "")))
    if not normalized.is_file() or not Path(str(normalized) + ".csi").is_file():
        return False
    return digest(normalized) == normalization.get("output_sha256")


def dragen_gp_attestation(callset: dict[str, Any], artifact: Path) -> dict[str, Any] | None:
    if callset["caller"] != "DRAGEN":
        return None
    return {
        "schema_version": 1,
        "caller_profile_id": "dragen_snv_germline",
        "caller_release": "4.2",
        "source_record_url": "https://zenodo.org/records/8350256",
        "source_filename": DRAGEN_KEY,
        "source_md5": "388f58faa52a8811fe19b06533d2c3d5",
        "semantic_deviation": "FORMAT/GP_PHRED_SCALE",
        "source_sha256": callset["sha256"],
        "source_artifact_path": callset["local_path"],
        "artifact_sha256": digest(artifact),
    }


def download_callsets(root: Path) -> list[dict[str, Any]]:
    callset_files = record_files(CALLSET_RECORD)
    dragen_files = record_files(DRAGEN_RECORD)
    selected = [
        ("GATK_HAPLOTYPECALLER", select_callset(callset_files, "GATK")),
        ("DEEPVARIANT", select_callset(callset_files, "DEEPVARIANT")),
    ]
    dragen = [item for item in dragen_files if item.get("key") == DRAGEN_KEY]
    if len(dragen) != 1:
        raise RuntimeError(f"Expected exactly one {DRAGEN_KEY} in Zenodo record {DRAGEN_RECORD}")
    selected.append(("DRAGEN", dragen[0]))

    downloaded = []
    for caller, item in selected:
        key = str(item["key"])
        destination = root / f"{caller.lower()}_{Path(key).name}"
        source_url = file_url(item, DRAGEN_RECORD if caller == "DRAGEN" else CALLSET_RECORD)
        print(f"Downloading {caller} callset {key} from {source_url}", flush=True)
        download(source_url, destination)
        expected = str(item.get("checksum") or "")
        algorithm, _, expected_value = expected.partition(":")
        observed = digest(destination, algorithm) if algorithm in {"md5", "sha1", "sha256"} else None
        if expected_value and observed and observed.lower() != expected_value.lower():
            raise RuntimeError(f"Checksum mismatch for {key}: expected {expected}, observed {algorithm}:{observed}")
        downloaded.append({
            "caller": caller,
            "filename": key,
            "download_url": source_url,
            "bytes": destination.stat().st_size,
            "zenodo_checksum": expected or None,
            "verified_source_checksum": bool(expected_value and observed),
            "source_md5": digest(destination, "md5"),
            "sha256": digest(destination, "sha256"),
            "local_path": str(destination),
        })
    return downloaded


def build_chr20_reference(root: Path) -> tuple[Path, int]:
    source_fasta = root / f"{REFERENCE_ACCESSION}.fa"
    sequence = ""
    for attempt in range(2):
        download(REFERENCE_URL, source_fasta)
        try:
            with source_fasta.open("rt", encoding="ascii") as source:
                first = source.readline().strip()
                if not first.startswith(f">{REFERENCE_ACCESSION} "):
                    raise RuntimeError(
                        f"NCBI FASTA did not identify expected RefSeq accession {REFERENCE_ACCESSION}: {first}"
                    )
                sequence = "".join(line.strip() for line in source if line.strip()).upper()
            if len(sequence) != REFERENCE_LENGTH:
                raise RuntimeError(
                    f"RefSeq {REFERENCE_ACCESSION} length mismatch: expected {REFERENCE_LENGTH}, observed {len(sequence)}"
                )
            if set(sequence) - set("ACGTN"):
                raise RuntimeError("NCBI chr20 reference contains unexpected sequence symbols")
            break
        except (OSError, UnicodeError, RuntimeError):
            source_fasta.unlink(missing_ok=True)
            if attempt:
                raise
    fasta = root / "chr20.reference.fa"
    header = ">chr20\n"
    with fasta.open("w", encoding="ascii", newline="\n") as output:
        output.write(header)
        output.write(sequence + "\n")
    offset = len(header.encode("ascii"))
    with Path(str(fasta) + ".fai").open("w", encoding="ascii", newline="\n") as index:
        index.write(f"chr20\t{len(sequence)}\t{offset}\t{len(sequence)}\t{len(sequence) + 1}\n")
    return fasta, len(sequence)


def reference_for_contig(reference: Path, contig: str, root: Path) -> Path:
    if contig == "chr20":
        return reference
    if contig != "20":
        raise RuntimeError(f"Unexpected chromosome-20 contig label: {contig}")
    sequence = "".join(
        line.strip()
        for line in reference.read_text(encoding="ascii").splitlines()
        if line and not line.startswith(">")
    )
    fasta = root / "chr20.20.reference.fa"
    header = ">20\n"
    fasta.write_text(header + sequence + "\n", encoding="ascii")
    offset = len(header.encode("ascii"))
    Path(str(fasta) + ".fai").write_text(
        f"20\t{len(sequence)}\t{offset}\t{len(sequence)}\t{len(sequence) + 1}\n",
        encoding="ascii",
    )
    return fasta


def run(command: list[str], *, stdout_path: Path | None = None) -> str:
    if stdout_path is None:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(
                f"Command failed ({completed.returncode}): {' '.join(command)}\n"
                f"{completed.stderr[-4000:]}"
            )
        return completed.stdout
    with stdout_path.open("w", encoding="utf-8", newline="\n") as output:
        completed = subprocess.run(command, check=False, stdout=output, stderr=subprocess.PIPE, text=True)
    if completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stderr[-4000:]}"
        )
    return completed.stderr or ""


def validate_whole_vcf_with_bcftools(source: Path) -> dict[str, Any]:
    """Parse the complete callset with HTSlib and report its record/sample counts."""
    output = run(["bcftools", "stats", "-s", "-", str(source)])
    summary: dict[str, int] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) >= 4 and fields[0] == "SN" and fields[1] == "0":
            label = fields[2].rstrip(":")
            try:
                summary[label] = int(fields[3])
            except ValueError as exc:
                raise RuntimeError(f"Invalid bcftools stats value for {label}: {fields[3]!r}") from exc
    if "number of records" not in summary or "number of samples" not in summary:
        raise RuntimeError("bcftools stats did not return whole-file record and sample counts")
    if summary["number of records"] < 1 or summary["number of samples"] < 1:
        raise RuntimeError("VCF must contain at least one variant record and one sample")
    return {
        "status": "PASS",
        "method": "BCFTOOLS_STATS_HTSLIB_FULL_FILE_PARSE",
        "records": summary["number of records"],
        "sample_count": summary["number of samples"],
        "summary": summary,
    }


def project_chr20(source: Path, root: Path, reference_length: int) -> tuple[Path, str]:
    header = run(["bcftools", "view", "-h", str(source)])
    contigs = re.findall(r"^##contig=<ID=([^,>]+)", header, flags=re.MULTILINE)
    contig = "chr20" if "chr20" in contigs else "20" if "20" in contigs else None
    if contig is None:
        raise RuntimeError(f"No chr20/20 contig in caller VCF header: {source.name}")
    body_path = root / f"{source.stem}.chr20.records.vcf"
    run(["bcftools", "view", "-t", contig, "-Ov", "-o", str(body_path), str(source)])
    with body_path.open("r", encoding="utf-8") as body:
        record_lines = [line for line in body if line and not line.startswith("#")]
    if not record_lines:
        raise RuntimeError(f"No sample variant records on {contig} in {source.name}")

    subset = root / f"{source.stem}.chr20.vcf"
    header_lines = []
    for line in header.splitlines():
        if line.startswith("##contig=<"):
            match = re.match(r"##contig=<ID=([^,>]+)", line)
            if match and match.group(1) != contig:
                continue
        header_lines.append(line)
    if not any(line.startswith(f"##contig=<ID={contig},") for line in header_lines):
        header_lines.append(f"##contig=<ID={contig},length={reference_length}>")
    with subset.open("w", encoding="utf-8", newline="\n") as output:
        output.write("\n".join(header_lines) + "\n")
        output.writelines(record_lines)
    return subset, contig


def exercise_one(callset: dict[str, Any], reference: Path, reference_length: int, root: Path) -> dict[str, Any]:
    caller = callset["caller"]
    source = Path(callset["local_path"])
    expected_profile = EXPECTED_PROFILES[caller]
    result: dict[str, Any] = {
        "caller": caller,
        "source_file": callset["filename"],
        "source_sha256": callset["sha256"],
        "source_bytes": callset["bytes"],
        "caller_semantic_review_required": caller == "DRAGEN",
    }

    provenance = inspect_caller_provenance(source)
    result["caller_provenance"] = {
        key: provenance.get(key)
        for key in (
            "identity_status", "caller_profile_id", "caller_version", "version_status",
            "profile_match_status", "caller_semantic_compatibility_status",
            "caller_semantic_compatibility_review_required", "release_qualification_status",
            "clinical_qualification_status", "assay_mode_status", "gvcf_handling_status",
        )
    }
    result["expected_profile"] = expected_profile
    result["caller_profile_match"] = provenance.get("caller_profile_id") == expected_profile

    try:
        result["whole_file_parser_validation"] = validate_whole_vcf_with_bcftools(source)
    except (RuntimeError, OSError) as error:
        result["whole_file_parser_validation"] = {"status": "FAIL", "error": str(error)}
        return result

    subset, contig = project_chr20(source, root, reference_length)
    subset_attestation = dragen_gp_attestation(callset, subset)
    region_strict = validate_vcf_strict(subset, caller_attestation=subset_attestation)
    result["chr20_projection"] = {
        "contig": contig,
        "records": region_strict["records"],
        "sample_count": region_strict["sample_count"],
        "strict_validation": "PASS",
        "caller_semantic_attestation": region_strict["caller_semantic_attestation"],
        "caller_semantic_compatibility_review_required": region_strict[
            "caller_semantic_compatibility_review_required"
        ],
    }

    selected_reference = reference_for_contig(reference, contig, root)
    reference_result = validate_vcf_reference_alleles(subset, selected_reference)
    result["reference_validation"] = reference_result

    routed_dir = root / f"{caller.lower()}_routed"
    routed = route_vcf_records(subset, routed_dir, reference_contig_lengths={contig: reference_length})
    result["routing"] = routed
    sequence_path = routed.get("sequence_path")
    if not sequence_path or routed.get("sequence_records", 0) == 0:
        raise RuntimeError(f"No sequence-resolved SNV/indel records were routed for {caller}")

    normalized = root / f"{caller.lower()}.normalized.vcf.gz"
    normalization = normalize_vcf_with_bcftools(
        sequence_path,
        normalized,
        reference_fasta=selected_reference,
        expected_bcftools_version="1.25",
        timeout_seconds=1800,
    )
    normalized_attestation = dragen_gp_attestation(callset, normalized)
    normalized_strict = validate_vcf_strict(normalized, caller_attestation=normalized_attestation)
    result["normalization"] = {
        "status": "PASS",
        "output": str(normalized),
        "output_bytes": normalized.stat().st_size,
        "output_sha256": digest(normalized),
        "index_exists": Path(str(normalized) + ".csi").is_file(),
        "normalized_records": normalized_strict["records"],
        "source_child_reconciliation": normalization.get("source_child_reconciliation"),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=Path("real-caller-vcf-data"))
    parser.add_argument("--report", type=Path, default=Path("real-caller-vcf-report.json"))
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    bcftools_version = run(["bcftools", "--version"]).splitlines()[:2]
    callsets = download_callsets(args.work_dir)
    reference, reference_length = build_chr20_reference(args.work_dir)

    report: dict[str, Any] = {
        "schema_version": 1,
        "scope": "real sample-level germline SNV/indel caller VCF intake, validation, routing, GRCh38 chr20 REF validation, and reference-aware normalization",
        "reference": {
            "source": REFERENCE_URL,
            "accession": REFERENCE_ACCESSION,
            "source_fasta": str(args.work_dir / f"{REFERENCE_ACCESSION}.fa"),
            "source_fasta_sha256": digest(args.work_dir / f"{REFERENCE_ACCESSION}.fa"),
            "contig": "chr20",
            "length": reference_length,
            "fasta_sha256": digest(reference),
            "fai_sha256": digest(Path(str(reference) + ".fai")),
        },
        "bcftools": bcftools_version,
        "datasets": {
            "gatk_deepvariant": f"https://zenodo.org/records/{CALLSET_RECORD}",
            "dragen": f"https://zenodo.org/records/{DRAGEN_RECORD}",
        },
        "callsets": callsets,
        "results": [],
    }

    failures = []
    report["overall"] = "RUNNING"
    prior_report: dict[str, Any] = {}
    if args.report.is_file():
        try:
            candidate = json.loads(args.report.read_text(encoding="utf-8"))
            if (
                candidate.get("schema_version") == report["schema_version"]
                and candidate.get("scope") == report["scope"]
                and candidate.get("reference", {}).get("fasta_sha256") == report["reference"]["fasta_sha256"]
                and candidate.get("bcftools") == report["bcftools"]
            ):
                prior_report = candidate
        except (OSError, json.JSONDecodeError):
            prior_report = {}
    prior_results = {
        result.get("caller"): result
        for result in prior_report.get("results", [])
        if isinstance(result, dict)
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = args.report.with_name(args.report.name + ".part")
    temporary_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary_report.replace(args.report)

    for callset in callsets:
        cached = prior_results.get(callset["caller"])
        if cached:
            cached = {
                **cached,
                "reference_sha256": prior_report["reference"]["fasta_sha256"],
                "bcftools": prior_report["bcftools"],
            }
        if cached and reusable_caller_result(
            cached,
            callset,
            report["reference"]["fasta_sha256"],
            report["bcftools"],
        ):
            result = cached
            print(f"Reusing verified completed result for {callset['caller']}", flush=True)
        else:
            try:
                result = exercise_one(callset, reference, reference_length, args.work_dir)
                result["reference_sha256"] = report["reference"]["fasta_sha256"]
                result["bcftools"] = report["bcftools"]
            except Exception as error:  # noqa: BLE001 - preserve caller-specific failure in the report
                result = {
                    "caller": callset["caller"],
                    "source_file": callset["filename"],
                    "status": "ERROR",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
        report["results"].append(result)
        if not result.get("caller_profile_match"):
            failures.append(f"{callset['caller']}: caller profile identity did not match")
        if (result.get("whole_file_parser_validation") or {}).get("status") != "PASS":
            failures.append(f"{callset['caller']}: whole-file HTSlib VCF parse did not pass")
        if (result.get("chr20_projection") or {}).get("strict_validation") != "PASS":
            failures.append(f"{callset['caller']}: strict chr20 VCF validation did not pass")
        if callset["caller"] == "DRAGEN" and not (result.get("chr20_projection") or {}).get("caller_semantic_compatibility_review_required"):
            failures.append("DRAGEN: GP semantic deviation was not retained as review-required")
        if (result.get("reference_validation") or {}).get("result") not in {"PASS", "PARTIAL"}:
            failures.append(f"{callset['caller']}: selected-reference validation did not pass")
        if (result.get("normalization") or {}).get("status") != "PASS":
            failures.append(f"{callset['caller']}: reference-aware normalization did not pass")
        report["failures"] = list(failures)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary_report = args.report.with_name(args.report.name + ".part")
        temporary_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary_report.replace(args.report)

    report["overall"] = "PASS" if not failures else "FAIL"
    report["failures"] = failures
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
