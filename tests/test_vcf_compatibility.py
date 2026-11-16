from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.app.domain.vcf_compatibility import (
    VCFCompatibilityProjectionError,
    create_dragen_v42_event_projection,
)


def _attestation() -> dict:
    return {
        "status": "VERIFIED_LAB_SIGNED_RUN_MANIFEST",
        "caller_profile_id": "dragen_snv_germline",
        "caller_release": "4.2",
        "caller_extension": "INFO/EVENT_AND_EVENTTYPE_NUMBER_A",
        "compatibility_profile_id": "dragen-v4.2-targeted-merge-vcf42-compatibility",
        "caller_extension_detected": True,
        "targeted_records_verified": True,
        "output_mode": "DRAGEN_V42_HARD_FILTERED_WITH_TARGETED_MERGE",
    }


def _source(path: Path, *, targeted: bool = True) -> Path:
    info = "TARGETED;EVENT=evt1;EVENTTYPE=GENE_CONVERSION" if targeted else "EVENT=evt1;EVENTTYPE=GENE_CONVERSION"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=DRAGEN_SNV\n"
        "##source=DRAGEN_TARGETED\n"
        '##INFO=<ID=TARGETED,Number=0,Type=Flag,Description="Targeted caller record">\n'
        '##INFO=<ID=EVENT,Number=A,Type=String,Description="Event name">\n'
        '##INFO=<ID=EVENTTYPE,Number=A,Type=String,Description="Event type">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t10\t.\tA\tG\t.\tPASS\t{info}\tGT\t0/1\n",
        encoding="utf-8",
    )
    return path


def test_projection_namespaces_reserved_fields_without_changing_values_or_source(tmp_path):
    source = _source(tmp_path / "source.vcf")
    original_bytes = source.read_bytes()
    original_sha256 = hashlib.sha256(original_bytes).hexdigest()
    output = tmp_path / "projected.vcf"

    result = create_dragen_v42_event_projection(
        source,
        output,
        caller_semantic_attestation=_attestation(),
    )

    projected = output.read_text(encoding="utf-8")
    assert source.read_bytes() == original_bytes
    assert result["source_sha256"] == original_sha256
    assert result["source_artifact_mutated"] is False
    assert result["source_record_count"] == result["projection_record_count"] == 1
    assert result["targeted_event_record_count"] == 1
    assert 'ID=DRAGEN_EVENT,Number=A,Type=String' in projected
    assert 'ID=DRAGEN_EVENTTYPE,Number=A,Type=String' in projected
    assert "DRAGEN_EVENT=evt1;DRAGEN_EVENTTYPE=GENE_CONVERSION" in projected
    assert "TARGETED;" in projected
    assert "ID=EVENT," not in projected
    assert "ID=EVENTTYPE," not in projected


def test_projection_rejects_header_only_or_unverified_attestation(tmp_path):
    source = _source(tmp_path / "source.vcf")
    attestation = _attestation()
    attestation["targeted_records_verified"] = False

    with pytest.raises(VCFCompatibilityProjectionError, match="NOT_FULLY_ATTESTED"):
        create_dragen_v42_event_projection(
            source,
            tmp_path / "projected.vcf",
            caller_semantic_attestation=attestation,
        )


def test_projection_rejects_event_record_without_targeted_marker(tmp_path):
    source = _source(tmp_path / "source.vcf", targeted=False)

    with pytest.raises(VCFCompatibilityProjectionError, match="TARGETED_MARKER_MISSING"):
        create_dragen_v42_event_projection(
            source,
            tmp_path / "projected.vcf",
            caller_semantic_attestation=_attestation(),
        )


def test_projection_refuses_to_overwrite_existing_evidence(tmp_path):
    source = _source(tmp_path / "source.vcf")
    output = tmp_path / "projected.vcf"
    output.write_text("preserve this evidence\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_dragen_v42_event_projection(
            source,
            output,
            caller_semantic_attestation=_attestation(),
        )

    assert output.read_text(encoding="utf-8") == "preserve this evidence\n"
