"""Pinned EBI EVA VCF validation-suite execution and evidence capture."""
from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED_VCF_VERSIONS = frozenset({"VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4"})


class EBIValidatorUnavailable(RuntimeError):
    """The pinned EBI validator could not be attested or executed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _declared_fileformat(path: Path) -> str | None:
    opener = gzip.open if path.name.lower().endswith((".gz", ".bgz")) else open
    try:
        with opener(path, "rt", encoding="utf-8-sig") as handle:
            for line in handle:
                if line.startswith("##fileformat="):
                    return line.rstrip("\r\n").split("=", 1)[1].strip()
                if line.startswith("#CHROM"):
                    break
    except (OSError, EOFError, UnicodeError) as exc:
        raise EBIValidatorUnavailable(
            f"Unable to read VCF header before EBI validation: {exc}"
        ) from exc
    return None


def run_ebi_vcf_validator(
    path: str | Path,
    *,
    expected_version: str = "0.10.2",
    profile_id: str = "ebi-vcf-validator-0.10.2-linux-64",
    executable_name: str = "vcf_validator",
    caller_provenance: dict | None = None,
    timeout_seconds: int = 3600,
) -> dict:
    """Run EBI syntax/semantic validation and return immutable run evidence.

    VCF versions outside the EBI 0.10.2 parser set are explicitly NOT_SUPPORTED.
    A missing, mismatched, or non-executable validator blocks intake.
    """
    source = Path(path)
    started_at = datetime.now(timezone.utc).isoformat()
    fileformat = _declared_fileformat(source)
    base = {
        "validator": "EBI_VCF_VALIDATION_SUITE",
        "validator_version_expected": expected_version,
        "validator_profile_id": profile_id,
        "artifact_sha256": _sha256(source),
        "vcf_version": fileformat,
        "caller": (
            (caller_provenance or {}).get("caller_profile_id")
            or (caller_provenance or {}).get("caller")
            or "UNKNOWN"
        ),
        "caller_version": (caller_provenance or {}).get("caller_version"),
        "caller_identity_status": (caller_provenance or {}).get("identity_status", "UNKNOWN"),
        "caller_provenance": caller_provenance or {"identity_status": "UNKNOWN"},
        "started_at": started_at,
        "supported_vcf_versions": sorted(SUPPORTED_VCF_VERSIONS),
    }
    if fileformat not in SUPPORTED_VCF_VERSIONS:
        return {
            **base,
            "status": "NOT_SUPPORTED",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "reason": (
                f"EBI vcf-validator {expected_version} supports VCF 4.1-4.4; "
                f"declared fileformat was {fileformat!r}."
            ),
        }

    executable = shutil.which(executable_name)
    if executable is None:
        raise EBIValidatorUnavailable(
            "Pinned EBI vcf_validator executable is unavailable; VCF intake is blocked."
        )
    executable_path = Path(executable).resolve()
    runtime_env = os.environ.copy()
    ebi_library_dir = str(executable_path.parent.parent / "lib")
    runtime_env["LD_LIBRARY_PATH"] = ebi_library_dir
    try:
        version_result = subprocess.run(
            [str(executable_path), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=runtime_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EBIValidatorUnavailable(
            f"Unable to attest EBI vcf_validator executable: {exc}"
        ) from exc
    version_output = (version_result.stdout or version_result.stderr).strip()
    expected_banner = f"vcf_validator version {expected_version}"
    if version_result.returncode != 0 or expected_banner not in version_output:
        raise EBIValidatorUnavailable(
            "EBI vcf_validator version attestation failed: "
            f"expected {expected_banner!r}, observed {version_output!r}."
        )

    try:
        with tempfile.TemporaryDirectory(prefix="siraloom-ebi-vcf-") as temp_dir:
            report_dir = Path(temp_dir)
            command = [
                str(executable_path),
                "-i", str(source),
                "-l", "warning",
                "-r", "summary,text",
                "-o", str(report_dir),
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=runtime_env,
            )
            report_files = sorted(
                candidate for candidate in report_dir.rglob("*") if candidate.is_file()
            )
            reports = []
            for report in report_files:
                raw = report.read_bytes()
                reports.append({
                    "filename": report.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw),
                    "content": raw.decode("utf-8", errors="replace"),
                })
            finished_at = datetime.now(timezone.utc).isoformat()
            evidence = {
                **base,
                "status": "PASS" if completed.returncode == 0 else "FAIL",
                "finished_at": finished_at,
                "executable_path": str(executable_path),
                "executable_sha256": _sha256(executable_path),
                "version_banner": version_output,
                "command": command,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "reports": reports,
                "report_count": len(reports),
                "runtime_seconds_limit": timeout_seconds,
            }
            if completed.returncode == 0 and not reports:
                evidence["report_warning"] = "EBI validator exited successfully but emitted no report files."
            return evidence
    except subprocess.TimeoutExpired as exc:
        raise EBIValidatorUnavailable(
            f"EBI vcf_validator exceeded its {timeout_seconds}-second execution limit."
        ) from exc
    except OSError as exc:
        raise EBIValidatorUnavailable(
            f"EBI vcf_validator could not complete execution: {exc}"
        ) from exc


def run_ebi_vcf_assembly_checker(
    vcf_path: str | Path,
    reference_fasta: str | Path,
    *,
    source_artifact_sha256: str,
    caller_provenance: dict | None = None,
    expected_version: str = "0.10.2",
    profile_id: str = "ebi-vcf-validator-0.10.2-linux-64",
    executable_name: str = "vcf_assembly_checker",
    timeout_seconds: int = 3600,
) -> dict:
    """Run EBI's independent FASTA REF concordance checker for a defined VCF projection."""
    vcf = Path(vcf_path)
    fasta = Path(reference_fasta)
    fai = Path(str(fasta) + ".fai")
    if not fasta.is_file() or not fai.is_file():
        raise EBIValidatorUnavailable(
            "EBI assembly checking requires the exact reference FASTA and its .fai index."
        )
    if not source_artifact_sha256 or len(source_artifact_sha256) != 64:
        raise ValueError("The source artifact SHA-256 is required for EBI assembly evidence.")

    executable = shutil.which(executable_name)
    if executable is None:
        raise EBIValidatorUnavailable(
            "Pinned EBI vcf_assembly_checker executable is unavailable; reference validation is blocked."
        )
    executable_path = Path(executable).resolve()
    runtime_env = os.environ.copy()
    runtime_env["LD_LIBRARY_PATH"] = str(executable_path.parent.parent / "lib")

    try:
        version_result = subprocess.run(
            [str(executable_path), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=runtime_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EBIValidatorUnavailable(
            f"Unable to attest EBI vcf_assembly_checker executable: {exc}"
        ) from exc
    version_output = (version_result.stdout or version_result.stderr).strip()
    expected_banner = f"vcf-assembly-checker version {expected_version}"
    if version_result.returncode != 0 or expected_banner not in version_output:
        raise EBIValidatorUnavailable(
            "EBI vcf_assembly_checker version attestation failed: "
            f"expected {expected_banner!r}, observed {version_output!r}."
        )

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        with tempfile.TemporaryDirectory(prefix="siraloom-ebi-assembly-") as temp_dir:
            report_dir = Path(temp_dir)
            command = [
                str(executable_path),
                "-i", str(vcf),
                "-f", str(fasta),
                "-r", "summary,text",
                "-o", str(report_dir),
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=runtime_env,
            )
            report_files = sorted(
                candidate for candidate in report_dir.rglob("*") if candidate.is_file()
            )
            reports = []
            for report in report_files:
                raw = report.read_bytes()
                reports.append({
                    "filename": report.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw),
                    "content": raw.decode("utf-8", errors="replace"),
                })
            return {
                "validator": "EBI_VCF_ASSEMBLY_CHECKER",
                "validator_version_expected": expected_version,
                "validator_profile_id": profile_id,
                "version_banner": version_output,
                "executable_path": str(executable_path),
                "executable_sha256": _sha256(executable_path),
                "status": "PASS" if completed.returncode == 0 else "FAIL",
                "exit_code": completed.returncode,
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "source_artifact_sha256": source_artifact_sha256,
                "validation_input_sha256": _sha256(vcf),
                "validation_input_scope": "CHR20_PROJECTION_ONLY",
                "caller": (
                    (caller_provenance or {}).get("caller_profile_id")
                    or (caller_provenance or {}).get("caller")
                    or "UNKNOWN"
                ),
                "caller_version": (caller_provenance or {}).get("caller_version"),
                "caller_identity_status": (caller_provenance or {}).get("identity_status", "UNKNOWN"),
                "caller_provenance": caller_provenance or {"identity_status": "UNKNOWN"},
                "reference_fasta": str(fasta),
                "reference_fasta_sha256": _sha256(fasta),
                "reference_fai_sha256": _sha256(fai),
                "command": command,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "reports": reports,
                "report_count": len(reports),
                "runtime_seconds_limit": timeout_seconds,
            }
    except subprocess.TimeoutExpired as exc:
        raise EBIValidatorUnavailable(
            f"EBI vcf_assembly_checker exceeded its {timeout_seconds}-second execution limit."
        ) from exc
    except OSError as exc:
        raise EBIValidatorUnavailable(
            f"EBI vcf_assembly_checker could not complete execution: {exc}"
        ) from exc
