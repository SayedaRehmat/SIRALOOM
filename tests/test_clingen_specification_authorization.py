from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException


def test_clingen_global_specification_import_requires_platform_role():
    from backend.app.api.v1.clingen import ClinGenImportRequest, import_specification

    with pytest.raises(HTTPException) as exc:
        import_specification(
            ClinGenImportRequest(ruleset_id="BA1"),
            object(),
            SimpleNamespace(user_id=uuid4(), role="lab_director"),
        )
    assert exc.value.status_code == 403


def test_clingen_global_automation_validation_requires_platform_role_before_read():
    from backend.app.api.v1.clingen import ClinGenValidationRequest, validate_specification

    class ForbiddenDB:
        def get(self, *_args):
            pytest.fail("Global ClinGen row was read before role authorization")

    with pytest.raises(HTTPException) as exc:
        validate_specification(
            uuid4(),
            ClinGenValidationRequest(reason="Reviewed"),
            ForbiddenDB(),
            SimpleNamespace(user_id=uuid4(), role="clinical_geneticist"),
        )
    assert exc.value.status_code == 403


def test_clingen_validation_audit_identity_comes_from_authenticated_principal(monkeypatch):
    from backend.app.api.v1 import clingen

    user_id, specification_id = uuid4(), uuid4()
    row = SimpleNamespace(
        id=specification_id,
        validation_status="UNVALIDATED",
        validated_for_automation=False,
        validated_by=None,
        validation_reason=None,
        validation_reference=None,
        validated_at=None,
        specification_id="specification-1",
        version="1",
    )
    observed = {}

    class DB:
        def get(self, model, requested_id):
            assert model is clingen.ClinGenSpecification
            assert requested_id == specification_id
            return row

        def add(self, value):
            pass

        def commit(self):
            pass

    class Audit:
        def __init__(self, _db):
            pass

        def record(self, **kwargs):
            observed["actor_id"] = kwargs["actor_id"]

    monkeypatch.setattr(clingen, "AuditService", Audit)
    monkeypatch.setattr(
        clingen,
        "validate_snapshot_for_automation",
        lambda _row, **kwargs: {"approved_by": kwargs["approved_by"]},
    )
    clingen.validate_specification(
        specification_id,
        clingen.ClinGenValidationRequest(reason="Reviewed"),
        DB(),
        SimpleNamespace(user_id=user_id, role="platform_admin"),
    )

    assert row.validated_by == str(user_id)
    assert observed["actor_id"] == str(user_id)


def test_clingen_import_audit_identity_comes_from_authenticated_principal(monkeypatch):
    from backend.app.api.v1 import clingen

    user_id = uuid4()
    snapshot = SimpleNamespace(
        specification_id="specification-2",
        version="2",
        provider="ClinGen",
        framework="ACMG/AMP",
        source_iri="https://example.invalid/specification-2",
        modified_at=None,
        gene_scope=[],
        disease_scope=[],
        criteria={},
        raw_entity={},
        request_fingerprint="request-fingerprint",
        response_sha256="response-sha256",
        request_metadata={},
    )
    observed = {}

    class DB:
        def scalar(self, _statement):
            return None

        def add(self, row):
            observed["row"] = row

        def commit(self):
            pass

    class Client:
        pass

    class Audit:
        def __init__(self, _db):
            pass

        def record(self, **kwargs):
            observed["actor_id"] = kwargs["actor_id"]
            observed["actor_type"] = kwargs["actor_type"]

    monkeypatch.setattr(clingen, "CSpecClient", Client)
    monkeypatch.setattr(clingen, "fetch_ruleset", lambda *_args: snapshot)
    monkeypatch.setattr(clingen, "AuditService", Audit)
    clingen.import_specification(
        clingen.ClinGenImportRequest(ruleset_id="rule-set-2"),
        DB(),
        SimpleNamespace(user_id=user_id, role="platform_admin"),
    )

    assert observed["actor_id"] == str(user_id)
    assert observed["actor_type"] == "HUMAN"
