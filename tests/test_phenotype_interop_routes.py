import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.app.api.v1 import phenotypes as phenotype_api
from backend.app.auth.principal import Principal


class _FakeDB:
    def __init__(self, case, revision):
        self.case = case
        self.revision = revision
        self.committed = False

    def get(self, model, object_id):
        assert object_id == self.case.id
        return self.case

    def scalars(self, _query):
        return []

    def scalar(self, _query):
        return self.revision

    def commit(self):
        self.committed = True


class _FakeAudit:
    calls = []

    def __init__(self, _db):
        pass

    def record(self, **kwargs):
        self.calls.append(kwargs)


def _context():
    case = SimpleNamespace(id=uuid4(), case_identifier="INTEROP-CASE")
    revision = SimpleNamespace(
        id=uuid4(),
        version=2,
        schema_version=1,
        revision_fingerprint="a" * 64,
        intake_status="COMPLETE",
        phenotype_review_status="COMPLETE",
        family_history_review_status="NOT_ASSESSED",
        context={
            "referral_indication": "Unexplained seizures",
            "prior_testing": [{
                "test_type": "Chromosomal microarray",
                "artifact_id": str(uuid4()),
                "source_reference": "LAB-REPORT-1",
            }],
        },
        phenotype_review_note=None,
        family_history_review_note="No family history supplied.",
        completion_note=None,
        recorded_at=datetime(2026, 10, 20, tzinfo=UTC),
        recorded_by=uuid4(),
    )
    principal = Principal(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="clinical_geneticist",
        subject="interop-test",
    )
    return case, revision, principal


def test_phenopackets_endpoint_returns_schema_document_and_revision_sidecar(monkeypatch):
    case, revision, principal = _context()
    db = _FakeDB(case, revision)
    _FakeAudit.calls = []
    captured = {}

    monkeypatch.setattr(phenotype_api, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(phenotype_api, "AuditService", _FakeAudit)

    def fake_build(**kwargs):
        captured.update(kwargs)
        return {"id": "GA4GH-PACKET"}, [{"field": "clinical_intake.referral_indication"}]

    monkeypatch.setattr(phenotype_api, "build_phenopackets_v2", fake_build)
    result = phenotype_api.export_case_phenopackets_v2(
        case_id=case.id,
        allow_lossy=True,
        db=db,
        principal=principal,
    )

    assert captured["clinical_intake_revision"] is revision
    assert result["document"]["id"] == "GA4GH-PACKET"
    assert result["clinical_intake_revision"]["version"] == revision.version
    assert result["clinical_intake_revision"]["revision_fingerprint"] == revision.revision_fingerprint
    assert "revision_id" not in result["clinical_intake_revision"]
    assert "recorded_by" not in result["clinical_intake_revision"]
    prior_test = result["clinical_intake_revision"]["context"]["prior_testing"][0]
    assert "artifact_id" not in prior_test
    assert prior_test["artifact_reference_present"] is True
    assert db.committed is True
    assert _FakeAudit.calls[0]["after_state"]["clinical_intake_revision_id"] == str(revision.id)


def test_fhir_endpoint_passes_revision_to_bundle_builder_and_audits_export(monkeypatch):
    case, revision, principal = _context()
    db = _FakeDB(case, revision)
    _FakeAudit.calls = []
    captured = {}

    monkeypatch.setattr(phenotype_api, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(phenotype_api, "AuditService", _FakeAudit)

    def fake_build(**kwargs):
        captured.update(kwargs)
        return {"resourceType": "Bundle", "type": "collection", "entry": []}

    monkeypatch.setattr(phenotype_api, "build_fhir_r5_bundle", fake_build)
    result = phenotype_api.export_case_phenotypes_fhir_r5(
        case_id=case.id,
        db=db,
        principal=principal,
    )

    assert captured["clinical_intake_revision"] is revision
    payload = json.loads(result.body)
    assert result.media_type == "application/fhir+json"
    assert payload["resourceType"] == "Bundle"
    assert db.committed is True
    assert _FakeAudit.calls[0]["after_state"]["clinical_intake_revision_version"] == 2


def test_phenotype_export_sidecar_preserves_source_semantics_without_internal_foreign_keys():
    member_id = uuid4()
    member = SimpleNamespace(id=member_id, member_identifier="SIBLING-1")
    observation = SimpleNamespace(
        id=uuid4(),
        record_fingerprint="e" * 64,
        subject_member_id=member_id,
        hpo_id="HP:0001250",
        canonical_hpo_id="HP:0001250",
        label="Seizures",
        phenotype_status="ABSENT",
        present=False,
        onset="childhood",
        severity="mild",
        observed_at=datetime(2025, 1, 1, tzinfo=UTC),
        created_at=datetime(2025, 1, 2, tzinfo=UTC),
        clinical_attributes={"laterality": "BILATERAL"},
        ontology_resolution={
            "primary_term": {"status": "CURRENT"},
            "resource": {
                "resource_id": str(uuid4()),
                "qualification_id": str(uuid4()),
                "resource_checksum": "sha256:abcd",
            },
        },
        source="FAMILY_HISTORY",
        evidence={"source_note": "reported by family", "analysis_id": str(uuid4())},
        analysis_id=uuid4(),
    )

    result = phenotype_api._phenotype_export_sidecar([observation], [member])

    assert result[0]["subject_member_identifier"] == "SIBLING-1"
    assert result[0]["phenotype_status"] == "ABSENT"
    assert "observation_id" not in result[0]
    assert result[0]["clinical_attributes"]["laterality"] == "BILATERAL"
    assert result[0]["evidence"]["source_note"] == "reported by family"
    assert "analysis_id" not in result[0]["evidence"]
    assert "resource_id" not in result[0]["ontology_resolution"]["resource"]
    assert "qualification_id" not in result[0]["ontology_resolution"]["resource"]
    assert result[0]["ontology_resolution"]["resource"]["resource_checksum"] == "sha256:abcd"
    assert "subject_member_id" not in result[0]


def test_pedigree_sidecar_uses_pseudonymous_subjects_and_sanitizes_internal_keys():
    case = SimpleNamespace(clinical_context={})
    father_id = uuid4()
    proband_id = uuid4()
    father = SimpleNamespace(
        id=father_id,
        member_identifier="FATHER",
        relationship_to_proband="father",
        sex="MALE",
        affected_status="UNAFFECTED",
        is_proband=False,
        sampled=True,
        specimen_id=uuid4(),
        metadata_json={
            "consanguinous_parents": False,
            "analysis_id": str(uuid4()),
            "family_note": "Reported by proband",
        },
    )
    proband = SimpleNamespace(
        id=proband_id,
        member_identifier="PROBAND",
        relationship_to_proband=None,
        sex="FEMALE",
        affected_status="AFFECTED",
        is_proband=True,
        sampled=False,
        specimen_id=None,
        metadata_json={},
    )
    relationship = SimpleNamespace(
        parent_member_id=father_id,
        child_member_id=proband_id,
        relationship_type="PARENT_CHILD",
        metadata_json={"consanguinous_parents": False, "parent_member_id": str(father_id)},
    )

    result = phenotype_api._pedigree_export_sidecar(
        case, [father, proband], [relationship], None
    )

    father_export = next(item for item in result["members"] if item["member_identifier"] == "FATHER")
    assert father_export["phenopacket_subject_id"] == (
        f"SIRALOOM:{uuid5(NAMESPACE_URL, f'siraloom:pedigree-member:{father_id}')}"
    )
    assert father_export["specimen_reference_present"] is True
    assert "analysis_id" not in father_export["metadata"]
    assert "parent_member_id" not in result["relationships"][0]["metadata"]
    assert str(father_id) not in str(result)
    assert result["consanguinous_parents"] is False
