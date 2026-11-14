from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from backend.app.domain import ebi_vcf_validator as ebi


def _vcf(path: Path, version: str = "VCFv4.2") -> Path:
    path.write_text(
        f"##fileformat={version}\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    return path


def _fake_tool(tmp_path: Path) -> Path:
    executable = tmp_path / "vcf_validator"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_unsupported_vcf_version_is_explicit_and_does_not_invoke_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _vcf(tmp_path / "unsupported.vcf", "VCFv4.5")
    monkeypatch.setattr(ebi.shutil, "which", lambda _name: pytest.fail("tool must not run"))

    result = ebi.run_ebi_vcf_validator(source)

    assert result["status"] == "NOT_SUPPORTED"
    assert result["vcf_version"] == "VCFv4.5"
    assert result["artifact_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_missing_executable_blocks_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _vcf(tmp_path / "missing.vcf")
    monkeypatch.setattr(ebi.shutil, "which", lambda _name: None)

    with pytest.raises(ebi.EBIValidatorUnavailable):
        ebi.run_ebi_vcf_validator(source)


def test_successful_execution_captures_binary_identity_command_and_full_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _vcf(tmp_path / "valid.vcf")
    executable = _fake_tool(tmp_path)
    monkeypatch.setattr(ebi.shutil, "which", lambda _name: str(executable))

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "vcf_validator version 0.10.2\n", "")
        report_dir = Path(command[command.index("-o") + 1])
        (report_dir / "valid.errors_summary.1.txt").write_text("No errors\n", encoding="utf-8")
        (report_dir / "valid.errors.1.txt").write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "valid VCF\n", "")

    monkeypatch.setattr(ebi.subprocess, "run", fake_run)
    result = ebi.run_ebi_vcf_validator(source)

    assert result["status"] == "PASS"
    assert result["validator_version_expected"] == "0.10.2"
    assert result["executable_sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest()
    assert result["artifact_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["exit_code"] == 0
    assert result["report_count"] == 2
    assert {report["content"] for report in result["reports"]} == {"No errors\n", ""}
    assert result["command"][result["command"].index("-l") + 1] == "warning"


def test_nonzero_exit_is_fail_and_preserves_error_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _vcf(tmp_path / "invalid.vcf")
    executable = _fake_tool(tmp_path)
    monkeypatch.setattr(ebi.shutil, "which", lambda _name: str(executable))

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "vcf_validator version 0.10.2\n", "")
        report_dir = Path(command[command.index("-o") + 1])
        (report_dir / "invalid.errors_summary.1.txt").write_text(
            "Invalid INFO field at line 3\n", encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 1, "", "VCF is invalid")

    monkeypatch.setattr(ebi.subprocess, "run", fake_run)
    result = ebi.run_ebi_vcf_validator(source)

    assert result["status"] == "FAIL"
    assert result["exit_code"] == 1
    assert "VCF is invalid" in result["stderr"]
    assert "Invalid INFO field" in result["reports"][0]["content"]
