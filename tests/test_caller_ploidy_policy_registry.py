from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from backend.app.api.v1 import ploidy as ploidy_api
from backend.app.auth.principal import Principal
from backend.app.domain.ploidy_schemas import CallerPloidyPolicyCreate


def _policy_payload(**overrides):
    payload = {
        "schema_version": 1,
        "caller_id": "validated-caller",
        "caller_version": "4.2.1",
        "policy_version": "1.0.0",
        "reference_build": "GRCh38",
        "status": "QUALIFIED",
        "validation_evidence_reference": "validation-record-456",
        "region_copy_number_to_gt_ploidy": {
            "PAR": {"2": 2},
            "X_NON_PAR": {"1": 1, "2": 2},
            "Y_NON_PAR": {"0": "NOT_CALLABLE", "1": 1},
        },
    }
    payload.update(overrides)
    return payload


def test_caller_policy_schema_rejects_boolean_gt_ploidy():
    with pytest.raises(ValidationError):
        CallerPloidyPolicyCreate(**_policy_payload(
            region_copy_number_to_gt_ploidy={"X_NON_PAR": {"1": True}}
        ))


def test_caller_policy_schema_rejects_unknown_inference_fields():
    payload = _policy_payload()
    payload["sex"] = "male"
    with pytest.raises(ValidationError):
        CallerPloidyPolicyCreate(**payload)


def test_caller_policy_migration_creates_versioned_immutable_registry(tmp_path, monkeypatch):
    database = tmp_path / "caller-ploidy-policy.sqlite"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0060_caller_ploidy_policy_revisions")
    engine = create_engine(url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        columns = {column["name"] for column in inspector.get_columns("caller_ploidy_policy_revisions")}
        assert {
            "assay_id", "caller_id", "caller_version", "policy_version", "reference_build",
            "status", "schema_version", "validation_evidence_reference",
            "region_copy_number_to_gt_ploidy", "qualified_by", "qualified_at",
            "recorded_by", "recorded_at", "revision_fingerprint", "audit_event_id",
        }.issubset(columns)
        unique_constraints = {
            item["name"] for item in inspector.get_unique_constraints("caller_ploidy_policy_revisions")
        }
        assert "uq_caller_ploidy_policy_exact_version_status" in unique_constraints
        assert "uq_caller_ploidy_policy_fingerprint" in unique_constraints
        triggers = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='caller_ploidy_policy_revisions'"
        )).scalars().all()
        assert set(triggers) == {
            "trg_caller_ploidy_policy_no_update",
            "trg_caller_ploidy_policy_no_delete",
        }
    engine.dispose()


class _PolicySession:
    def __init__(self, assay, existing=None):
        self.assay = assay
        self.existing = existing
        self.added = []
        self.committed = False

    def get(self, model, identity):
        assert model.__name__ == "Assay"
        return self.assay

    def scalar(self, statement):
        return self.existing

    def scalars(self, statement):
        rows = [self.existing] if self.existing is not None else []
        return SimpleNamespace(all=lambda: rows)

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True

    def refresh(self, row):
        return None

    def rollback(self):
        return None


class _PolicyAuditRecorder:
    event_id = uuid4()
    calls = []

    def __init__(self, db):
        self.db = db

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return self.event_id


def test_qualified_caller_policy_is_bound_to_assay_and_server_attested(monkeypatch):
    organization_id = uuid4()
    assay_id = uuid4()
    user_id = uuid4()
    assay = SimpleNamespace(id=assay_id, organization_id=organization_id, status="ACTIVE")
    db = _PolicySession(assay)
    _PolicyAuditRecorder.calls = []
    monkeypatch.setattr(ploidy_api, "AuditService", _PolicyAuditRecorder)
    role_checks = []
    monkeypatch.setattr(ploidy_api, "require_role", lambda _principal, roles: role_checks.append(roles))

    result = ploidy_api.create_caller_ploidy_policy(
        assay_id=assay_id,
        payload=CallerPloidyPolicyCreate(**_policy_payload()),
        db=db,
        principal=Principal(
            user_id=user_id,
            organization_id=organization_id,
            role="lab_director",
            subject="reviewer-subject",
        ),
    )

    row = db.added[0]
    assert result["assay_id"] == str(assay_id)
    assert result["status"] == "QUALIFIED"
    assert result["qualified_by"] == str(user_id)
    assert result["qualified_at"] is not None
    assert row.assay_id == assay_id
    assert row.qualified_by == user_id
    assert row.qualified_at is not None
    assert row.audit_event_id == _PolicyAuditRecorder.event_id
    assert row.region_copy_number_to_gt_ploidy["Y_NON_PAR"]["0"] == "NOT_CALLABLE"
    assert db.committed is True
    assert role_checks
    assert _PolicyAuditRecorder.calls[0]["event_type"] == "CALLER_PLOIDY_POLICY_RECORDED"


def test_caller_policy_version_is_immutable_and_requires_version_bump_for_changed_mapping(monkeypatch):
    organization_id = uuid4()
    assay_id = uuid4()
    user_id = uuid4()
    assay = SimpleNamespace(id=assay_id, organization_id=organization_id, status="ACTIVE")
    existing = SimpleNamespace(
        status="QUALIFIED",
        revision_fingerprint="existing-fingerprint",
        region_copy_number_to_gt_ploidy={"X_NON_PAR": {"1": 1}},
    )
    db = _PolicySession(assay, existing=existing)
    monkeypatch.setattr(ploidy_api, "require_role", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        ploidy_api.create_caller_ploidy_policy(
            assay_id=assay_id,
            payload=CallerPloidyPolicyCreate(**_policy_payload(
                region_copy_number_to_gt_ploidy={"X_NON_PAR": {"1": 2}}
            )),
            db=db,
            principal=Principal(
                user_id=user_id,
                organization_id=organization_id,
                role="lab_director",
                subject="reviewer-subject",
            ),
        )

    assert error.value.status_code == 409
    assert "new policy_version" in error.value.detail or "immutable within a policy_version" in error.value.detail
    assert db.added == []



def test_draft_to_qualified_transition_keeps_identical_mapping(monkeypatch):
    organization_id = uuid4()
    assay_id = uuid4()
    user_id = uuid4()
    mapping = {
        "PAR": {"2": 2},
        "X_NON_PAR": {"1": 1, "2": 2},
        "Y_NON_PAR": {"0": "NOT_CALLABLE", "1": 1},
    }
    draft = SimpleNamespace(
        status="DRAFT",
        revision_fingerprint="draft-fingerprint",
        region_copy_number_to_gt_ploidy=mapping,
    )
    assay = SimpleNamespace(id=assay_id, organization_id=organization_id, status="ACTIVE")
    db = _PolicySession(assay, existing=draft)
    _PolicyAuditRecorder.calls = []
    monkeypatch.setattr(ploidy_api, "AuditService", _PolicyAuditRecorder)
    monkeypatch.setattr(ploidy_api, "require_role", lambda *_args: None)

    result = ploidy_api.create_caller_ploidy_policy(
        assay_id=assay_id,
        payload=CallerPloidyPolicyCreate(**_policy_payload()),
        db=db,
        principal=Principal(
            user_id=user_id,
            organization_id=organization_id,
            role="lab_director",
            subject="reviewer-subject",
        ),
    )

    assert result["status"] == "QUALIFIED"
    assert db.added[0].region_copy_number_to_gt_ploidy == mapping
    assert db.added[0].qualified_by == user_id



def test_caller_ploidy_policy_routes_are_registered_in_application_openapi():
    from backend.app.main import app

    paths = app.openapi()["paths"]
    route = "/api/v1/assays/{assay_id}/ploidy-policies"
    assert route in paths
    assert "post" in paths[route]
    assert "get" in paths[route]
