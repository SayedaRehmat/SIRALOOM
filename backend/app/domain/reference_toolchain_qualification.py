"""Reference-backed execution checks for the governed BCFtools toolchain.

This module runs BCFtools against the exact FASTA being qualified. It verifies
a valid SNV and a left-normalized small insertion, then proves that an
intentionally incorrect REF allele is rejected.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_token(value: str) -> str | None:
    match = re.search(r"\\b(\\d+\\.\\d+(?:\\.\\d+)?)\\b", value)
    return match.group(1) if match else None


def _run(command: list[str], *, timeout: int = 180) -> dict[str, Any]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def _parse_fasta_output(value: str) -> str:
    return "".join(
        line.strip()
        for line in value.splitlines()
        if line and not line.startswith(">")
    ).upper()


def _find_indel_test_sequence(sequence: str) -> tuple[int, int, int] | None:
    """Return (run_start, run_end_exclusive, snv_index) for a safe fixture."""
    canonical = frozenset("ACGT")
    index = 1
    while index < len(sequence) - 1:
        base = sequence[index]
        if base not in canonical or sequence[index - 1] != base or sequence[index + 1] != base:
            index += 1
            continue
        start = index - 1
        while start > 0 and sequence[start - 1] == base:
            start -= 1
        end = index + 2
        while end < len(sequence) and sequence[end] == base:
            end += 1
        if end - start >= 3 and end < len(sequence):
            snv_index = next(
                (
                    candidate
                    for candidate, observed in enumerate(sequence)
                    if observed in canonical and not start <= candidate < end
                ),
                None,
            )
            if snv_index is not None:
                return start, end, snv_index
        index = max(index + 1, end)
    return None


def _write_vcf(path: Path, contig: str, contig_length: int, records: list[tuple[int, str, str]]) -> None:
    lines = [
        "##fileformat=VCFv4.2",
        f"##contig=<ID={contig},length={contig_length}>",
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO",
    ]
    for position, ref, alt in sorted(records, key=lambda item: item[0]):
        lines.append(
            f"{contig}\\t{position}\\t.\\t{ref}\\t{alt}\\t.\\tPASS\\t."
        )
    path.write_text("\\n".join(lines) + "\\n", encoding="ascii")


def execute_bcftools_reference_check(
    fasta_path: str | Path,
    contigs: list[dict[str, Any]],
    *,
    expected_fasta_sha256: str,
    expected_bcftools_version: str,
    expected_samtools_version: str | None = None,
) -> dict[str, Any]:
    """Execute known-answer normalization and REF-rejection checks on a FASTA.

    The returned evidence is suitable for persistence in ResourceQualification.
    A missing executable, version mismatch, failed normalization, absent
    left-alignment, or accepted incorrect REF allele produces BLOCKED evidence.
    """
    fasta = Path(fasta_path)
    evidence: dict[str, Any] = {
        "status": "BLOCKED",
        "tool": "bcftools norm",
        "reference_fasta": str(fasta.resolve()),
        "expected_reference_fasta_sha256": expected_fasta_sha256,
        "tests": {},
    }
    try:
        if not fasta.is_file():
            evidence["error"] = "qualified reference FASTA is missing"
            return evidence
        observed_fasta_sha256 = _sha256(fasta)
        evidence["reference_fasta_sha256"] = observed_fasta_sha256
        if observed_fasta_sha256 != str(expected_fasta_sha256).lower():
            evidence["error"] = "reference FASTA SHA-256 changed before BCFtools execution"
            return evidence

        bcftools = shutil.which("bcftools")
        samtools = shutil.which("samtools")
        if not bcftools:
            evidence["error"] = "bcftools executable is not available on PATH"
            return evidence
        if not samtools:
            evidence["error"] = "samtools executable is not available on PATH for reference fixture extraction"
            return evidence
        evidence["bcftools_executable"] = str(Path(bcftools).resolve())
        evidence["samtools_executable"] = str(Path(samtools).resolve())

        bcftools_version_result = _run([bcftools, "--version"], timeout=30)
        samtools_version_result = _run([samtools, "--version"], timeout=30)
        if bcftools_version_result["returncode"] != 0:
            evidence["error"] = "bcftools --version failed"
            evidence["bcftools_version_check"] = bcftools_version_result
            return evidence
        if samtools_version_result["returncode"] != 0:
            evidence["error"] = "samtools --version failed"
            evidence["samtools_version_check"] = samtools_version_result
            return evidence

        observed_bcftools_version = str(bcftools_version_result["stdout"]).splitlines()[0].strip()
        observed_samtools_version = str(samtools_version_result["stdout"]).splitlines()[0].strip()
        evidence["bcftools_version"] = observed_bcftools_version
        evidence["samtools_version"] = observed_samtools_version
        expected_bcftools_token = _version_token(expected_bcftools_version)
        observed_bcftools_token = _version_token(observed_bcftools_version)
        evidence["bcftools_version_match"] = bool(
            expected_bcftools_token
            and observed_bcftools_token
            and expected_bcftools_token == observed_bcftools_token
        )
        if not evidence["bcftools_version_match"]:
            evidence["error"] = (
                f"bcftools version mismatch: expected {expected_bcftools_version!r}, "
                f"observed {observed_bcftools_version!r}"
            )
            return evidence
        if expected_samtools_version:
            expected_samtools_token = _version_token(expected_samtools_version)
            observed_samtools_token = _version_token(observed_samtools_version)
            evidence["samtools_version_match"] = bool(
                expected_samtools_token
                and observed_samtools_token
                and expected_samtools_token == observed_samtools_token
            )
            if not evidence["samtools_version_match"]:
                evidence["error"] = (
                    f"samtools version mismatch: expected {expected_samtools_version!r}, "
                    f"observed {observed_samtools_version!r}"
                )
                return evidence

        selected: tuple[str, int, str, int, int, int] | None = None
        sequence_query_attempts: list[dict[str, Any]] = []
        for item in contigs:
            contig = str(item.get("name") or "")
            contig_length = int(item.get("length") or 0)
            if not contig or contig_length < 5:
                continue
            query_end = min(contig_length, 100000)
            query = _run(
                [samtools, "faidx", str(fasta), f"{contig}:1-{query_end}"],
                timeout=120,
            )
            sequence_query_attempts.append({
                "contig": contig,
                "region": f"{contig}:1-{query_end}",
                "returncode": query["returncode"],
                "stderr": query["stderr"],
            })
            if query["returncode"] != 0:
                continue
            sequence = _parse_fasta_output(query["stdout"])
            fixture = _find_indel_test_sequence(sequence)
            if fixture is None:
                continue
            run_start, run_end, snv_index = fixture
            selected = (contig, contig_length, sequence, run_start, run_end, snv_index)
            break
        evidence["reference_sequence_queries"] = sequence_query_attempts
        if selected is None:
            evidence["error"] = (
                "could not find a reference window with a canonical homopolymer run "
                "and an independent canonical SNV position"
            )
            return evidence

        contig, contig_length, sequence, run_start, run_end, snv_index = selected
        snv_ref = sequence[snv_index]
        snv_alt = next(base for base in "ACGT" if base != snv_ref)
        snv_position = snv_index + 1

        insertion_base = sequence[run_start]
        insertion_anchor_index = run_start + 1
        insertion_position = insertion_anchor_index + 1
        insertion_ref = sequence[insertion_anchor_index]
        insertion_alt = insertion_ref + insertion_base

        evidence["fixture"] = {
            "contig": contig,
            "contig_length": contig_length,
            "sequence_window_start": 1,
            "sequence_window_length": len(sequence),
            "snv": {
                "position": snv_position,
                "ref": snv_ref,
                "alt": snv_alt,
            },
            "small_insertion": {
                "input_position": insertion_position,
                "ref": insertion_ref,
                "alt": insertion_alt,
                "homopolymer_base": insertion_base,
                "homopolymer_start_1based": run_start + 1,
                "homopolymer_end_1based": run_end,
            },
        }

        with tempfile.TemporaryDirectory(prefix="siraloom-bcftools-reference-check-") as temporary:
            root = Path(temporary)
            valid_input = root / "valid-snvs-indels.vcf"
            valid_output = root / "normalized.vcf"
            valid_records = [
                (snv_position, snv_ref, snv_alt),
                (insertion_position, insertion_ref, insertion_alt),
            ]
            _write_vcf(valid_input, contig, contig_length, valid_records)
            valid_command = [
                bcftools, "norm", "-f", str(fasta), "-c", "e",
                "-m", "-any", "-Ov", "-o", str(valid_output), str(valid_input),
            ]
            valid_result = _run(valid_command)
            output_records: list[list[str]] = []
            if valid_result["returncode"] == 0 and valid_output.is_file():
                output_records = [
                    line.split("\\t")
                    for line in valid_output.read_text(encoding="utf-8").splitlines()
                    if line and not line.startswith("#")
                ]
            normalized_snv = next(
                (
                    record for record in output_records
                    if len(record) >= 5
                    and int(record[1]) == snv_position
                    and record[3] == snv_ref
                    and record[4] == snv_alt
                ),
                None,
            )
            normalized_indel = next(
                (
                    record for record in output_records
                    if len(record) >= 5
                    and len(record[4]) > len(record[3])
                ),
                None,
            )
            snv_passed = valid_result["returncode"] == 0 and normalized_snv is not None
            indel_left_aligned = bool(
                valid_result["returncode"] == 0
                and normalized_indel is not None
                and int(normalized_indel[1]) < insertion_position
            )
            evidence["tests"]["valid_snv"] = {
                "status": "PASS" if snv_passed else "FAIL",
                "command": valid_command,
                "returncode": valid_result["returncode"],
                "record": normalized_snv,
                "stderr": valid_result["stderr"],
            }
            evidence["tests"]["valid_small_indel"] = {
                "status": "PASS" if indel_left_aligned else "FAIL",
                "command": valid_command,
                "returncode": valid_result["returncode"],
                "input_position": insertion_position,
                "normalized_position": int(normalized_indel[1]) if normalized_indel else None,
                "left_aligned": indel_left_aligned,
                "record": normalized_indel,
                "stderr": valid_result["stderr"],
            }

            wrong_ref = next(base for base in "ACGT" if base != snv_ref)
            invalid_input = root / "incorrect-ref.vcf"
            invalid_output = root / "incorrect-ref-normalized.vcf"
            _write_vcf(
                invalid_input,
                contig,
                contig_length,
                [(snv_position, wrong_ref, snv_ref)],
            )
            invalid_command = [
                bcftools, "norm", "-f", str(fasta), "-c", "e",
                "-Ov", "-o", str(invalid_output), str(invalid_input),
            ]
            invalid_result = _run(invalid_command)
            error_text = str(invalid_result["stderr"]).lower()
            ref_mismatch_reported = (
                invalid_result["returncode"] != 0
                and "mismatch" in error_text
                and ("ref" in error_text or "reference" in error_text)
            )
            evidence["tests"]["incorrect_ref_rejected"] = {
                "status": "PASS" if ref_mismatch_reported else "FAIL",
                "command": invalid_command,
                "returncode": invalid_result["returncode"],
                "rejected": invalid_result["returncode"] != 0,
                "reference_mismatch_reported": ref_mismatch_reported,
                "stderr": invalid_result["stderr"],
            }

        all_passed = all(
            evidence["tests"][name]["status"] == "PASS"
            for name in ("valid_snv", "valid_small_indel", "incorrect_ref_rejected")
        )
        evidence["status"] = "VERIFIED" if all_passed else "BLOCKED"
        if not all_passed:
            evidence["error"] = "one or more reference-backed BCFtools normalization checks failed"
        return evidence
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, StopIteration) as exc:
        evidence["error"] = str(exc)[:2000]
        return evidence
