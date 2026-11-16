from __future__ import annotations

import gzip
import subprocess
from pathlib import Path

import pytest

from scripts.validation import run_real_caller_vcf_smoke as smoke
from scripts.validation.run_real_caller_vcf_smoke import dragen_gp_attestation


def _write_vcf(path: Path, *, targeted: bool) -> None:
    header = ["##fileformat=VCFv4.2", "##source=DRAGEN_SNV"]
    if targeted:
        header.extend([
            "##source=DRAGEN_TARGETED",
            '##INFO=<ID=TARGETED,Number=0,Type=Flag,Description="Targeted caller record">',
            '##INFO=<ID=EVENT,Number=A,Type=String,Description="Event name">',
            '##INFO=<ID=EVENTTYPE,Number=A,Type=String,Description="Type of associated event">',
        ])
    header.append("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO")
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(header) + "\n")


def _callset(path: Path) -> dict:
    return {
        "caller": "DRAGEN",
        "filename": "HG002_35x.hard-filtered.vcf.gz",
        "sha256": "fixture-sha256",
        "local_path": str(path),
    }


def test_hard_filtered_dragen_fixture_does_not_receive_targeted_event_waiver(tmp_path: Path):
    artifact = tmp_path / "HG002_35x.hard-filtered.vcf.gz"
    _write_vcf(artifact, targeted=False)

    attestation = dragen_gp_attestation(_callset(artifact), artifact)

    assert attestation is not None
    assert attestation["spec_semantics"] == "VCFv4.2_FORMAT_GP_PHRED_SCALED"
    assert attestation["targeted_records_verified"] is False
    assert attestation["targeted_output_provenance_status"] == "NOT_ESTABLISHED_FOR_THIS_ARTIFACT"
    assert "caller_extension" not in attestation
    assert "compatibility_profile_id" not in attestation


def test_dragen_hard_filtered_merged_targeted_output_does_not_require_targeted_filename(tmp_path: Path):
    artifact = tmp_path / "HG002_35x.hard-filtered.vcf.gz"
    _write_vcf(artifact, targeted=True)

    attestation = dragen_gp_attestation(_callset(artifact), artifact)

    assert attestation is not None
    assert attestation["targeted_records_verified"] is False  # strict parser must verify each record
    assert attestation["targeted_output_filename_verified"] is False
    assert attestation["output_mode"] == "DRAGEN_V42_HARD_FILTERED_WITH_TARGETED_MERGE"
    assert attestation["targeted_output_provenance_status"] == (
        "VERIFIED_BY_SOURCE_HEADER_AND_TARGETED_FIELD_DEFINITIONS"
    )
    assert attestation["caller_extension"] == "INFO/EVENT_AND_EVENTTYPE_NUMBER_A"
    assert attestation["compatibility_profile_id"] == "dragen-v4.2-targeted-merge-vcf42-compatibility"


def test_dragen_targeted_source_without_targeted_field_definitions_is_not_attested(tmp_path: Path):
    artifact = tmp_path / "HG002_35x.hard-filtered.vcf.gz"
    with gzip.open(artifact, "wt", encoding="utf-8") as handle:
        handle.write(
            "##fileformat=VCFv4.2\n"
            "##source=DRAGEN_SNV\n"
            "##source=DRAGEN_TARGETED\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        )

    attestation = dragen_gp_attestation(_callset(artifact), artifact)

    assert attestation is not None
    assert "caller_extension" not in attestation
    assert attestation["output_mode"] == "DRAGEN_V42_OUTPUT_MODE_UNRESOLVED"


def test_gatk_runtime_requires_exact_observed_version_and_records_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    executable = tmp_path / "gatk"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    lock_file = tmp_path / "gatk-explicit.lock"
    lock_file.write_text("@EXPLICIT\\nhttps://conda.example/gatk-4.6.2.0.conda\\n", encoding="utf-8")
    monkeypatch.setenv("SIRALOOM_GATK_EXPLICIT_LOCK", str(lock_file))
    monkeypatch.setattr(smoke.shutil, "which", lambda name: str(executable) if name == "gatk" else None)
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout="The Genome Analysis Toolkit (GATK) v4.6.2.0\n", stderr=""
        ),
    )

    runtime = smoke.require_gatk("4.6.2.0")

    assert runtime["observed_version"] == "4.6.2.0"
    assert runtime["expected_version"] == "4.6.2.0"
    assert runtime["executable_sha256"] == smoke.digest(executable)


def test_gatk_runtime_rejects_version_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    executable = tmp_path / "gatk"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    lock_file = tmp_path / "gatk-explicit.lock"
    lock_file.write_text("@EXPLICIT\\nhttps://conda.example/gatk-4.6.2.0.conda\\n", encoding="utf-8")
    monkeypatch.setenv("SIRALOOM_GATK_EXPLICIT_LOCK", str(lock_file))
    monkeypatch.setattr(smoke.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout="The Genome Analysis Toolkit (GATK) v4.6.1.0\n", stderr=""
        ),
    )

    with pytest.raises(RuntimeError, match="GATK_VERSION_MISMATCH"):
        smoke.require_gatk("4.6.2.0")


def test_reference_dictionary_uses_sequence_md5_and_valid_sam_fields(tmp_path: Path):
    reference = tmp_path / "chr20.reference.fa"
    sequence = "ACGTN"
    dictionary = smoke.write_reference_dictionary(reference, "chr20", sequence)

    lines = dictionary.read_text(encoding="ascii").splitlines()
    assert lines[0] == "@HD\tVN:1.6\tSO:unsorted"
    assert lines[1].startswith("@SQ\tSN:chr20\tLN:5\tM5:")
    assert lines[1].endswith(smoke.hashlib.md5(sequence.encode("ascii")).hexdigest())


def test_gatk_validatevariants_persists_command_input_reference_and_exit_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    input_vcf = tmp_path / "caller.chr20.vcf"
    input_vcf.write_text("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n", encoding="utf-8")
    reference = tmp_path / "chr20.reference.fa"
    reference.write_text(">chr20\nACGT\n", encoding="ascii")
    Path(str(reference) + ".fai").write_text("chr20\t4\t7\t4\t5\n", encoding="ascii")
    dictionary = smoke.write_reference_dictionary(reference, "chr20", "ACGT")
    runtime = {
        "executable": "/opt/gatk/bin/gatk",
        "observed_version": "4.6.2.0",
        "executable_sha256": "a" * 64,
    }
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout="ValidateVariants completed successfully\n", stderr=""
        ),
    )

    result = smoke.run_gatk_validate_variants(
        runtime, "GATK_HAPLOTYPECALLER", input_vcf, reference, tmp_path,
        source_vcf_sha256="b" * 64,
    )

    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert result["command"][1] == "ValidateVariants"
    assert result["input_sha256"] == smoke.digest(input_vcf)
    assert result["reference_dictionary_sha256"] == smoke.digest(dictionary)
    assert Path(result["stdout_path"]).read_text(encoding="utf-8").startswith("ValidateVariants")
