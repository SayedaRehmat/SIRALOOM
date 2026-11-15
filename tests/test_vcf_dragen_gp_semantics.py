from __future__ import annotations

import hashlib

import pytest

from backend.app.domain import vcf_validation as validation


def _vcf(path, gp_value: str, *, version: str = "VCFv4.2", event_extension: bool = False) -> None:
    event_header = (
        '##INFO=<ID=TARGETED,Number=0,Type=Flag,Description="Targeted caller record">\\n'
        '##INFO=<ID=EVENT,Number=A,Type=String,Description="Event name">\\n'
        '##INFO=<ID=EVENTTYPE,Number=A,Type=String,Description="Type of associated event">\\n'
        if event_extension else ""
    )
    info_value = "TARGETED;EVENT=EV1;EVENTTYPE=VARIANT_IN_HOMOLOGY_REGION" if event_extension else "."
    path.write_text(
        f"##fileformat={version}\\n"
        '##source=DRAGEN_SNV\\n'
        + event_header
        + '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\\n'
        + '##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior probabilities">\\n'
        + "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\tFORMAT\\tHG002\\n"
        + f"chr20\\t100\\t.\\tA\\tC\\t50\\tPASS\\t{info_value}\\tGT:GP\\t0/1:{gp_value}\\n",
        encoding="utf-8",
    )


def test_vcf42_gp_phred_values_pass_without_caller_attestation(tmp_path):
    source = tmp_path / "vcf42-phred.vcf"
    _vcf(source, "3.1662,15.337,3.1125")
    result = validation.validate_vcf_strict(source)
    assert result["records"] == 1
    assert result["caller_semantic_attestation"] is None
    assert result["caller_semantic_compatibility_review_required"] is False


def test_vcf41_gp_phred_values_pass_without_caller_attestation(tmp_path):
    source = tmp_path / "vcf41-phred.vcf"
    _vcf(source, "3.1662,15.337,3.1125", version="VCFv4.1")
    assert validation.validate_vcf_strict(source)["records"] == 1


def test_vcf43_gp_probability_values_pass(tmp_path):
    source = tmp_path / "vcf43-probabilities.vcf"
    _vcf(source, "0.1,0.8,0.1", version="VCFv4.3")
    assert validation.validate_vcf_strict(source)["records"] == 1


def test_vcf43_gp_value_above_one_fails(tmp_path):
    source = tmp_path / "vcf43-invalid-gp.vcf"
    _vcf(source, "0.1,3.1662,0.1", version="VCFv4.3")
    with pytest.raises(validation.StrictVCFValidationError) as error:
        validation.validate_vcf_strict(source)
    assert error.value.code == "VCF_FIELD_TYPE_INVALID"
    assert "3.1662" in str(error.value)


def test_vcf42_gp_negative_phred_value_fails(tmp_path):
    source = tmp_path / "vcf42-negative-gp.vcf"
    _vcf(source, "0.1,-3.0,12.5")
    with pytest.raises(validation.StrictVCFValidationError) as error:
        validation.validate_vcf_strict(source)
    assert error.value.code == "VCF_FIELD_TYPE_INVALID"


def test_dragen_v42_event_extension_requires_attestation(tmp_path):
    source = tmp_path / "dragen-v42-event.vcf"
    _vcf(source, "3.1662,15.337,3.1125", event_extension=True)
    with pytest.raises(validation.StrictVCFValidationError) as error:
        validation.validate_vcf_strict(source)
    assert error.value.code == "VCF_HEADER_DEFINITION_INVALID"


def test_verified_dragen_v42_event_extension_is_explicitly_review_required(tmp_path, monkeypatch):
    source = tmp_path / "dragen-v42-event.vcf"
    _vcf(source, "3.1662,15.337,3.1125", event_extension=True)
    monkeypatch.setattr(
        validation,
        "_verify_dragen_42_fixture_attestation",
        lambda _path, _attestation: {
            "status": "VERIFIED_PINNED_PUBLIC_DATASET_FIXTURE",
            "caller_profile_id": "dragen_snv_germline",
            "caller_release": "4.2",
            "field": "INFO/EVENT_AND_EVENTTYPE",
            "gp_spec_semantics": "VCFv4.2_FORMAT_GP_PHRED_SCALED",
            "spec_conformance": "VCFv4.2_CONFORMANT",
            "caller_extension": "INFO/EVENT_AND_EVENTTYPE_NUMBER_A",
            "clinical_review_required": True,
        },
    )
    result = validation.validate_vcf_strict(source, caller_attestation={"fixture": "pinned"})
    assert result["records"] == 1
    assert result["caller_semantic_attestation"]["caller_release"] == "4.2"
    assert result["caller_semantic_attestation"]["targeted_records_verified"] is True
    assert result["caller_semantic_compatibility_review_required"] is True
    assert result["caller_provenance"]["caller_semantic_compatibility_review_required"] is True
    assert result["caller_provenance"]["caller_semantic_compatibility_status"] == "DOCUMENTED_DRAGEN_V42_EVENT_EXTENSION"
    assert {item["field_id"] for item in result["caller_provenance"]["field_semantic_deviations"]} >= {"EVENT", "EVENTTYPE"}
    assert result["caller_provenance"]["field_semantic_profiles"][-1]["field_id"] == "GP"


def test_dragen_attestation_rejects_missing_source_binding(tmp_path):
    source = tmp_path / "dragen.vcf"
    _vcf(source, "3.1662,15.337,3.1125")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    attestation = {
        "schema_version": 1,
        "caller_profile_id": "dragen_snv_germline",
        "caller_release": "4.2",
        "source_record_url": "https://zenodo.org/records/8350256",
        "source_filename": "HG002_35x.hard-filtered.vcf.gz",
        "source_md5": "388f58faa52a8811fe19b06533d2c3d5",
        "spec_semantics": "VCFv4.2_FORMAT_GP_PHRED_SCALED",
        "caller_extension": "INFO/EVENT_AND_EVENTTYPE_NUMBER_A",
        "source_sha256": digest,
        "artifact_sha256": digest,
    }
    with pytest.raises(validation.StrictVCFValidationError) as error:
        validation._verify_dragen_42_fixture_attestation(source, attestation)
    assert error.value.code == "VCF_CALLER_ATTESTATION_INVALID"

def test_dragen_v42_event_extension_rejects_event_records_without_targeted_flag(tmp_path, monkeypatch):
    source = tmp_path / "dragen-v42-event-without-targeted-flag.vcf"
    _vcf(source, "3.1662,15.337,3.1125", event_extension=True)
    source.write_text(
        source.read_text(encoding="utf-8").replace("TARGETED;EVENT=", "EVENT="),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        validation,
        "_verify_dragen_42_fixture_attestation",
        lambda _path, _attestation: {
            "status": "VERIFIED_PINNED_PUBLIC_DATASET_FIXTURE",
            "caller_profile_id": "dragen_snv_germline",
            "caller_release": "4.2",
            "field": "INFO/EVENT_AND_EVENTTYPE",
            "gp_spec_semantics": "VCFv4.2_FORMAT_GP_PHRED_SCALED",
            "spec_conformance": "VCFv4.2_CONFORMANT",
            "caller_extension": "INFO/EVENT_AND_EVENTTYPE_NUMBER_A",
            "clinical_review_required": True,
        },
    )
    with pytest.raises(validation.StrictVCFValidationError) as error:
        validation.validate_vcf_strict(source, caller_attestation={"fixture": "pinned"})
    assert error.value.code == "VCF_CALLER_EXTENSION_INVALID"

