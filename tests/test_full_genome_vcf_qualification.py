from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validation" / "run_full_genome_vcf_qualification.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_full_genome_vcf_qualification", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_genome_runner_requires_exact_gatk_version_and_records_binary_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load_runner()
    executable = tmp_path / "gatk"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda name: str(executable) if name == "gatk" else None)
    monkeypatch.setattr(
        module,
        "run_command",
        lambda command, timeout: {
            "command": command,
            "exit_code": 0,
            "stdout": "The Genome Analysis Toolkit (GATK) v4.6.2.0\\n",
            "stderr": "",
        },
    )
    monkeypatch.setattr(module, "sha256_file", lambda path: "a" * 64)

    result = module.require_gatk("4.6.2.0")

    assert result["observed_version"] == "4.6.2.0"
    assert result["expected_version"] == "4.6.2.0"
    assert result["executable_sha256"] == "a" * 64
    assert result["version_evidence"]["exit_code"] == 0


def test_full_genome_runner_rejects_gatk_version_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_runner()
    executable = tmp_path / "gatk"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(
        module,
        "run_command",
        lambda command, timeout: {
            "command": command,
            "exit_code": 0,
            "stdout": "The Genome Analysis Toolkit (GATK) v4.6.1.0",
            "stderr": "",
        },
    )

    with pytest.raises(module.QualificationBlocked, match="GATK_VERSION_MISMATCH"):
        module.require_gatk("4.6.2.0")


def test_full_genome_runner_blocks_when_gatk_is_not_installed(monkeypatch: pytest.MonkeyPatch):
    module = _load_runner()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    with pytest.raises(module.QualificationBlocked, match="GATK_VALIDATEVARIANTS_UNAVAILABLE"):
        module.require_gatk("4.6.2.0")
