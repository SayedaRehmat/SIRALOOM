from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from backend.app.adapters.phenotype.fhir_r5 import build_fhir_r5_bundle


def _case():
    return SimpleNamespace(id=uuid4(), case_identifier="CASE-FHIR-1")


def _observation(*, status="PRESENT", subject_member_id=None, attributes=None):
    return SimpleNamespace(
        id=uuid4(),
        subject_member_id=subject_member_id,
        hpo_id="HP:0001250",
        label="Seizures",
        phenotype_status=status,
        observed_at=datetime(2025, 3, 1, tzinfo=UTC),
        created_at=datetime(2025, 3, 2, tzinfo=UTC),
        clinical_attributes=attributes or {},
        ontology_resolution={
            "primary_term": {
                "input_id": "HP:0001250",
                "status": "CURRENT",
                "canonical_id": "HP:0001250",
                "label": "Seizures",
            },
            "related_terms": [],
            "resource": {
                "resource_id": "hpo-resource",
                "ontology_release": "2026-10-01",
                "ontology_sha256": "a" * 64,
                "qualification_id": "hpo-qualification",
                "contract_hash": "b" * 64,
            },
        },
        source="CLINICAL_INPUT",
        evidence={},
    )


def _member(identifier, *, sex="UNKNOWN", affected="UNKNOWN", proband=False, relationship=None, metadata=None):
    return SimpleNamespace(
        id=uuid4(),
        member_identifier=identifier,
        sex=sex,
        affected_status=affected,
        is_proband=proband,
        relationship_to_proband=relationship,
        sampled=False,
        specimen_id=None,
        metadata_json=metadata or {},
    )


def _resources(bundle):
    return [entry["resource"] for entry in bundle["entry"]]


def test_fhir_r5_bundle_uses_observation_and_never_promotes_phenotype_to_condition():
    bundle = build_fhir_r5_bundle(
        case=_case(),
        phenotype_observations=[_observation()],
    )

    resources = _resources(bundle)
    observations = [item for item in resources if item["resourceType"] == "Observation"]
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert len(observations) == 1
    assert observations[0]["status"] == "preliminary"
    assert observations[0]["code"]["coding"][0]["system"] == "http://purl.obolibrary.org/obo/hp.owl"
    assert observations[0]["valueBoolean"] is True
    assert not any(item["resourceType"] == "Condition" for item in resources)


def test_fhir_r5_preserves_absent_excluded_unknown_and_not_assessed_semantics():
    rows = [
        _observation(status="ABSENT"),
        _observation(status="EXCLUDED"),
        _observation(status="UNKNOWN"),
        _observation(status="NOT_ASSESSED"),
    ]
    bundle = build_fhir_r5_bundle(case=_case(), phenotype_observations=rows)
    observations = {
        next(ext["valueCode"] for ext in item["extension"] if ext["url"].endswith("/phenotype-status")): item
        for item in _resources(bundle)
        if item["resourceType"] == "Observation"
    }

    assert observations["ABSENT"]["valueBoolean"] is False
    assert observations["EXCLUDED"]["valueBoolean"] is False
    assert observations["UNKNOWN"]["dataAbsentReason"]["coding"][0]["code"] == "unknown"
    assert observations["NOT_ASSESSED"]["dataAbsentReason"]["coding"][0]["code"] == "not-performed"


def test_fhir_r5_family_observation_is_attributed_to_relative_not_proband():
    proband = _member("PROBAND", sex="MALE", affected="AFFECTED", proband=True)
    mother = _member("MOTHER", sex="FEMALE", affected="UNAFFECTED", relationship="mother")
    bundle = build_fhir_r5_bundle(
        case=_case(),
        phenotype_observations=[_observation(subject_member_id=mother.id)],
        pedigree_members=[proband, mother],
    )

    resources = _resources(bundle)
    observation = next(item for item in resources if item["resourceType"] == "Observation")
    assert observation["subject"]["reference"] == f"Patient/{proband.id}"
    assert observation["focus"][0]["reference"] == f"RelatedPerson/{mother.id}"
    assert any(item["resourceType"] == "FamilyMemberHistory" for item in resources)


def test_fhir_r5_preserves_parent_child_relationships_as_explicit_extensions():
    father = _member(
        "FATHER",
        sex="MALE",
        affected="UNAFFECTED",
        relationship="father",
        metadata={"consanguinity_reported": True},
    )
    proband = _member("PROBAND", sex="MALE", affected="AFFECTED", proband=True)
    relationship = SimpleNamespace(
        parent_member_id=father.id,
        child_member_id=proband.id,
        relationship_type="PARENT_CHILD",
        metadata_json={"source": "family_report"},
    )
    bundle = build_fhir_r5_bundle(
        case=_case(),
        phenotype_observations=[],
        pedigree_members=[father, proband],
        pedigree_relationships=[relationship],
    )

    resources = _resources(bundle)
    patient = next(item for item in resources if item["resourceType"] == "Patient")
    father_resource = next(
        item for item in resources
        if item["resourceType"] == "RelatedPerson" and item["id"] == str(father.id)
    )
    assert any(ext["url"].endswith("/pedigree-parent") for ext in patient["extension"])
    assert any(ext["url"].endswith("/pedigree-child") for ext in father_resource["extension"])
    assert any(ext["url"].endswith("/pedigree-member-metadata") for ext in father_resource["extension"])
    assert any(ext["url"].endswith("/pedigree-relationship-metadata") for ext in patient["extension"])


def test_fhir_r5_preserves_patient_specific_episode_frequency_in_extension():
    observation = _observation(attributes={
        "episode_frequency": {
            "count": 3,
            "period_value": 2,
            "period_unit": "WEEKS",
        }
    })
    bundle = build_fhir_r5_bundle(case=_case(), phenotype_observations=[observation])
    resource = next(item for item in _resources(bundle) if item["resourceType"] == "Observation")
    frequency = next(ext for ext in resource["extension"] if ext["url"].endswith("/episode-frequency"))
    values = {item["url"]: item for item in frequency["extension"]}
    assert values["count"]["valueInteger"] == 3
    assert values["period-value"]["valueDecimal"] == 2
    assert values["period-unit"]["valueCode"] == "WEEKS"


def test_fhir_r5_family_export_requires_one_explicit_proband():
    member = _member("RELATIVE")
    try:
        build_fhir_r5_bundle(
            case=_case(),
            phenotype_observations=[],
            pedigree_members=[member],
        )
    except ValueError as exc:
        assert "exactly one explicitly designated proband" in str(exc)
    else:
        raise AssertionError("Family export must not infer a proband.")


def test_fhir_r5_preserves_versioned_clinical_intake_and_differentials_without_diagnosis_conversion():
    revision = SimpleNamespace(
        id=uuid4(),
        version=4,
        schema_version=1,
        revision_fingerprint="d" * 64,
        intake_status="COMPLETE",
        phenotype_review_status="COMPLETE",
        family_history_review_status="NOT_ASSESSED",
        phenotype_review_note=None,
        family_history_review_note="Family history unavailable from referral source.",
        completion_note=None,
        recorded_at=datetime(2026, 10, 20, tzinfo=UTC),
        context={
            "referral_indication": "Unexplained seizures",
            "referral_question": "Evaluate a suspected inherited epilepsy",
            "clinical_summary": "Recurrent seizures since early childhood.",
            "age_at_assessment": {
                "value": 7,
                "unit": "YEARS",
                "as_of_date": "2026-10-15",
            },
            "prior_testing": [{
                "test_type": "Chromosomal microarray",
                "performed_at": "2024-05-01",
                "laboratory": "Regional genetics laboratory",
                "accession_reference": "LAB-2024-001",
                "result_status": "NEGATIVE",
                "result_summary": "No reportable copy-number finding.",
                "source_reference": "REPORT-001",
                "artifact_id": str(uuid4()),
            }],
            "differential_diagnoses": [{
                "system": "http://snomed.info/sct",
                "code": "84757009",
                "display": "Epilepsy",
                "certainty": "SUSPECTED",
                "clinical_status": "ACTIVE",
            }],
            "source_document_references": ["REFERRAL-001"],
        },
    )
    bundle = build_fhir_r5_bundle(
        case=_case(),
        phenotype_observations=[_observation()],
        clinical_intake_revision=revision,
    )

    resources = _resources(bundle)
    patient = next(item for item in resources if item["resourceType"] == "Patient")
    intake = next(
        item for item in patient["extension"]
        if item["url"].endswith("/clinical-intake-revision")
    )
    fields = {item["url"].rsplit("/", 1)[-1]: item for item in intake["extension"]}
    assert fields["revision-version"]["valueInteger"] == 4
    assert fields["intake-status"]["valueCode"] == "COMPLETE"
    assert fields["referral-indication"]["valueString"] == "Unexplained seizures"
    age = next(item for item in intake["extension"] if item["url"].endswith("/age-at-assessment"))
    age_fields = {item["url"]: item for item in age["extension"]}
    assert age_fields["value"]["valueDecimal"] == 7
    assert age_fields["unit"]["valueCode"] == "YEARS"
    prior = next(item for item in intake["extension"] if item["url"].endswith("/prior-testing"))
    assert any(item["url"] == "result-status" and item["valueCode"] == "NEGATIVE" for item in prior["extension"])
    differential = next(item for item in intake["extension"] if item["url"].endswith("/differential-diagnosis"))
    assert any(item["url"] == "certainty" and item["valueString"] == "SUSPECTED" for item in differential["extension"])
    assert not any(item["resourceType"] == "Condition" for item in resources)
