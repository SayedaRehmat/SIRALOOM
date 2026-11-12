from __future__ import annotations

import hashlib

import pytest

from backend.app.domain import vcf_validation as validation


def _vcf(path, gp_value: str) -> None:
    path.write_text(
        "##fileformat=VCFv4.2\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior probabilities">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG002\n"
        f"chr20\t100\t.\tA\tC\t50\tPASS\t.\tGT:GP\t0/1:{gp_value}\n",
        encoding="utf-8",
    )


def test_standard_gp_probability_values_pass(tmp_path):
    source = tmp_path / "standard.vcf"
    _vcf(source, "0.1,0.8,0.1")

    result = validation.validate_vcf_strict(source)

    assert result["records"] == 1
    assert result["caller_semantic_attestation"] is None
    assert result["caller_semantic_compatibility_review_required"] is False


def test_standard_gp_value_above_one_fails_without_attestation(tmp_path):
    source = tmp_path / "standard.vcf"
    _vcf(source, "0.1,3.1662e+00,0.1")

    with pytest.raises(validation.StrictVCFValidationError) as error:
        validation.validate_vcf_strict(source)

    assert error.value.code == "VCF_FIELD_TYPE_INVALID"
    assert "3.1662e+00" in str(error.value)


def test_verified_dragen_profile_accepts_phred_gp_but_requires_review(tmp_path, monkeypatch):
    source = tmp_path / "dragen.vcf"
    _vcf(source, "0.1,3.1662e+00,12.5")
    attestation = {"fixture": "pinned-dataset"}

    monkeypatch.setattr(
        validation,
        "_verify_dragen_42_gp_attestation",
        lambda _path, _attestation: {
            "status": "VERIFIED_PINNED_PUBLIC_DATASET_FIXTURE",
            "caller_profile_id": "dragen_snv_germline",
            "caller_release": "4.2",
            "field": "FORMAT/GP",
            "scale": "PHRED_SCALED_POSTERIOR_GENOTYPE_VALUES",
            "clinical_review_required": True,
        },
    )

    result = validation.validate_vcf_strict(source, caller_attestation=attestation)

    assert result["records"] == 1
    assert result["caller_semantic_attestation"]["caller_release"] == "4.2"
    assert result["caller_semantic_compatibility_review_required"] is True


def test_phred_gp_still_rejects_negative_values(tmp_path, monkeypatch):
    source = tmp_path / "dragen.vcf"
    _vcf(source, "0.1,-3.0,12.5")
    monkeypatch.setattr(
        validation,
        "_verify_dragen_42_gp_attestation",
        lambda _path, _attestation: {"status": "VERIFIED_PINNED_PUBLIC_DATASET_FIXTURE"},
    )

    with pytest.raises(validation.StrictVCFValidationError) as error:
        validation.validate_vcf_strict(source, caller_attestation={"fixture": True})

    assert error.value.code == "VCF_FIELD_TYPE_INVALID"


def test_dragen_attestation_rejects_unpinned_or_missing_provenance(tmp_path):
    source = tmp_path / "dragen.vcf"
    _vcf(source, "0.1,3.1662e+00,12.5")
    source.write_bytes(source.read_bytes())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    attestation = {
        "schema_version": 1,
        "caller_profile_id": "dragen_snv_germline",
        "caller_release": "4.2",
        "source_record_url": "https://zenodo.org/records/8350256",
        "source_filename": "HG002_35x.hard-filtered.vcf.gz",
        "source_md5": "388f58faa52a8811fe19b06533d2c3d5",
        "semantic_deviation": "FORMAT/GP_PHRED_SCALE",
        "source_sha256": digest,
        "artifact_sha256": digest,
    }

    with pytest.raises(validation.StrictVCFValidationError) as error:
        validation._verify_dragen_42_gp_attestation(source, attestation)

    assert error.value.code == "VCF_CALLER_ATTESTATION_INVALID"
