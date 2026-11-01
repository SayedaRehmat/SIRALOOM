from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from backend.app.api.v1 import cases as cases_api
from backend.app.auth.principal import Principal
from backend.app.domain.case_workspace import SpecimenPloidyEvidenceCreate


def test_specimen_ploidy_evidence_schema_rejects_boolean_copy_number():
    with pytest.raises(ValidationError):
        SpecimenPloidyEvidenceCreate(
            reference_build="GRCh38",
            status="VERIFIED",
            region_copy_number={"X_NON_PAR": True},
            source_type="CYTOGENETIC_REPORT",
            evidence_reference="artifact:sha256:" + "a" * 64,
        )


def test_specimen_ploidy_evidence_schema_forbids_inferred_sex_or_karyotype_fields():
    with pytest.raises(ValidationError):
        SpecimenPloidyEvidenceCreate(
            reference_build="GRCh38",
            status="VERIFIED",
            region_copy_number={"X_NON_PAR": 1},
            source_type="CYTOGENETIC_REPORT",
            evidence_reference="report-123",
            karyotype="46,XY",
        )


def test_specimen_ploidy_evidence_migration_creates_immutable_versioned_table(tmp_path, monkeypatch):
    database = tmp_path / "specimen-ploidy-evidence.sqlite"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0059_specimen_ploidy_evidence")
    engine = create_engine(url)
    with engine.connect() as connection:
        inspector = inspect(connection)
        columns = {column["name"] for column in inspector.get_columns("specimen_ploidy_evidence_revisions")}
        assert {
            "specimen_id", "version", "schema_version", "revision_fingerprint",
            "reference_build", "status", "region_copy_number", "source_type",
            "evidence_reference", "reviewed_by", "reviewed_at", "recorded_by",
            "recorded_at", "audit_event_id",
        }.issubset(columns)
        unique_constraints = {item["name"] for item in inspector.get_unique_constraints("specimen_ploidy_evidence_revisions")}
        assert "uq_specimen_ploidy_evidence_version" in unique_constraints
        assert "uq_specimen_ploidy_evidence_fingerprint" in unique_constraints
        triggers = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='specimen_ploidy_evidence_revisions'"
        )).scalars().all()
        assert set(triggers) == {
            "trg_specimen_ploidy_evidence_no_update",
            "trg_specimen_ploidy_evidence_no_delete",
        }
    engine.dispose()


def test_specimen_ploidy_evidence_migration_rejects_update_and_delete(tmp_path, monkeypatch):
    database = tmp_path / "specimen-ploidy-immutable.sqlite"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0059_specimen_ploidy_evidence")
    engine = create_engine(url)
    with engine.begin() as connection:
        # A minimal row is sufficient to exercise the database-level mutation guard.
        organization_id = uuid4()
        user_id = uuid4()
        case_id = uuid4()
        specimen_id = uuid4()
        audit_id = uuid4()
        connection.execute(text("INSERT INTO organizations (id, name, created_at, updated_at) VALUES (:id, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"id": str(organization_id)})
        connection.execute(text(
            "INSERT INTO users (id, organization_id, display_name, role, status, created_at, updated_at) "
            "VALUES (:id, :org, 'Reviewer', 'lab_director', 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"id": str(user_id), "org": str(organization_id)})
        connection.execute(text(
            "INSERT INTO cases (id, organization_id, case_identifier, status, language, created_by) "
            "VALUES (:id, :org, 'CASE-1', 'DRAFT', 'en', :user)"
        ), {"id": str(case_id), "org": str(organization_id), "user": str(user_id)})
        connection.execute(text(
            "INSERT INTO specimens (id, case_id, specimen_identifier, metadata, created_at) VALUES (:id, :case, 'SPEC-1', '{}', CURRENT_TIMESTAMP)"
        ), {"id": str(specimen_id), "case": str(case_id)})
        connection.execute(text(
            "INSERT INTO audit_events (id, event_version, event_type, actor_type, actor_id, "
            "input_artifacts, output_artifacts, software, workflow, resource_versions, payload, occurred_at) "
            "VALUES (:id, '1.0', 'TEST', 'HUMAN', :actor, '[]', '[]', '{}', '{}', '{}', '{}', CURRENT_TIMESTAMP)"
        ), {"id": str(audit_id), "actor": str(user_id)})
        connection.execute(text(
            "INSERT INTO specimen_ploidy_evidence_revisions "
            "(id, specimen_id, version, schema_version, revision_fingerprint, reference_build, status, "
            "region_copy_number, reviewed_by, reviewed_at, recorded_by, audit_event_id) "
            "VALUES (:id, :specimen, 1, 1, :fingerprint, 'GRCh38', 'VERIFIED', "
            "'{\"X_NON_PAR\":1}', :reviewer, CURRENT_TIMESTAMP, :recorder, :audit)"
        ), {
            "id": str(uuid4()), "specimen": str(specimen_id), "fingerprint": "a" * 64,
            "reviewer": str(user_id), "recorder": str(user_id), "audit": str(audit_id),
        })
    with engine.begin() as connection:
        with pytest.raises(Exception, match="append-only"):
            connection.execute(text(
                "UPDATE specimen_ploidy_evidence_revisions SET status='CONFLICTED' WHERE specimen_id=:id"
            ), {"id": str(specimen_id)})
    with engine.begin() as connection:
        with pytest.raises(Exception, match="append-only"):
            connection.execute(text(
                "DELETE FROM specimen_ploidy_evidence_revisions WHERE specimen_id=:id"
            ), {"id": str(specimen_id)})
    engine.dispose()


class _EvidenceSession:
    def __init__(self, case, specimen, existing=None):
        self.case = case
        self.specimen = specimen
        self.existing = existing
        self.added = []
        self.scalar_calls = 0
        self.committed = False

    def get(self, model, identity, **kwargs):
        if model.__name__ == "Case":
            assert kwargs.get("with_for_update") is True
            return self.case
        if model.__name__ == "Specimen":
            assert kwargs.get("with_for_update") is True
            return self.specimen
        raise AssertionError(model)

    def scalar(self, statement):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return self.existing
        return None

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True

    def refresh(self, row, **kwargs):
        # The fake session has no identity map.
        return None

    def rollback(self):
        pass


class _AuditRecorder:
    event_id = uuid4()
    calls = []

    def __init__(self, db):
        self.db = db

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return self.event_id


def test_verified_specimen_ploidy_evidence_is_persisted_with_review_and_audit_provenance(monkeypatch):
    organization_id = uuid4()
    case_id = uuid4()
    specimen_id = uuid4()
    user_id = uuid4()
    case = SimpleNamespace(id=case_id, organization_id=organization_id)
    specimen = SimpleNamespace(id=specimen_id, case_id=case_id)
    db = _EvidenceSession(case, specimen)
    _AuditRecorder.calls = []
    monkeypatch.setattr(cases_api, "AuditService", _AuditRecorder)
    permissions = []
    monkeypatch.setattr(cases_api, "require_case_permission", lambda _case, _principal, _db, permission: permissions.append(permission))
    monkeypatch.setattr(cases_api, "require_role", lambda *_args: None)

    result = cases_api.record_specimen_ploidy_evidence(
        case_id=case_id,
        specimen_id=specimen_id,
        payload=SpecimenPloidyEvidenceCreate(
            reference_build="GRCh38",
            status="VERIFIED",
            region_copy_number={"PAR": 2, "X_NON_PAR": 1, "Y_NON_PAR": 1},
            source_type="CYTOGENETIC_REPORT",
            evidence_reference="artifact:sha256:" + "b" * 64,
        ),
        db=db,
        principal=Principal(
            user_id=user_id,
            organization_id=organization_id,
            role="lab_director",
            subject="reviewer-subject",
        ),
    )

    revision = db.added[0]
    assert result["version"] == 1
    assert result["status"] == "VERIFIED"
    assert result["reviewed_by"] == str(user_id)
    assert result["reviewed_at"] is not None
    assert revision.recorded_by == user_id
    assert revision.reviewed_by == user_id
    assert revision.audit_event_id == _AuditRecorder.event_id
    assert db.committed is True
    assert permissions == ["review"]
    assert _AuditRecorder.calls[0]["event_type"] == "SPECIMEN_PLOIDY_EVIDENCE_RECORDED"
