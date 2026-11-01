from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

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
        context={"referral_indication": "Unexplained seizures"},
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
    assert result["clinical_intake_revision"]["revision_id"] == str(revision.id)
    assert "recorded_by" not in result["clinical_intake_revision"]
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
    assert result["bundle"]["resourceType"] == "Bundle"
    assert result["clinical_intake_revision"]["version"] == 2
    assert db.committed is True
    assert _FakeAudit.calls[0]["after_state"]["clinical_intake_revision_version"] == 2
