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
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote
from pathlib import Path
from typing import Any

from backend.app.config import settings
from backend.app.domain.ebi_vcf_validator import (
    assess_ebi_vcf_compatibility,
    run_ebi_vcf_assembly_checker,
    run_ebi_vcf_validator,
)
from backend.app.domain.ingestion import validate_vcf
from backend.app.domain.vcf_caller_profiles import inspect_caller_provenance
from backend.app.domain.vcf_compatibility import create_dragen_v42_event_projection
from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools, route_vcf_records
from backend.app.domain.vcf_validation import (
    validate_vcf_reference_alleles,
    validate_vcf_strict,
)
from backend.app.domain.vcf_gatk_allele_audit import partition_vcf_by_alt_observation

ZENODO_API = "https://zenodo.org/api/records"
DRAGEN_RECORD = "8350256"
CALLSET_RECORD = "10428664"
DRAGEN_KEY = "HG002_35x.hard-filtered.vcf.gz"
REFERENCE_URL = "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes/chr20.fa.gz"
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
        raise RuntimeError(f"Unexpected Zenodo file listing for record {record_id}")
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
        if caller == "GATK" and "GATK" in upper:
            candidates.append(item)
        elif caller == "DEEPVARIANT" and (
            "DEEPVARIANT" in upper or re.search(r"(?:^|[_.-])DV(?:[_.-]|$)", upper)
        ) and "GIRAFFE" not in upper:
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


def download(
    url: str,
    destination: Path,
    *,
    expected_size: int | None = None,
    expected_checksum: str | None = None,
    max_attempts: int = 5,
    timeout: int = 120,
) -> None:
    """Resume interrupted transfers; verify publisher metadata before publishing."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    if expected_size is not None and expected_size <= 0:
        raise ValueError("expected_size must be positive")

    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_name(destination.name + ".part")
    checksum_algorithm = None
    checksum_value = None
    if expected_checksum:
        checksum_algorithm, separator, checksum_value = expected_checksum.partition(":")
        if not separator or checksum_algorithm not in {"md5", "sha1", "sha256"} or not checksum_value:
            raise RuntimeError(f"Unsupported publisher checksum declaration: {expected_checksum}")

    def verify(path: Path) -> None:
        size = path.stat().st_size
        if expected_size is not None and size != expected_size:
            raise RuntimeError(
                f"Download size mismatch for {destination.name}: expected={expected_size}; observed={size}"
            )
        if size == 0:
            raise RuntimeError(f"Downloaded empty file: {destination}")
        if checksum_algorithm:
            observed = digest(path, checksum_algorithm)
            if observed.lower() != str(checksum_value).lower():
                raise RuntimeError(
                    f"Checksum mismatch for {destination.name}: "
                    f"expected={expected_checksum}; observed={checksum_algorithm}:{observed}"
                )

    if destination.is_file():
        try:
            verify(destination)
            return
        except RuntimeError:
            destination.unlink()

    last_error: Exception | None = None
    for attempt in range(max_attempts):
        if part_path.is_file() and expected_size is not None and part_path.stat().st_size == expected_size:
            try:
                verify(part_path)
            except RuntimeError:
                part_path.unlink(missing_ok=True)
                raise
            os.replace(part_path, destination)
            return
        offset = part_path.stat().st_size if part_path.exists() else 0
        headers = {"User-Agent": "SIRALOOM-real-vcf-validation/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.getcode()
                if status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range)
                    if not match or int(match.group(1)) != offset:
                        raise RuntimeError(
                            f"Invalid Content-Range while resuming {destination.name}: {content_range!r}"
                        )
                    if expected_size is not None and match.group(3) != "*" and int(match.group(3)) != expected_size:
                        raise RuntimeError(
                            f"Remote size changed while downloading {destination.name}: "
                            f"expected={expected_size}; content_range={content_range}"
                        )
                    mode = "ab"
                elif status == 200:
                    # The server ignored Range; restart rather than append duplicate bytes.
                    offset = 0
                    mode = "wb"
                else:
                    raise RuntimeError(f"Unexpected HTTP status {status} downloading {destination.name}")

                with part_path.open(mode) as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())

            observed_size = part_path.stat().st_size
            if expected_size is not None and observed_size < expected_size:
                last_error = RuntimeError(
                    f"Incomplete response for {destination.name}: "
                    f"expected={expected_size} bytes; received={observed_size}"
                )
                if attempt + 1 < max_attempts:
                    delay = min(2 ** attempt, 16)
                    print(
                        f"Download incomplete for {destination.name} "
                        f"(attempt {attempt + 1}/{max_attempts}); resuming in {delay}s",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(delay)
                    continue
                break
            try:
                verify(part_path)
            except RuntimeError:
                part_path.unlink(missing_ok=True)
                raise
            os.replace(part_path, destination)
            return
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(
                    f"Non-retryable HTTP {exc.code} downloading {destination.name}: {exc}"
                ) from exc
            if attempt + 1 < max_attempts:
                delay = min(2 ** attempt, 16)
                print(
                    f"Download interrupted for {destination.name} "
                    f"(attempt {attempt + 1}/{max_attempts}); retrying in {delay}s: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(delay)

    raise RuntimeError(
        f"Download failed after {max_attempts} attempts for {destination.name}; "
        f"partial_bytes={part_path.stat().st_size if part_path.exists() else 0}; "
        f"last_error={last_error}"
    ) from last_error


def digest(path: Path, algorithm: str = "sha256") -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def dragen_gp_attestation(callset: dict[str, Any], artifact: Path) -> dict[str, Any] | None:
    if callset["caller"] != "DRAGEN":
        return None

    # The pinned Zenodo fixture is a hard-filtered SNV VCF that declares
    # BOTH DRAGEN_SNV and DRAGEN_TARGETED. DRAGEN 4.2 supports merging targeted
    # calls into the hard-filtered VCF; the output filename therefore does not
    # have to end in .targeted.vcf. We require the source declaration and the
    # correctly typed TARGETED/EVENT/EVENTTYPE header definitions here, then
    # validate every EVENT-bearing record's TARGETED flag in validate_vcf_strict.
    opener = gzip.open if artifact.suffix == ".gz" else open
    header_lines: list[str] = []
    with opener(artifact, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#CHROM"):
                break
            if line.startswith("##"):
                header_lines.append(line.rstrip("\r\n"))
    source_values = {
        line.split("=", 1)[1].strip()
        for line in header_lines
        if line.startswith("##source=") and "=" in line
    }
    definitions = {
        line.split("ID=", 1)[1].split(",", 1)[0]: line
        for line in header_lines
        if line.startswith("##INFO=<ID=") and "ID=" in line
    }
    targeted_filename = ".targeted.vcf" in artifact.name
    targeted_header_valid = (
        "TARGETED" in definitions
        and "Number=0" in definitions["TARGETED"]
        and "Type=Flag" in definitions["TARGETED"]
        and "EVENT" in definitions
        and "Number=A" in definitions["EVENT"]
        and "Type=String" in definitions["EVENT"]
        and "EVENTTYPE" in definitions
        and "Number=A" in definitions["EVENTTYPE"]
        and "Type=String" in definitions["EVENTTYPE"]
    )
    targeted_provenance_verified = (
        {"DRAGEN_SNV", "DRAGEN_TARGETED"}.issubset(source_values)
        and targeted_header_valid
    )

    attestation = {
        "schema_version": 1,
        "status": "VERIFIED_PINNED_PUBLIC_DATASET_FIXTURE",
        "caller_profile_id": "dragen_snv_germline",
        "caller_release": "4.2",
        "source_record_url": "https://zenodo.org/records/8350256",
        "source_filename": DRAGEN_KEY,
        "source_md5": "388f58faa52a8811fe19b06533d2c3d5",
        "spec_semantics": "VCFv4.2_FORMAT_GP_PHRED_SCALED",
        "source_sha256": callset["sha256"],
        "source_artifact_path": callset["local_path"],
        "artifact_sha256": digest(artifact),
        "caller_extension_detected": targeted_provenance_verified,
        "targeted_output_filename_verified": targeted_filename,
        # Record-level proof is deliberately deferred to the strict parser.
        "targeted_records_verified": False,
        "targeted_output_provenance_status": (
            "VERIFIED_BY_SOURCE_HEADER_AND_TARGETED_FIELD_DEFINITIONS"
            if targeted_provenance_verified
            else "NOT_ESTABLISHED_FOR_THIS_ARTIFACT"
        ),
        "output_mode": (
            "DRAGEN_V42_HARD_FILTERED_WITH_TARGETED_MERGE"
            if targeted_provenance_verified and callset.get("filename") == DRAGEN_KEY
            else "DRAGEN_V42_STANDALONE_TARGETED"
            if targeted_provenance_verified and targeted_filename
            else "DRAGEN_V42_OUTPUT_MODE_UNRESOLVED"
        ),
    }
    if targeted_provenance_verified:
        attestation.update({
            "caller_extension": "INFO/EVENT_AND_EVENTTYPE_NUMBER_A",
            "compatibility_profile_id": "dragen-v4.2-targeted-merge-vcf42-compatibility",
        })
    return attestation


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
        expected = str(item.get("checksum") or "")
        expected_size = int(item["size"]) if item.get("size") is not None else None
        download(
            source_url,
            destination,
            expected_size=expected_size,
            expected_checksum=expected or None,
        )
        algorithm, _, expected_value = expected.partition(":")
        observed = digest(destination, algorithm) if algorithm in {"md5", "sha1", "sha256"} else None
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


def write_reference_dictionary(reference: Path, contig: str, sequence: str) -> Path:
    dictionary = reference.with_suffix(".dict")
    sequence_md5 = hashlib.md5(sequence.encode("ascii")).hexdigest()
    dictionary.write_text(
        chr(10).join([
            chr(9).join(["@HD", "VN:1.6", "SO:unsorted"]),
            chr(9).join(["@SQ", f"SN:{contig}", f"LN:{len(sequence)}", f"M5:{sequence_md5}"]),
        ]) + chr(10),
        encoding="ascii",
    )
    return dictionary

def build_chr20_reference(root: Path) -> tuple[Path, int]:
    compressed = root / "chr20.fa.gz"
    download(REFERENCE_URL, compressed)
    with gzip.open(compressed, "rt", encoding="ascii") as source:
        first = source.readline().strip()
        if not first.startswith(">"):
            raise RuntimeError("UCSC chr20 FASTA has no FASTA header")
        sequence = "".join(line.strip() for line in source if line.strip()).upper()
    if not sequence or set(sequence) - set("ACGTN"):
        raise RuntimeError("UCSC chr20 reference sequence is empty or contains unexpected symbols")
    fasta = root / "chr20.reference.fa"
    header = ">chr20\n"
    with fasta.open("w", encoding="ascii", newline="\n") as output:
        output.write(header)
        output.write(sequence + "\n")
    offset = len(header.encode("ascii"))
    with Path(str(fasta) + ".fai").open("w", encoding="ascii", newline="\n") as index:
        index.write(f"chr20\t{len(sequence)}\t{offset}\t{len(sequence)}\t{len(sequence) + 1}\n")
    write_reference_dictionary(fasta, "chr20", sequence)
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
    write_reference_dictionary(fasta, "20", sequence)
    return fasta


def require_gatk(expected_version: str) -> dict[str, Any]:
    executable = shutil.which("gatk")
    if not executable:
        raise RuntimeError("GATK_VALIDATEVARIANTS_UNAVAILABLE")
    version_result = subprocess.run(
        [executable, "--version"], check=False, capture_output=True, text=True, timeout=120
    )
    version_output = "\n".join(
        value for value in (version_result.stdout, version_result.stderr) if value
    )
    match = re.search(r"v?(\d+\.\d+\.\d+\.\d+)", version_output)
    if version_result.returncode != 0 or not match:
        raise RuntimeError(
            f"GATK_VERSION_UNRESOLVED: exit={version_result.returncode}; output={version_output[-2000:]}"
        )
    observed = match.group(1)
    if observed != expected_version:
        raise RuntimeError(
            f"GATK_VERSION_MISMATCH: expected={expected_version}; observed={observed}"
        )
    executable_path = Path(executable).resolve()
    lock_value = os.environ.get("SIRALOOM_GATK_EXPLICIT_LOCK")
    if not lock_value:
        raise RuntimeError("GATK_EXPLICIT_LOCK_REQUIRED")
    lock_path = Path(lock_value).resolve()
    if not lock_path.is_file():
        raise RuntimeError(f"GATK_EXPLICIT_LOCK_MISSING: {lock_path}")
    return {
        "name": "GATK",
        "expected_version": expected_version,
        "observed_version": observed,
        "executable": str(executable_path),
        "executable_sha256": digest(executable_path),
        "version_command": [str(executable_path), "--version"],
        "version_stdout": version_result.stdout,
        "version_stderr": version_result.stderr,
        "version_exit_code": version_result.returncode,
        "explicit_environment_lock": str(lock_path) if lock_path else None,
        "explicit_environment_lock_sha256": digest(lock_path) if lock_path else None,
    }


def run_gatk_validate_variants(
    runtime: dict[str, Any],
    caller: str,
    input_vcf: Path,
    reference: Path,
    root: Path,
    *,
    source_vcf_sha256: str,
    projection: dict[str, Any] | None = None,
    input_scope: str = "CHR20_REFERENCE_RESOLVED_SEQUENCE_RECORDS",
) -> dict[str, Any]:
    """Run GATK on lossless record partitions; exclude ALLELES only per affected records."""
    log_dir = root / f"{caller.lower()}_gatk_validatevariants"
    log_dir.mkdir(parents=True, exist_ok=True)
    partition = partition_vcf_by_alt_observation(
        input_vcf, output_dir=log_dir / "record-partitions"
    )
    if not partition["source_record_count"]:
        raise RuntimeError("GATK validation input contains no records.")
    runs = []
    aggregate_stdout = []
    aggregate_stderr = []
    run_specs = [
        ("ALL_ALT_OBSERVED", Path(partition["all_alt_observed_path"]),
         partition["all_alt_observed_record_count"], []),
        ("UNOBSERVED_ALT_PRESENT", Path(partition["unobserved_alt_path"]),
         partition["unobserved_alt_record_count"], ["ALLELES"]),
    ]
    for label, partition_path, record_count, excluded in run_specs:
        if not record_count:
            runs.append({
                "partition": label, "status": "NOT_RUN_EMPTY_PARTITION",
                "record_count": 0, "validation_types_excluded": excluded,
            })
            continue
        stdout_path = log_dir / f"{label.lower()}.stdout.log"
        stderr_path = log_dir / f"{label.lower()}.stderr.log"
        command = [
            runtime["executable"], "ValidateVariants",
            "-R", str(reference), "-V", str(partition_path),
        ]
        if excluded:
            command.extend(["--validation-type-to-exclude", *excluded])
        started = datetime.now(timezone.utc).isoformat()
        clock = time.monotonic()
        try:
            completed = subprocess.run(
                command, check=False, capture_output=True, text=True, timeout=6 * 60 * 60
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            exit_code = completed.returncode
            error = None
        except Exception as exc:
            stdout, stderr = "", f"{type(exc).__name__}: {exc}"
            exit_code = None
            error = stderr
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        aggregate_stdout.append(f"## {label}\n{stdout}")
        aggregate_stderr.append(f"## {label}\n{stderr}")
        runs.append({
            "partition": label,
            "status": "PASS" if exit_code == 0 else "FAIL",
            "record_count": record_count,
            "input_path": str(partition_path),
            "input_sha256": digest(partition_path),
            "input_bytes": partition_path.stat().st_size,
            "validation_types_excluded": excluded,
            "command": command,
            "started_at": started,
            "elapsed_seconds": round(time.monotonic() - clock, 3),
            "exit_code": exit_code,
            "error": error,
            "stdout_path": str(stdout_path.resolve()),
            "stdout_sha256": digest(stdout_path),
            "stderr_path": str(stderr_path.resolve()),
            "stderr_sha256": digest(stderr_path),
        })
    stdout_path = log_dir / "validatevariants.stdout.log"
    stderr_path = log_dir / "validatevariants.stderr.log"
    stdout_payload = aggregate_stdout[0] if len(aggregate_stdout) == 1 else "\n".join(aggregate_stdout)
    stderr_payload = aggregate_stderr[0] if len(aggregate_stderr) == 1 else "\n".join(aggregate_stderr)
    stdout_path.write_text(stdout_payload, encoding="utf-8")
    stderr_path.write_text(stderr_payload, encoding="utf-8")
    failed = any(item.get("status") == "FAIL" for item in runs)
    review_required = partition["unobserved_alt_record_count"] > 0
    return {
        "status": "FAIL" if failed else ("PASS_WITH_REVIEW_REQUIRED" if review_required else "PASS"),
        "caller": caller,
        "tool": "GATK ValidateVariants",
        "tool_version": runtime["observed_version"],
        "tool_executable_sha256": runtime["executable_sha256"],
        "validation_profile": "GATK_RECORD_PARTITIONED_STRICT_VALIDATION_V1",
        "validation_types_excluded": ["ALLELES"] if review_required else [],
        "validation_policy_reason": (
            "GATK ALLELES remained enabled for every record whose ALT alleles were observed in sample GTs. "
            "Only the lossless partition containing unobserved ALT alleles omitted ALLELES; all other GATK "
            "validation checks ran on both partitions."
        ),
        "review_required": review_required,
        "allele_observation_partition": partition,
        "partition_runs": runs,
        "command": next((item["command"] for item in runs if item.get("command")), []),
        "commands": [item["command"] for item in runs if item.get("command")],
        "exit_code": 1 if failed else 0,
        "input_path": str(input_vcf.resolve()),
        "input_sha256": digest(input_vcf),
        "input_bytes": input_vcf.stat().st_size,
        "source_vcf_sha256": source_vcf_sha256,
        "input_scope": input_scope,
        "reference_fasta": str(reference.resolve()),
        "reference_fasta_sha256": digest(reference),
        "reference_fai_sha256": digest(Path(str(reference) + ".fai")),
        "reference_dictionary": str(reference.with_suffix(".dict")),
        "reference_dictionary_sha256": digest(reference.with_suffix(".dict")),
        "stdout_path": str(stdout_path.resolve()),
        "stdout_sha256": digest(stdout_path),
        "stderr_path": str(stderr_path.resolve()),
        "stderr_sha256": digest(stderr_path),
        "compatibility_projection": projection,
    }


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


def exercise_one(
    callset: dict[str, Any],
    reference: Path,
    reference_length: int,
    root: Path,
    gatk_runtime: dict[str, Any],
) -> dict[str, Any]:
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
        source_attestation = dragen_gp_attestation(callset, source)
        intake_validation = validate_vcf(
            source,
            caller_attestation=source_attestation,
            artifact_sha256=callset["sha256"],
            expected_reference_build="GRCh38",
        )
        result["whole_file_intake_validation"] = {
            "status": intake_validation.status,
            "error_code": intake_validation.error_code,
            "errors": intake_validation.errors,
        }
        result["whole_file_ebi_validation"] = (
            (intake_validation.metadata or {}).get("ebi_vcf_validation")
            or {"status": "MISSING_EBI_VALIDATION_EVIDENCE"}
        )
        intake_metadata = intake_validation.metadata or {}
        ebi_failed_after_siraloom_pass = (
            intake_validation.error_code == "EBI_VCF_VALIDATION_FAILED"
        )
        strict_passed = intake_validation.status == "VALID" or ebi_failed_after_siraloom_pass
        result["whole_file_strict_validation"] = {
            "status": "PASS" if strict_passed else "FAIL",
            "vcf_version": intake_validation.fileformat,
            "records": intake_metadata.get("source_record_count"),
            "sample_count": len(intake_validation.sample_names),
            "alternate_alleles": intake_metadata.get("alternate_allele_count"),
            "multiallelic_records": intake_metadata.get("multiallelic_source_record_count"),
            "symbolic_records": intake_metadata.get("symbolic_source_record_count"),
            "gvcf_markers": intake_metadata.get("gvcf_marker_count"),
            "compression": intake_metadata.get("compression"),
            "caller_semantic_attestation": intake_metadata.get("caller_semantic_attestation"),
            "caller_semantic_compatibility_review_required": intake_metadata.get(
                "caller_semantic_compatibility_review_required"
            ),
            "targeted_record_count": (intake_metadata.get("caller_provenance") or {}).get("targeted_record_count"),
            "targeted_event_record_count": (intake_metadata.get("caller_provenance") or {}).get("targeted_event_record_count"),
            "targeted_eventtype_record_count": (intake_metadata.get("caller_provenance") or {}).get("targeted_eventtype_record_count"),
            "caller_provenance_semantic_status": (
                intake_metadata.get("caller_provenance") or {}
            ).get("caller_semantic_compatibility_status"),
            **(
                {
                    "error_code": intake_validation.error_code,
                    "errors": intake_validation.errors,
                }
                if not strict_passed
                else {}
            ),
        }
        if not strict_passed:
            return result
        semantic_attestation = intake_metadata.get("caller_semantic_attestation")
        if (
            caller == "DRAGEN"
            and intake_metadata.get("caller_semantic_compatibility_review_required")
        ):
            try:
                projection_path = root / "dragen.event-projected.vcf"
                projection = create_dragen_v42_event_projection(
                    source,
                    projection_path,
                    caller_semantic_attestation=semantic_attestation,
                )
                projection_ebi = run_ebi_vcf_validator(
                    projection_path,
                    caller_provenance=provenance,
                    expected_version=settings.ebi_vcf_validator_version,
                    profile_id=settings.ebi_vcf_validator_profile_id,
                    executable_name=settings.ebi_vcf_validator_executable,
                    timeout_seconds=3600,
                )
                projection_assessment = assess_ebi_vcf_compatibility(
                    projection_ebi,
                    caller_semantic_attestation=semantic_attestation,
                )
                projection_ebi["compatibility_assessment"] = projection_assessment
                result["whole_file_ebi_validation"]["compatibility_projection"] = {
                    **projection,
                    "projection_ebi_validation": projection_ebi,
                    "projection_ebi_effective_status": projection_assessment.get(
                        "effective_status", projection_ebi.get("status")
                    ),
                }
            except Exception as projection_error:
                result["whole_file_ebi_validation"]["compatibility_projection"] = {
                    "status": "ERROR",
                    "error_type": type(projection_error).__name__,
                    "error": str(projection_error),
                }
    except Exception as error:
        result["whole_file_intake_validation"] = {
            "status": "ERROR",
            "error_type": type(error).__name__,
            "errors": [str(error)],
        }
        result["whole_file_strict_validation"] = {
            "status": "FAIL",
            "error_type": type(error).__name__,
            "error": str(error),
        }
        return result

    subset, contig = project_chr20(source, root, reference_length)
    subset_attestation = dragen_gp_attestation(callset, subset)
    region_strict = validate_vcf_strict(subset, caller_attestation=subset_attestation)
    result["chr20_projection"] = {
        "contig": contig,
        "records": region_strict["records"],
        "sample_count": region_strict["sample_count"],
        "strict_validation": "PASS",
    }

    selected_reference = reference_for_contig(reference, contig, root)
    reference_result = validate_vcf_reference_alleles(subset, selected_reference)
    result["reference_validation"] = reference_result
    result["ebi_assembly_validation"] = run_ebi_vcf_assembly_checker(
        subset,
        selected_reference,
        source_artifact_sha256=callset["sha256"],
        caller_provenance=provenance,
        expected_version=settings.ebi_vcf_validator_version,
        profile_id=settings.ebi_vcf_validator_profile_id,
        executable_name=settings.ebi_vcf_assembly_checker_executable,
    )

    routed_dir = root / f"{caller.lower()}_routed"
    routed = route_vcf_records(subset, routed_dir, reference_contig_lengths={contig: reference_length})
    result["routing"] = routed
    sequence_path = routed.get("sequence_path")
    if not sequence_path or routed.get("sequence_records", 0) == 0:
        raise RuntimeError(f"No sequence-resolved SNV/indel records were routed for {caller}")

    gatk_input = Path(sequence_path)
    gatk_projection = None
    if (
        caller == "DRAGEN"
        and isinstance(semantic_attestation, dict)
        and semantic_attestation.get("caller_extension_detected") is True
        and semantic_attestation.get("targeted_records_verified") is True
    ):
        gatk_projection_path = root / f"{caller.lower()}.chr20.event-projected.vcf"
        gatk_projection = create_dragen_v42_event_projection(
            gatk_input,
            gatk_projection_path,
            caller_semantic_attestation=semantic_attestation,
        )
        gatk_input = gatk_projection_path
    result["gatk_validate_variants"] = run_gatk_validate_variants(
        gatk_runtime,
        caller,
        gatk_input,
        selected_reference,
        root,
        source_vcf_sha256=callset["sha256"],
        projection=gatk_projection,
    )

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
        "normalization_evidence": normalization,
        "normalization_command": normalization.get("command"),
        "index_validation": normalization.get("index_validation"),
        "reference_identity": normalization.get("reference_identity"),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=Path("real-caller-vcf-data"))
    parser.add_argument("--report", type=Path, default=Path("real-caller-vcf-report.json"))
    parser.add_argument(
        "--gatk-version",
        default=os.environ.get("SIRALOOM_GATK_EXPECTED_VERSION", "4.6.2.0"),
    )
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    bcftools_version = run(["bcftools", "--version"]).splitlines()[:2]
    gatk_runtime = require_gatk(args.gatk_version)
    callsets = download_callsets(args.work_dir)
    reference, reference_length = build_chr20_reference(args.work_dir)

    report: dict[str, Any] = {
        "schema_version": 2,
        "scope": "real sample-level germline SNV/indel caller VCF intake, SIRALOOM and EBI validation, GATK ValidateVariants, routing, GRCh38 chr20 REF validation, and reference-aware normalization",
        "reference": {
            "source": REFERENCE_URL,
            "contig": "chr20",
            "length": reference_length,
            "fasta_sha256": digest(reference),
            "fai_sha256": digest(Path(str(reference) + ".fai")),
            "dictionary": str(reference.with_suffix(".dict")),
            "dictionary_sha256": digest(reference.with_suffix(".dict")),
        },
        "toolchain": {"gatk": gatk_runtime},
        "bcftools": bcftools_version,
        "datasets": {
            "gatk_deepvariant": f"https://zenodo.org/records/{CALLSET_RECORD}",
            "dragen": f"https://zenodo.org/records/{DRAGEN_RECORD}",
        },
        "callsets": callsets,
        "results": [],
    }

    failures = []
    for callset in callsets:
        try:
            result = exercise_one(callset, reference, reference_length, args.work_dir, gatk_runtime)
        except Exception as error:
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
        if (result.get("whole_file_intake_validation") or {}).get("status") != "VALID":
            failures.append(f"{callset['caller']}: production-path intake validation did not pass")
        ebi_effective_status = (
            (result.get("whole_file_ebi_validation") or {})
            .get("compatibility_assessment", {})
            .get("effective_status")
            or (result.get("whole_file_ebi_validation") or {}).get("status")
        )
        if ebi_effective_status not in {"PASS", "PASS_WITH_DOCUMENTED_COMPATIBILITY_EXCEPTIONS", "PASS_WITH_REVIEW_REQUIRED"}:
            failures.append(f"{callset['caller']}: EBI whole-file validation has blocking diagnostics")
        if (result.get("whole_file_strict_validation") or {}).get("status") != "PASS":
            failures.append(f"{callset['caller']}: whole-file strict VCF validation did not pass")
        if (result.get("ebi_assembly_validation") or {}).get("status") != "PASS":
            failures.append(f"{callset['caller']}: EBI chr20 assembly validation did not pass")
        if callset["caller"] == "DRAGEN" and not (result.get("whole_file_strict_validation") or {}).get("caller_semantic_compatibility_review_required"):
            failures.append("DRAGEN: documented VCFv4.2 EVENT/EVENTTYPE caller extension was not retained as review-required")
        if callset["caller"] == "DRAGEN":
            projection_evidence = (
                result.get("whole_file_ebi_validation") or {}
            ).get("compatibility_projection") or {}
            projection_status = projection_evidence.get("projection_ebi_effective_status")
            if projection_status not in {
                "PASS", "PASS_WITH_DOCUMENTED_COMPATIBILITY_EXCEPTIONS"
            }:
                failures.append("DRAGEN: EBI validation did not pass on the lossless EVENT compatibility projection")
        if (result.get("reference_validation") or {}).get("result") not in {"PASS", "PARTIAL"}:
            failures.append(f"{callset['caller']}: selected-reference validation did not pass")
        gatk_status = (result.get("gatk_validate_variants") or {}).get("status")
        if gatk_status not in {"PASS", "PASS_WITH_REVIEW_REQUIRED"}:
            failures.append(f"{callset['caller']}: GATK ValidateVariants did not pass on reference-resolved chr20 records")
        if (result.get("normalization") or {}).get("status") != "PASS":
            failures.append(f"{callset['caller']}: reference-aware normalization did not pass")

    review_required_callers = sorted({
        result.get("caller")
        for result in report["results"]
        if (
            (result.get("whole_file_strict_validation") or {}).get("caller_semantic_compatibility_review_required")
            or (result.get("whole_file_ebi_validation") or {}).get("compatibility_assessment", {}).get("effective_status") == "PASS_WITH_REVIEW_REQUIRED"
            or (result.get("gatk_validate_variants") or {}).get("review_required") is True
        )
    })
    report["review_required_callers"] = review_required_callers
    report["overall"] = (
        "FAIL" if failures else "PASS_WITH_REVIEW_REQUIRED" if review_required_callers else "PASS"
    )
    report["failures"] = failures
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
