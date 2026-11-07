from uuid import uuid4

import pytest

from backend.app.domain.family_genotype_matrix import build_family_genotype_matrix


def _sample(member_id, identifier, calls):
    return {
        "member_id": member_id,
        "member_identifier": identifier,
        "relationship_to_proband": "PROBAND" if identifier == "PROBAND" else "FATHER",
        "sex": "UNKNOWN",
        "affected_status": "AFFECTED" if identifier == "PROBAND" else "UNAFFECTED",
        "specimen_id": uuid4(),
        "analysis_id": uuid4(),
        "analysis_version": 1,
        "artifact_id": uuid4(),
        "artifact_sha256": "a" * 64,
        "sample_name": identifier,
        "binding_id": uuid4(),
        "binding_fingerprint": "b" * 64,
        "normalization_step_status": "SUCCEEDED",
        "normalized_partition_count": 2,
        "ploidy_evidence": None,
        "calls": calls,
    }


def test_family_matrix_does_not_infer_reference_for_absent_variant_or_no_call():
    case_id, father_id, proband_id = uuid4(), uuid4(), uuid4()
    observed_variant, absent_variant = uuid4(), uuid4()
    father = _sample(father_id, "FATHER", {
        observed_variant: {
            "sample_name": "FATHER",
            "genotype": "./.",
            "normalized_genotype": "./.",
            "missing_allele_count": 2,
            "format_values": {"DP": "18", "GQ": "0"},
        },
    })
    proband = _sample(proband_id, "PROBAND", {
        observed_variant: {
            "sample_name": "PROBAND",
            "source_genotype": "0|1",
            "normalized_genotype": "0|1",
            "normalized_zygosity": "HET",
            "selected_alt_dosage": 1,
            "reference_allele_dosage": 1,
            "phase": "PHASED",
            "phase_set": "1200",
            "format_values": {"DP": "42", "GQ": "99", "AD": [20, 22]},
            "source_record_sha256": "c" * 64,
            "source_record_index": 7,
        },
    })

    matrix = build_family_genotype_matrix(
        case_id=case_id,
        variant_ids=[observed_variant, absent_variant],
        samples=[proband, father],
        relationships=[{
            "parent_member_identifier": "FATHER",
            "child_member_identifier": "PROBAND",
            "relationship_type": "PARENT_CHILD",
            "relationship_status": "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
        }],
    )

    by_member = {sample["member_identifier"]: sample for sample in matrix["samples"]}
    father_calls = {row["variant_id"]: row for row in by_member["FATHER"]["calls"]}
    proband_calls = {row["variant_id"]: row for row in by_member["PROBAND"]["calls"]}

    assert father_calls[str(observed_variant)]["call_state"] == "NO_CALL"
    assert father_calls[str(observed_variant)]["callability"] == "NOT_ASSESSED"
    assert father_calls[str(absent_variant)]["call_state"] == "NO_RECORD"
    assert father_calls[str(absent_variant)]["reference_allele_dosage"] is None
    assert proband_calls[str(observed_variant)]["call_state"] == "CALL_PRESENT"
    assert proband_calls[str(observed_variant)]["phase"] == "PHASED"
    assert proband_calls[str(observed_variant)]["phase_set"] == "1200"
    assert proband_calls[str(observed_variant)]["quality_metrics"] == {
        "DP": "42", "GQ": "99", "AD": [20, 22],
    }
    assert proband_calls[str(observed_variant)]["source_record_sha256"] == "c" * 64
    assert matrix["interpretation_status"] == "NOT_PERFORMED"
    assert matrix["biological_relatedness_status"] == "NOT_ESTABLISHED"


def test_family_matrix_fingerprint_is_independent_of_sample_input_order():
    case_id, member_a, member_b, variant_id = (uuid4() for _ in range(4))
    a = _sample(member_a, "A", {variant_id: {"sample_name": "A", "genotype": "0/1"}})
    b = _sample(member_b, "B", {variant_id: {"sample_name": "B", "genotype": "0/0"}})
    relationships = [{
        "parent_member_identifier": "A",
        "child_member_identifier": "B",
        "relationship_type": "PARENT_CHILD",
    }]
    first = build_family_genotype_matrix(
        case_id=case_id, variant_ids=[variant_id], samples=[a, b], relationships=relationships,
    )
    second = build_family_genotype_matrix(
        case_id=case_id, variant_ids=[variant_id], samples=[b, a], relationships=relationships,
    )
    assert first["matrix_fingerprint"] == second["matrix_fingerprint"]


def test_family_matrix_rejects_multiple_bindings_for_one_member():
    case_id, member_id, variant_id = uuid4(), uuid4(), uuid4()
    a = _sample(member_id, "MEMBER", {})
    b = _sample(member_id, "MEMBER", {})
    with pytest.raises(ValueError, match="at most one"):
        build_family_genotype_matrix(
            case_id=case_id, variant_ids=[variant_id], samples=[a, b], relationships=[],
        )
