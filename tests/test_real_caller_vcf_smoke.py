from __future__ import annotations

import gzip
from pathlib import Path

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
