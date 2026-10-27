from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from backend.app.api.v1 import phenotypes as phenotype_api
from backend.app.api.v1.phenotypes import PhenotypeInput
from backend.app.auth.principal import Principal
from backend.app.phenotype import match_hpo, normalize_terms


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"hpo_id": "HP:0001250"}, "PRESENT"),
        ({"hpo_id": "HP:0001250", "present": True}, "PRESENT"),
        ({"hpo_id": "HP:0001250", "present": False}, "ABSENT"),
        ({"hpo_id": "HP:0001250", "phenotype_status": "excluded"}, "EXCLUDED"),
        ({"hpo_id": "HP:0001250", "phenotype_status": "unknown"}, "UNKNOWN"),
        ({"hpo_id": "HP:0001250", "phenotype_status": "not_assessed"}, "NOT_ASSESSED"),
    ],
)
def test_phenotype_api_normalizes_legacy_and_explicit_states(payload, expected):
    assert PhenotypeInput(**payload).phenotype_status == expected


def test_phenotype_api_rejects_conflicting_legacy_presence_and_explicit_state():
    with pytest.raises(ValidationError, match="conflicts with legacy present flag"):
        PhenotypeInput(
            hpo_id="HP:0001250",
            phenotype_status="EXCLUDED",
            present=True,
        )


@pytest.mark.parametrize(
    ("status", "present"),
    [
        ("PRESENT", True),
        ("ABSENT", False),
        ("EXCLUDED", False),
        ("UNKNOWN", False),
        ("NOT_ASSESSED", False),
    ],
)
def test_phenotype_endpoint_persists_explicit_state_and_legacy_boolean(
    monkeypatch, status, present
):
    case_id = uuid4()
    user_id = uuid4()
    case = SimpleNamespace(id=case_id, case_identifier="PHENO-1")

    class FakeDB:
        row = None

        def get(self, model, object_id, *, with_for_update=False):
            assert object_id == case_id
            assert with_for_update is True
            return case

        def refresh(self, row, *, with_for_update=False):
            assert row is case
            assert with_for_update is True

        def scalar(self, _query):
            return None

        def add(self, row):
            self.row = row
            row.created_at = datetime.now(UTC)

        def commit(self):
            return None

    class FakeAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            return None

    monkeypatch.setattr(phenotype_api, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(phenotype_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(phenotype_api, "AuditService", FakeAudit)
    monkeypatch.setattr(phenotype_api, "create_case_change_candidates", lambda *_args, **_kwargs: None)
    db = FakeDB()

    result = phenotype_api.add_case_phenotype(
        case_id=case_id,
        body=PhenotypeInput(hpo_id="HP:0001250", phenotype_status=status),
        db=db,
        principal=Principal(
            user_id=user_id,
            organization_id=uuid4(),
            role="clinical_geneticist",
            subject="phenotype-test",
        ),
    )

    assert db.row.phenotype_status == status
    assert db.row.present is present
    assert result["phenotype_status"] == status
    assert result["present"] is (True if status == "PRESENT" else False if status in {"ABSENT", "EXCLUDED"} else None)


def test_phenotype_similarity_uses_only_present_terms():
    terms = [
        {"hpo_id": "HP:0000001", "phenotype_status": "PRESENT"},
        {"hpo_id": "HP:0000002", "phenotype_status": "ABSENT", "present": False},
        {"hpo_id": "HP:0000003", "phenotype_status": "UNKNOWN", "present": False},
        {"hpo_id": "HP:0000004", "phenotype_status": "NOT_ASSESSED", "present": False},
    ]
    assert [term.status for term in normalize_terms(terms)] == [
        "PRESENT", "ABSENT", "UNKNOWN", "NOT_ASSESSED"
    ]

    result = match_hpo(terms, ["HP:0000001", "HP:0000002", "HP:0000003", "HP:0000004"])

    assert result.query_count == 1
    assert result.target_count == 4
    assert result.matched == ("HP:0000001",)
    assert result.score == 1.0


def test_phenotype_state_migration_backfills_and_keeps_states_distinct(tmp_path, monkeypatch):
    database = tmp_path / "phenotype-state-migration.sqlite"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0049_case_access_role_capabilities")

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO phenotype_observations "
            "(id, case_id, analysis_id, hpo_id, label, present, onset, severity, source, evidence, created_at) "
            "VALUES (:id, :case_id, NULL, :hpo_id, NULL, :present, NULL, NULL, 'TEST', '{}', CURRENT_TIMESTAMP)"
        ), [
            {"id": "10000000-0000-0000-0000-000000000001", "case_id": "20000000-0000-0000-0000-000000000001", "hpo_id": "HP:0000001", "present": True},
            {"id": "10000000-0000-0000-0000-000000000002", "case_id": "20000000-0000-0000-0000-000000000001", "hpo_id": "HP:0000002", "present": False},
        ])

    # Stop at the migration under test. Later migrations can be intentionally
    # irreversible and must not mask this migration's downgrade behavior.
    command.upgrade(config, "0050_phenotype_observation_status")
    with engine.begin() as connection:
        rows = connection.execute(text(
            "SELECT hpo_id, present, phenotype_status FROM phenotype_observations ORDER BY hpo_id"
        )).all()
        assert [(row.present, row.phenotype_status) for row in rows] == [
            (True, "PRESENT"), (False, "ABSENT")
        ]
        columns = {column["name"] for column in inspect(connection).get_columns("phenotype_observations")}
        assert "phenotype_status" in columns
        connection.execute(text(
            "INSERT INTO phenotype_observations "
            "(id, case_id, analysis_id, hpo_id, present, phenotype_status, source, evidence, created_at) "
            "VALUES ('10000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000001', NULL, 'HP:0000002', false, 'EXCLUDED', 'TEST', '{}', CURRENT_TIMESTAMP)"
        ))
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO phenotype_observations "
                "(id, case_id, analysis_id, hpo_id, present, phenotype_status, source, evidence, created_at) "
                "VALUES ('10000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000001', NULL, 'HP:0000002', false, 'EXCLUDED', 'TEST', '{}', CURRENT_TIMESTAMP)"
            ))
    engine.dispose()
    with pytest.raises(RuntimeError, match="Cannot downgrade phenotype states"):
        command.downgrade(config, "0049_case_access_role_capabilities")
