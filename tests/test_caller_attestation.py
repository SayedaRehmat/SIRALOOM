from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.domain.caller_attestation import canonical_manifest_bytes
from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict


def _write_dragen_vcf(path: Path, *, version: str | None = None) -> str:
    version_line = f"##DRAGENVersion={version}\n" if version else ""
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=DRAGEN_SNV\n"
        + version_line
        + '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        + '##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior values">\n'
        + "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        + "1\t10\t.\tA\tG\t.\tPASS\t.\tGT:GP\t0/1:3.1662e+00,0.0,1.2\n",
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _signed_envelope(path: Path, organization_id, monkeypatch, *, caller_profile_id="dragen_snv_germline", caller_release="4.2", reference_build="GRCh38"):
    key = b"laboratory-test-signing-key-material-32bytes"
    key_id = "test-lab-run-signer-v1"
    manifest = {
        "schema_version": 1,
        "manifest_id": str(uuid4()),
        "organization_id": str(organization_id),
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "caller_profile_id": caller_profile_id,
        "caller_release": caller_release,
        "pipeline_run_id": "run-HG002-2026-001",
        "assay_id": "WGS-GERMLINE-35X",
        "reference_build": reference_build,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "signer_id": "lab-pipeline-attestor",
    }
    monkeypatch.setattr(
        "backend.app.domain.caller_attestation.settings.caller_attestation_hmac_keys_json",
        json.dumps({str(organization_id): {key_id: key.hex()}}),
    )
    signature = hmac.new(key, canonical_manifest_bytes(manifest), hashlib.sha256).hexdigest()
    return {"manifest": manifest, "key_id": key_id, "signature": signature}


def test_dragen_gp_phred_requires_a_trusted_signed_run_manifest(tmp_path: Path) -> None:
    path = tmp_path / "dragen.vcf"
    _write_dragen_vcf(path)
    with pytest.raises(StrictVCFValidationError) as error:
        validate_vcf_strict(path)
    assert error.value.code == "VCF_FIELD_TYPE_INVALID"


def test_signed_dragen42_manifest_binds_artifact_and_preserves_review_gate(tmp_path, monkeypatch) -> None:
    organization_id = uuid4()
    path = tmp_path / "dragen.vcf"
    digest = _write_dragen_vcf(path)
    envelope = _signed_envelope(path, organization_id, monkeypatch)

    result = validate_vcf_strict(
        path,
        caller_attestation=envelope,
        organization_id=organization_id,
        artifact_sha256=digest,
        expected_reference_build="GRCh38",
    )

    assert result["caller_run_attestation"]["status"] == "VERIFIED_LAB_SIGNED_RUN_MANIFEST"
    assert result["caller_semantic_compatibility_review_required"] is True
    assert result["caller_provenance"]["caller_semantic_compatibility_status"] == "CALLER_SPEC_SEMANTIC_DEVIATION"
    assert result["caller_provenance"]["field_semantic_deviations"][0]["field_id"] == "GP"
    assert result["caller_provenance"]["field_semantic_deviations"][0]["clinical_interpretation"] == "REVIEW_REQUIRED"


def test_signed_manifest_with_tampered_signature_is_rejected(tmp_path, monkeypatch) -> None:
    organization_id = uuid4()
    path = tmp_path / "dragen.vcf"
    digest = _write_dragen_vcf(path)
    envelope = _signed_envelope(path, organization_id, monkeypatch)
    envelope["signature"] = "0" * 64

    with pytest.raises(StrictVCFValidationError) as error:
        validate_vcf_strict(
            path, caller_attestation=envelope, organization_id=organization_id,
            artifact_sha256=digest, expected_reference_build="GRCh38",
        )
    assert error.value.code == "CALLER_ATTESTATION_SIGNATURE_INVALID"


def test_signed_manifest_cannot_cross_tenant_or_artifact_digest(tmp_path, monkeypatch) -> None:
    organization_id = uuid4()
    path = tmp_path / "dragen.vcf"
    digest = _write_dragen_vcf(path)
    envelope = _signed_envelope(path, organization_id, monkeypatch)

    with pytest.raises(StrictVCFValidationError) as tenant_error:
        validate_vcf_strict(
            path, caller_attestation=envelope, organization_id=uuid4(),
            artifact_sha256=digest, expected_reference_build="GRCh38",
        )
    assert tenant_error.value.code == "CALLER_ATTESTATION_TENANT_MISMATCH"

    with pytest.raises(StrictVCFValidationError) as digest_error:
        validate_vcf_strict(
            path, caller_attestation=envelope, organization_id=organization_id,
            artifact_sha256="0" * 64, expected_reference_build="GRCh38",
        )
    assert digest_error.value.code == "CALLER_ATTESTATION_ARTIFACT_MISMATCH"


def test_signed_manifest_must_match_header_caller_and_selected_build(tmp_path, monkeypatch) -> None:
    organization_id = uuid4()
    path = tmp_path / "dragen.vcf"
    digest = _write_dragen_vcf(path)
    envelope = _signed_envelope(
        path, organization_id, monkeypatch, caller_profile_id="deepvariant_germline"
    )
    with pytest.raises(StrictVCFValidationError) as caller_error:
        validate_vcf_strict(
            path, caller_attestation=envelope, organization_id=organization_id,
            artifact_sha256=digest, expected_reference_build="GRCh38",
        )
    assert caller_error.value.code == "VCF_CALLER_ATTESTATION_CALLER_CONFLICT"

    envelope = _signed_envelope(path, organization_id, monkeypatch, reference_build="GRCh37")
    with pytest.raises(StrictVCFValidationError) as build_error:
        validate_vcf_strict(
            path, caller_attestation=envelope, organization_id=organization_id,
            artifact_sha256=digest, expected_reference_build="GRCh38",
        )
    assert build_error.value.code == "VCF_CALLER_ATTESTATION_BUILD_CONFLICT"


def test_header_release_conflict_rejects_signed_manifest(tmp_path, monkeypatch) -> None:
    organization_id = uuid4()
    path = tmp_path / "dragen.vcf"
    digest = _write_dragen_vcf(path, version="4.3.0")
    envelope = _signed_envelope(path, organization_id, monkeypatch, caller_release="4.2")

    with pytest.raises(StrictVCFValidationError) as error:
        validate_vcf_strict(
            path, caller_attestation=envelope, organization_id=organization_id,
            artifact_sha256=digest, expected_reference_build="GRCh38",
        )
    assert error.value.code == "VCF_CALLER_ATTESTATION_RELEASE_CONFLICT"



def test_signed_manifest_for_other_dragen_release_does_not_authorize_42_gp_semantics(tmp_path, monkeypatch) -> None:
    organization_id = uuid4()
    path = tmp_path / "dragen.vcf"
    digest = _write_dragen_vcf(path)
    envelope = _signed_envelope(path, organization_id, monkeypatch, caller_release="4.3.0")

    with pytest.raises(StrictVCFValidationError) as error:
        validate_vcf_strict(
            path,
            caller_attestation=envelope,
            organization_id=organization_id,
            artifact_sha256=digest,
            expected_reference_build="GRCh38",
        )
    assert error.value.code == "VCF_FIELD_TYPE_INVALID"


def test_untrusted_signer_and_post_signing_artifact_mutation_are_rejected(tmp_path, monkeypatch) -> None:
    organization_id = uuid4()
    path = tmp_path / "dragen.vcf"
    digest = _write_dragen_vcf(path)
    envelope = _signed_envelope(path, organization_id, monkeypatch)
    monkeypatch.setattr(
        "backend.app.domain.caller_attestation.settings.caller_attestation_hmac_keys_json",
        json.dumps({str(organization_id): {"different-key-id": "c" * 64}}),
    )

    with pytest.raises(StrictVCFValidationError) as signer_error:
        validate_vcf_strict(
            path, caller_attestation=envelope, organization_id=organization_id,
            artifact_sha256=digest, expected_reference_build="GRCh38",
        )
    assert signer_error.value.code == "CALLER_ATTESTATION_SIGNER_UNTRUSTED"

    envelope = _signed_envelope(path, organization_id, monkeypatch)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(StrictVCFValidationError) as digest_error:
        validate_vcf_strict(
            path, caller_attestation=envelope, organization_id=organization_id,
            artifact_sha256=digest, expected_reference_build="GRCh38",
        )
    assert digest_error.value.code == "CALLER_ATTESTATION_ARTIFACT_DIGEST_MISMATCH"
