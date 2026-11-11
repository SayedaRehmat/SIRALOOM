from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from backend.app.adapters.phenotype.phenopackets_v2 import (
    PhenopacketExportError,
    build_phenopackets_v2,
)


def _case():
    return SimpleNamespace(id=uuid4(), case_identifier="CASE-001")


def _observation(*, status="PRESENT", subject_member_id=None, attributes=None, resolution=None):
    return SimpleNamespace(
        id=uuid4(),
        case_id=None,
        subject_member_id=subject_member_id,
        hpo_id="HP:0001250",
        canonical_hpo_id="HP:0001250",
        label="Seizures",
        phenotype_status=status,
        onset=None,
        severity=None,
        clinical_attributes=attributes or {},
        ontology_resolution=resolution or {
            "primary_term": {
                "input_id": "HP:0001250",
                "status": "CURRENT",
                "canonical_id": "HP:0001250",
                "label": "Seizures",
            },
            "related_terms": [],
            "resource": {
                "ontology_release": "2026-10-01",
                "resource_checksum": "a" * 64,
            },
        },
        source="CLINICAL_INPUT",
        evidence={},
    )


def _member(identifier, *, sex="UNKNOWN", affected="UNKNOWN", proband=False, relationship=None, sampled=False, specimen_id=None, metadata=None):
    return SimpleNamespace(
        id=uuid4(),
        member_identifier=identifier,
        sex=sex,
        affected_status=affected,
        is_proband=proband,
        relationship_to_proband=relationship,
        sampled=sampled,
        specimen_id=specimen_id,
        metadata_json=metadata or {},
    )


def test_single_patient_export_is_validated_against_ga4gh_protobuf_schema():
    payload, warnings = build_phenopackets_v2(
        case=_case(),
        phenotype_observations=[_observation()],
    )

    assert warnings == []
    assert payload["metaData"]["phenopacketSchemaVersion"] == "2.0"
    assert payload["metaData"]["resources"][0]["version"] == (
        "http://purl.obolibrary.org/obo/hp/releases/2026-10-01/hp.obo"
    )
    assert payload["subject"]["id"].startswith("SIRALOOM:")
    assert payload["phenotypicFeatures"][0]["type"]["id"] == "HP:0001250"
    assert payload["phenotypicFeatures"][0]["type"]["label"] == "Seizures"
    assert "description" not in payload["phenotypicFeatures"][0]
    assert payload["phenotypicFeatures"][0].get("excluded", False) is False


def test_family_export_preserves_member_attribution_and_parentage():
    father = _member("FATHER", sex="MALE", affected="UNAFFECTED")
    mother = _member("MOTHER", sex="FEMALE", affected="UNAFFECTED")
    proband = _member("PROBAND", sex="MALE", affected="AFFECTED", proband=True)
    relationships = [
        SimpleNamespace(
            parent_member_id=father.id,
            child_member_id=proband.id,
            relationship_type="PARENT_CHILD",
            metadata_json={"consanguinous_parents": False},
        ),
        SimpleNamespace(
            parent_member_id=mother.id,
            child_member_id=proband.id,
            relationship_type="PARENT_CHILD",
            metadata_json={},
        ),
    ]
    observations = [
        _observation(subject_member_id=proband.id),
        _observation(subject_member_id=father.id),
    ]

    payload, warnings = build_phenopackets_v2(
        case=_case(),
        phenotype_observations=observations,
        pedigree_members=[father, mother, proband],
        pedigree_relationships=relationships,
    )

    assert warnings == []
    proband_id = f"SIRALOOM:{uuid5(NAMESPACE_URL, f'siraloom:pedigree-member:{proband.id}')}"
    father_id = f"SIRALOOM:{uuid5(NAMESPACE_URL, f'siraloom:pedigree-member:{father.id}')}"
    mother_id = f"SIRALOOM:{uuid5(NAMESPACE_URL, f'siraloom:pedigree-member:{mother.id}')}"
    assert payload["proband"]["subject"]["id"] == proband_id
    assert len(payload["relatives"]) == 1
    persons = {person["individualId"]: person for person in payload["pedigree"]["persons"]}
    assert persons[proband_id]["paternalId"] == father_id
    assert persons[proband_id]["maternalId"] == mother_id
    assert persons[father_id]["paternalId"] == "0"
    assert persons[father_id]["maternalId"] == "0"
    assert persons[mother_id]["paternalId"] == "0"
    assert persons[mother_id]["maternalId"] == "0"
    assert persons[proband_id]["affectedStatus"] == "AFFECTED"


def test_strict_export_rejects_states_that_ga4gh_cannot_represent():
    with pytest.raises(PhenopacketExportError, match="phenotype_status"):
        build_phenopackets_v2(
            case=_case(),
            phenotype_observations=[_observation(status="UNKNOWN")],
        )


def test_lossy_export_omits_unknown_states_instead_of_encoding_them_as_present():
    payload, warnings = build_phenopackets_v2(
        case=_case(),
        phenotype_observations=[
            _observation(status="UNKNOWN"),
            _observation(status="PRESENT"),
        ],
        allow_lossy=True,
    )

    assert len(payload["phenotypicFeatures"]) == 1
    assert payload["phenotypicFeatures"][0].get("excluded", False) is False
    assert any(item["field"] == "phenotype_status" for item in warnings)


def test_strict_export_rejects_excluded_vs_absent_collapse():
    with pytest.raises(PhenopacketExportError, match="phenotype_status"):
        build_phenopackets_v2(
            case=_case(),
            phenotype_observations=[_observation(status="EXCLUDED")],
        )


def test_family_export_requires_explicit_single_proband():
    member = _member("MEMBER", sex="MALE")
    with pytest.raises(PhenopacketExportError, match="exactly one explicitly designated proband"):
        build_phenopackets_v2(
            case=_case(),
            phenotype_observations=[],
            pedigree_members=[member],
        )


def test_family_export_does_not_guess_parent_role_from_unknown_sex():
    parent = _member("PARENT", sex="UNKNOWN")
    child = _member("CHILD", sex="FEMALE", proband=True)
    relationship = SimpleNamespace(
        parent_member_id=parent.id,
        child_member_id=child.id,
        relationship_type="PARENT_CHILD",
    )
    with pytest.raises(PhenopacketExportError, match="without a recorded MALE/FEMALE parent sex"):
        build_phenopackets_v2(
            case=_case(),
            phenotype_observations=[],
            pedigree_members=[parent, child],
            pedigree_relationships=[relationship],
        )


def test_family_export_rejects_non_parent_child_relationships():
    parent = _member("PARENT", sex="MALE")
    child = _member("CHILD", sex="FEMALE", proband=True)
    relationship = SimpleNamespace(
        parent_member_id=parent.id,
        child_member_id=child.id,
        relationship_type="GUARDIAN",
    )
    with pytest.raises(PhenopacketExportError, match="no equivalent"):
        build_phenopackets_v2(
            case=_case(),
            phenotype_observations=[],
            pedigree_members=[parent, child],
            pedigree_relationships=[relationship],
        )


def test_family_observation_cannot_reference_member_outside_case():
    proband = _member("PROBAND", sex="FEMALE", proband=True)
    with pytest.raises(PhenopacketExportError, match="outside this case"):
        build_phenopackets_v2(
            case=_case(),
            phenotype_observations=[_observation(subject_member_id=uuid4())],
            pedigree_members=[proband],
        )


def test_non_equivalent_clinical_attributes_are_reported_not_silently_dropped():
    row = _observation(attributes={"episode_frequency": {"count": 3, "period_value": 1, "period_unit": "WEEKS"}})
    with pytest.raises(PhenopacketExportError, match="episode_frequency"):
        build_phenopackets_v2(case=_case(), phenotype_observations=[row])

    payload, warnings = build_phenopackets_v2(
        case=_case(),
        phenotype_observations=[row],
        allow_lossy=True,
    )
    assert payload["phenotypicFeatures"]
    assert any(item["field"] == "clinical_attributes.episode_frequency" for item in warnings)


def test_clinical_intake_assessment_age_is_not_equated_with_last_encounter_age():
    revision = SimpleNamespace(
        id=uuid4(),
        version=3,
        schema_version=1,
        revision_fingerprint="c" * 64,
        intake_status="COMPLETE",
        phenotype_review_status="COMPLETE",
        family_history_review_status="NOT_ASSESSED",
        phenotype_review_note=None,
        family_history_review_note="Family history was not available.",
        completion_note=None,
        context={
            "referral_indication": "Unexplained seizures",
            "referral_question": "Evaluate a suspected inherited epilepsy",
            "age_at_assessment": {
                "value": 7,
                "unit": "YEARS",
                "as_of_date": "2026-10-15",
            },
            "prior_testing": [],
            "differential_diagnoses": [],
            "source_document_references": [],
        },
    )
    with pytest.raises(PhenopacketExportError, match="clinical_intake.age_at_assessment"):
        build_phenopackets_v2(
            case=_case(),
            phenotype_observations=[_observation()],
            clinical_intake_revision=revision,
        )

    payload, warnings = build_phenopackets_v2(
        case=_case(),
        phenotype_observations=[_observation()],
        clinical_intake_revision=revision,
        allow_lossy=True,
    )
    assert "timeAtLastEncounter" not in payload["subject"]
    assert any(item["field"] == "clinical_intake.referral_indication" for item in warnings)
    assert any(item["field"] == "clinical_intake.age_at_assessment" for item in warnings)


def test_family_export_reports_unmapped_pedigree_context_in_lossy_mode():
    father = _member(
        "FATHER",
        sex="MALE",
        affected="UNAFFECTED",
        relationship="father",
        sampled=True,
        specimen_id=uuid4(),
        metadata={"consanguinity_reported": True},
    )
    proband = _member("PROBAND", sex="FEMALE", affected="AFFECTED", proband=True)
    relationship = SimpleNamespace(
        parent_member_id=father.id,
        child_member_id=proband.id,
        relationship_type="PARENT_CHILD",
        metadata_json={"source": "family_report"},
    )
    with pytest.raises(PhenopacketExportError, match="pedigree"):
        build_phenopackets_v2(
            case=_case(),
            phenotype_observations=[],
            pedigree_members=[father, proband],
            pedigree_relationships=[relationship],
        )

    _, warnings = build_phenopackets_v2(
        case=_case(),
        phenotype_observations=[],
        pedigree_members=[father, proband],
        pedigree_relationships=[relationship],
        allow_lossy=True,
    )
    fields = {item["field"] for item in warnings}
    assert {
        "pedigree.relationship_to_proband",
        "pedigree.sampled",
        "pedigree.specimen_id",
        "pedigree.member_metadata",
        "pedigree.relationship_metadata",
    }.issubset(fields)


def test_family_export_preserves_explicit_consanguinity_and_refuses_to_assume_false():
    father = _member("FATHER", sex="MALE", affected="UNAFFECTED")
    proband = _member("PROBAND", sex="FEMALE", affected="AFFECTED", proband=True)
    relationship = SimpleNamespace(
        parent_member_id=father.id,
        child_member_id=proband.id,
        relationship_type="PARENT_CHILD",
        metadata_json={"consanguinous_parents": True},
    )
    payload, warnings = build_phenopackets_v2(
        case=_case(),
        phenotype_observations=[],
        pedigree_members=[father, proband],
        pedigree_relationships=[relationship],
    )
    assert payload["consanguinousParents"] is True
    assert not any(item["field"] == "pedigree.consanguinous_parents" for item in warnings)

    relationship.metadata_json = {}
    with pytest.raises(PhenopacketExportError, match="pedigree.consanguinous_parents"):
        build_phenopackets_v2(
            case=_case(),
            phenotype_observations=[],
            pedigree_members=[father, proband],
            pedigree_relationships=[relationship],
        )
