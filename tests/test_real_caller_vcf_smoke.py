from __future__ import annotations

import gzip
from pathlib import Path

from scripts.validation.run_real_caller_vcf_smoke import dragen_gp_attestation


def _write_vcf(path: Path, *, targeted: bool) -> None:
    header = ["##fileformat=VCFv4.2"]
    if targeted:
        header.append("##source=DRAGEN_TARGETED")
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


def test_dragen_targeted_extension_requires_both_filename_and_source_marker(tmp_path: Path):
    artifact = tmp_path / "HG002.targeted.vcf.gz"
    _write_vcf(artifact, targeted=True)

    attestation = dragen_gp_attestation(_callset(artifact), artifact)

    assert attestation is not None
    assert attestation["targeted_records_verified"] is True
    assert attestation["caller_extension"] == "INFO/EVENT_AND_EVENTTYPE_NUMBER_A"
    assert attestation["compatibility_profile_id"] == "dragen-v4.2-targeted-merge-vcf42-compatibility"
