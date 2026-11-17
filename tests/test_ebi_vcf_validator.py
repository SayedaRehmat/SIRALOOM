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


def test_assembly_checker_captures_reference_and_projection_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vcf = _vcf(tmp_path / "chr20.vcf")
    fasta = tmp_path / "chr20.fa"
    fasta.write_text(">chr20\\nACGTACGT\\n", encoding="ascii")
    Path(str(fasta) + ".fai").write_text("chr20\\t8\\t7\\t8\\t9\\n", encoding="ascii")
    executable = tmp_path / "vcf_assembly_checker"
    executable.write_text("#!/bin/sh\\nexit 0\\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setattr(ebi.shutil, "which", lambda _name: str(executable))

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(
                command, 0, "vcf-assembly-checker version 0.10.2\\n", ""
            )
        report_dir = Path(command[command.index("-o") + 1])
        (report_dir / "chr20.text_assembly_report.1.txt").write_text(
            "8 of 8 records match reference\\n", encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, "All records match\\n", "")

    monkeypatch.setattr(ebi.subprocess, "run", fake_run)
    source_sha = hashlib.sha256(b"original-whole-artifact").hexdigest()
    result = ebi.run_ebi_vcf_assembly_checker(
        vcf,
        fasta,
        source_artifact_sha256=source_sha,
        caller_provenance={"caller_profile_id": "gatk_haplotypecaller", "identity_status": "DECLARED"},
    )

    assert result["status"] == "PASS"
    assert result["validator"] == "EBI_VCF_ASSEMBLY_CHECKER"
    assert result["validator_version_expected"] == "0.10.2"
    assert result["source_artifact_sha256"] == source_sha
    assert result["vcf_version"] == "VCFv4.2"
    assert result["reference_build"] == "GRCh38"
    assert result["validation_input_scope"] == "CHR20_PROJECTION_ONLY"
    assert result["caller"] == "gatk_haplotypecaller"
    assert result["reference_fasta_sha256"] == hashlib.sha256(fasta.read_bytes()).hexdigest()
    assert result["reference_fai_sha256"] == hashlib.sha256(Path(str(fasta) + ".fai").read_bytes()).hexdigest()
    assert "8 of 8 records" in result["reports"][0]["content"]


def test_assembly_checker_requires_reference_fai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vcf = _vcf(tmp_path / "chr20.vcf")
    fasta = tmp_path / "chr20.fa"
    fasta.write_text(">chr20\\nACGT\\n", encoding="ascii")
    monkeypatch.setattr(ebi.shutil, "which", lambda _name: pytest.fail("tool must not run"))

    with pytest.raises(ebi.EBIValidatorUnavailable, match="FASTA and its .fai"):
        ebi.run_ebi_vcf_assembly_checker(
            vcf,
            fasta,
            source_artifact_sha256=hashlib.sha256(b"original").hexdigest(),
        )

def test_large_ebi_reports_are_hashed_and_bounded_with_structured_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _vcf(tmp_path / "dragen.vcf")
    lines = source.read_text(encoding="utf-8").splitlines()
    lines.insert(1, '##INFO=<ID=EVENT,Number=.,Type=String,Description="Event">')
    lines.insert(2, '##INFO=<ID=TARGETED,Number=0,Type=Flag,Description="Targeted caller record">')
    lines.insert(3, '##INFO=<ID=EVENTTYPE,Number=A,Type=String,Description="Type of associated event">')
    lines[4] = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE"
    lines[5] = "1\t20\t.\tA\tG\t.\tPASS\t.\tGT:GP\t0/1:3.1,15.3,3.1"
    lines.append("1\t21\t.\tC\tT\t.\tPASS\tTARGETED;EVENT=evt1;EVENTTYPE=VARIANT_IN_HOMOLOGY_REGION\tGT:GP\t0/1:3.1,15.3,3.1")
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    executable = _fake_tool(tmp_path)
    monkeypatch.setattr(ebi.shutil, "which", lambda _name: str(executable))

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "vcf_validator version 0.10.2\n", "")
        report_dir = Path(command[command.index("-o") + 1])
        (report_dir / "dragen.errors.1.txt").write_text(
            "Line 2: INFO EVENT metadata Number is not 1.\n"
            "Line 6: Sample #1, GP=3.1,15.3,3.1 value does not lie in the interval [0,1].\n"
            "Line 7: INFO 'EVENT' is not listed in a valid meta-data INFO entry. (warning)\n"
            + ("x" * (ebi._MAX_INLINE_REPORT_BYTES + 10)),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 1, "", "VCF is invalid")

    monkeypatch.setattr(ebi.subprocess, "run", fake_run)
    result = ebi.run_ebi_vcf_validator(source)

    assert result["status"] == "FAIL"
    assert result["reports"][0]["content_truncated"] is True
    assert "content" not in result["reports"][0]
    assert result["reports"][0]["sha256"]
    assert len(result["reports"][0]["content_preview"]) <= ebi._REPORT_PREVIEW_BYTES
    assert len(result["diagnostics"]) == 3
    gp = next(item for item in result["diagnostics"] if "GP=" in item["message_template"])
    assert gp["occurrences"] == 1
    assert gp["first_line"] == 6
    assert gp["severity"] == "ERROR"
    event_warning = next(item for item in result["diagnostics"] if item["severity"] == "WARNING")
    assert event_warning["occurrences"] == 1
    assert any(item.get("format_gp") == "3.1,15.3,3.1" for item in result["source_record_examples"])
    assert any(item.get("info_targeted") is True and item.get("info_event") == "evt1" for item in result["source_record_examples"])
    assert any("ID=TARGETED" in item.get("text", "") for item in result["source_record_examples"])
    assert any("ID=EVENTTYPE" in item.get("text", "") for item in result["source_record_examples"])
    # GP is a VCFv4.2 Phred-scaled field: EBI 0.10.2's [0,1] error
    # is classified separately, but the un-attested EVENT extension remains
    # blocking. Never turn the raw EBI FAIL into PASS.
    assessment = result["compatibility_assessment"]
    assert assessment["raw_status"] == "FAIL"
    assert assessment["effective_status"] == "FAIL"
    assert assessment["raw_ebi_result_preserved"] is True
    assert any(
        item["classification"] == "EBI_0_10_2_GP_RANGE_FALSE_POSITIVE_VCF41_VCF42"
        for item in assessment["known_nonblocking_diagnostics"]
    )
    assert any(
        item["classification"] == "UNRESOLVED"
        for item in assessment["blocking_diagnostics"]
    )

def test_vcf42_gp_range_diagnostic_is_classified_as_known_ebi_defect() -> None:
    result = ebi.assess_ebi_vcf_compatibility({
        "status": "FAIL",
        "validator_version_expected": "0.10.2",
        "vcf_version": "VCFv4.2",
        "diagnostics": [{
            "severity": "ERROR",
            "message_template": "Sample #1, GP=<values> value does not lie in the interval [0,1].",
            "occurrences": 4933817,
            "first_line": 3437,
        }],
    })
    assert result["raw_status"] == "FAIL"
    assert result["effective_status"] == "PASS_WITH_DOCUMENTED_COMPATIBILITY_EXCEPTIONS"
    assert result["known_exception_ids"] == ["EBI-VF-149"]
    assert result["blocking_diagnostics"] == []


def test_vcf43_gp_range_diagnostic_remains_blocking() -> None:
    result = ebi.assess_ebi_vcf_compatibility({
        "status": "FAIL",
        "validator_version_expected": "0.10.2",
        "vcf_version": "VCFv4.3",
        "diagnostics": [{
            "severity": "ERROR",
            "message_template": "Sample #1, GP=<values> value does not lie in the interval [0,1].",
            "occurrences": 1,
            "first_line": 4,
        }],
    })
    assert result["effective_status"] == "FAIL"
    assert result["blocking_diagnostics"][0]["classification"] == "UNRESOLVED"


def test_dragen_v42_event_extension_requires_verified_caller_attestation() -> None:
    result = {
        "status": "FAIL",
        "vcf_version": "VCFv4.2",
        "diagnostics": [
            {
                "severity": "ERROR",
                "message_template": "INFO EVENT metadata Number is not 1.",
                "occurrences": 1,
                "first_line": 32,
            },
            {
                "severity": "WARNING",
                "message_template": "INFO 'EVENT' is not listed in a valid meta-data INFO entry.",
                "occurrences": 107,
                "first_line": 50844,
            },
        ],
    }
    attestation = {
        "status": "VERIFIED_PINNED_PUBLIC_DATASET_FIXTURE",
        "caller_profile_id": "dragen_snv_germline",
        "caller_release": "4.2",
        "caller_extension": "INFO/EVENT_AND_EVENTTYPE_NUMBER_A",
            "compatibility_profile_id": "dragen-v4.2-targeted-merge-vcf42-compatibility",
        "caller_extension_detected": True,
        "targeted_records_verified": True,
    }
    assessed = ebi.assess_ebi_vcf_compatibility(result, caller_semantic_attestation=attestation)
    assert assessed["effective_status"] == "PASS_WITH_DOCUMENTED_COMPATIBILITY_EXCEPTIONS"
    assert assessed["caller_extension_attested"] is True
    assert "DRAGEN-V42-EVENT-VCF44-EXTENSION" in assessed["known_exception_ids"]

    untrusted = ebi.assess_ebi_vcf_compatibility(result)
    assert untrusted["effective_status"] == "FAIL"
    assert len(untrusted["blocking_diagnostics"]) == 2



def test_assembly_checker_full_file_scope_retains_stdout_when_text_report_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vcf = _vcf(tmp_path / "whole-genome.vcf")
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">chr1\\nACGT\\n", encoding="ascii")
    Path(str(fasta) + ".fai").write_text("chr1\\t4\\t6\\t4\\t5\\n", encoding="ascii")
    executable = _fake_tool(tmp_path)
    monkeypatch.setattr(ebi.shutil, "which", lambda _name: str(executable))

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(
                command, 0, "vcf-assembly-checker version 0.10.2\\n", ""
            )
        return subprocess.CompletedProcess(
            command, 0, "100000 of 100000 records match reference (100%)\\n", ""
        )

    monkeypatch.setattr(ebi.subprocess, "run", fake_run)
    result = ebi.run_ebi_vcf_assembly_checker(
        vcf,
        fasta,
        source_artifact_sha256=hashlib.sha256(b"source-vcf").hexdigest(),
        validation_input_scope="FULL_FILE",
    )

    assert result["status"] == "PASS"
    assert result["validation_input_scope"] == "FULL_FILE"
    assert result["summary_evidence"]["stdout"].startswith("100000 of 100000")
    assert result["summary_evidence"]["text_report_files_present"] is False
    assert result["summary_evidence"]["empty_text_report_files"] == []
    assert "not treated as diagnostic evidence" in result["summary_evidence"]["interpretation"]


def test_assembly_checker_rejects_unknown_validation_scope(
    tmp_path: Path,
) -> None:
    vcf = _vcf(tmp_path / "sample.vcf")
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">chr1\\nACGT\\n", encoding="ascii")
    Path(str(fasta) + ".fai").write_text("chr1\\t4\\t6\\t4\\t5\\n", encoding="ascii")
    with pytest.raises(ValueError, match="validation_input_scope"):
        ebi.run_ebi_vcf_assembly_checker(
            vcf,
            fasta,
            source_artifact_sha256=hashlib.sha256(b"source-vcf").hexdigest(),
            validation_input_scope="SOME_PROJECTION",
        )



def test_zero_exit_with_unresolved_error_diagnostic_is_not_effective_pass() -> None:
    assessed = ebi.assess_ebi_vcf_compatibility({
        "status": "PASS", "validator_version_expected": "0.10.2", "vcf_version": "VCFv4.2",
        "diagnostics": [{"severity": "ERROR", "message_template": "Malformed genotype field.", "occurrences": 1, "first_line": 17}],
    })
    assert assessed["raw_status"] == "PASS"
    assert assessed["effective_status"] == "FAIL"
    assert assessed["unresolved_error_count"] == 1


def test_zero_exit_with_unresolved_warning_is_review_required_not_clean_pass() -> None:
    assessed = ebi.assess_ebi_vcf_compatibility({
        "status": "PASS", "validator_version_expected": "0.10.2", "vcf_version": "VCFv4.2",
        "diagnostics": [{"severity": "WARNING", "message_template": "Reference and alternate alleles do not share the first nucleotide.", "occurrences": 6344, "first_line": 1035}],
    })
    assert assessed["effective_status"] == "PASS_WITH_REVIEW_REQUIRED"
    assert assessed["review_required"] is True
    assert assessed["unresolved_warning_count"] == 1



def test_assembly_checker_zero_exit_with_error_diagnostic_is_failure() -> None:
    assessed = ebi._assembly_checker_effective_status(0, [{"severity": "ERROR"}])
    assert assessed["status"] == "FAIL"
    assert assessed["unresolved_error_count"] == 1


def test_assembly_checker_warning_diagnostic_requires_review() -> None:
    assessed = ebi._assembly_checker_effective_status(0, [{"severity": "WARNING"}])
    assert assessed["status"] == "PASS_WITH_REVIEW_REQUIRED"
    assert assessed["review_required"] is True
