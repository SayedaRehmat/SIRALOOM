from pathlib import Path

import pytest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text, Table, MetaData, insert, update, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import uuid4
from datetime import datetime, timezone

from backend.app.infrastructure.db.models import (
    Organization, User, Case, Analysis,
    ExecutionEnvironmentRegistration, ToolExecutionRecord,
)


def test_execution_environment_and_tool_ledger_migration_creates_tables_and_guards(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "execution-ledger.sqlite"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "head")

    engine = create_engine(url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "execution_environment_registrations" in tables
    assert "tool_execution_records" in tables

    environment_columns = {
        column["name"]
        for column in inspector.get_columns("execution_environment_registrations")
    }
    assert {
        "organization_id",
        "owner_scope",
        "environment_id",
        "profile_version",
        "profile_fingerprint",
        "profile_json",
        "qualification_status",
    }.issubset(environment_columns)

    execution_columns = {
        column["name"] for column in inspector.get_columns("tool_execution_records")
    }
    assert {
        "execution_id",
        "case_id",
        "idempotency_key",
        "request_fingerprint",
        "organization_id",
        "analysis_id",
        "environment_registration_id",
        "environment_snapshot",
        "input_manifest",
        "output_manifest",
        "provenance",
        "attempt",
        "lease_token",
        "lease_expires_at",
        "stdout_sha256",
        "stderr_sha256",
    }.issubset(execution_columns)

    assert inspector.get_columns("tool_execution_records")[
        [column["name"] for column in inspector.get_columns("tool_execution_records")].index("case_id")
    ]["nullable"] is False
    assert inspector.get_columns("tool_execution_records")[
        [column["name"] for column in inspector.get_columns("tool_execution_records")].index("analysis_id")
    ]["nullable"] is True

    with engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }
    assert "trg_execution_environment_append_only_update" in triggers
    assert "trg_execution_environment_append_only_delete" in triggers
    assert "trg_tool_execution_record_identity_immutable" in triggers
    assert "trg_tool_execution_record_state_guard" in triggers
    assert "trg_tool_execution_record_no_delete" in triggers

    for model in (ExecutionEnvironmentRegistration, ToolExecutionRecord):
        database_columns = {
            column["name"]: column
            for column in inspector.get_columns(model.__tablename__)
        }
        model_columns = {column.name: column for column in model.__table__.columns}
        assert set(database_columns) == set(model_columns)
        for name, model_column in model_columns.items():
            assert database_columns[name]["nullable"] == model_column.nullable, (
                model.__tablename__, name, database_columns[name]["nullable"], model_column.nullable
            )

    environment_indexes = {item["name"] for item in inspector.get_indexes("execution_environment_registrations")}
    assert {"uq_execution_environment_lab_version", "uq_execution_environment_global_version"} <= environment_indexes
    execution_indexes = {item["name"] for item in inspector.get_indexes("tool_execution_records")}
    assert {
        "ix_tool_execution_case_created",
        "ix_tool_execution_analysis_created",
        "ix_tool_execution_org_status_created",
    } <= execution_indexes
    engine.dispose()


def _migration_config(db_path, monkeypatch):
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return url, cfg


def _migration_lab(session):
    organization = Organization(id=uuid4(), name="Execution Migration Lab")
    session.add(organization)
    session.flush()
    user = User(
        id=uuid4(), organization_id=organization.id, display_name="Migration Operator",
        role="lab_admin", status="ACTIVE",
    )
    session.add(user)
    session.flush()

    # This fixture intentionally represents the supported 0070 database.
    # The current ORM Case model already includes the later 0073 column, so
    # reflect and insert only columns that existed in the pre-execution schema.
    case_id = uuid4()
    case_table = Table("cases", MetaData(), autoload_with=session.get_bind())
    case_values = {
        "id": case_id,
        "organization_id": organization.id,
        "case_identifier": f"MIG-{uuid4().hex[:10]}",
        "status": "DRAFT",
        "accession_reconciliation_status": "NEW_WORKFLOW",
        "clinical_context": {},
        "language": "en",
        "created_by": user.id,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    session.execute(insert(case_table).values({
        key: value for key, value in case_values.items() if key in case_table.c
    }))
    case = type("PriorReleaseCase", (), {"id": case_id})()
    analysis = Analysis(
        id=uuid4(), case_id=case_id, analysis_type="GERMLINE",
        workflow_id="germline-standard", workflow_version="1", status="QUEUED",
        reference_build="GRCh38", created_by=user.id,
    )
    session.add(analysis)
    session.flush()
    return organization, user, case, analysis


def test_upgrade_from_supported_pre_execution_release_backfills_case_scope(tmp_path, monkeypatch):
    db_path = tmp_path / "prior-release.sqlite"
    url, cfg = _migration_config(db_path, monkeypatch)
    command.upgrade(cfg, "0070_resource_release_artifacts")

    engine = create_engine(url)
    with Session(engine) as session:
        organization, user, case, analysis = _migration_lab(session)
        session.commit()
        command.upgrade(cfg, "0071_execution_environment_provenance")
        environment = ExecutionEnvironmentRegistration(
            id=uuid4(), organization_id=organization.id, owner_scope="LABORATORY",
            environment_id="migration-lab-server", profile_version="1",
            profile_fingerprint="b" * 64, profile_json={"environment_id": "migration-lab-server"},
            qualification_status="ENVIRONMENT_QUALIFIED", created_by=user.id,
        )
        session.add(environment)
        session.commit()
        table = Table("tool_execution_records", MetaData(), autoload_with=engine)
        session.execute(insert(table).values(
            id=uuid4().hex, execution_id="legacy-analysis-execution",
            idempotency_key="c" * 64, request_fingerprint="d" * 64,
            organization_id=organization.id.hex, analysis_id=analysis.id.hex,
            environment_registration_id=environment.id.hex,
            tool_id="bcftools", tool_version="1.25", tool_profile_id="bcftools-1.25",
            executable_sha256="e" * 64, platform="linux-64", operation="normalize",
            request_snapshot={}, environment_snapshot={}, input_manifest=[], output_manifest=[],
            status="PENDING", attempt=0,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        session.commit()
        case_id, analysis_id = case.id, analysis.id
    engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT case_id, analysis_id FROM tool_execution_records "
            "WHERE execution_id = 'legacy-analysis-execution'"
        )).one()
        assert row.case_id == case_id.hex
        assert row.analysis_id == analysis_id.hex
        assert inspect(connection).get_columns("tool_execution_records")[
            [c["name"] for c in inspect(connection).get_columns("tool_execution_records")].index("case_id")
        ]["nullable"] is False
    engine.dispose()


def test_execution_ledger_sqlite_triggers_enforce_immutability_and_state_machine(tmp_path, monkeypatch):
    db_path = tmp_path / "execution-triggers.sqlite"
    url, cfg = _migration_config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    engine = create_engine(url)

    with Session(engine) as session:
        organization, user, case, analysis = _migration_lab(session)
        environment = ExecutionEnvironmentRegistration(
            id=uuid4(), organization_id=organization.id, owner_scope="LABORATORY",
            environment_id="trigger-lab-server", profile_version="1",
            profile_fingerprint="f" * 64, profile_json={"environment_id": "trigger-lab-server"},
            qualification_status="ENVIRONMENT_QUALIFIED", created_by=user.id,
        )
        session.add(environment)
        session.flush()
        record = ToolExecutionRecord(
            id=uuid4(), execution_id="trigger-execution", idempotency_key="1" * 64,
            request_fingerprint="2" * 64, organization_id=organization.id,
            case_id=case.id, analysis_id=analysis.id, environment_registration_id=environment.id,
            tool_id="bcftools", tool_version="1.25", tool_profile_id="bcftools-1.25",
            executable_sha256="3" * 64, platform="linux-64", operation="validate",
            request_snapshot={}, environment_snapshot={}, input_manifest=[], output_manifest=[],
            status="PENDING", attempt=0,
        )
        session.add(record)
        session.commit()

        with pytest.raises(IntegrityError):
            session.execute(update(ExecutionEnvironmentRegistration).where(
                ExecutionEnvironmentRegistration.id == environment.id
            ).values(profile_version="2"))
            session.commit()
        session.rollback()

        with pytest.raises(IntegrityError):
            session.execute(delete(ExecutionEnvironmentRegistration).where(
                ExecutionEnvironmentRegistration.id == environment.id
            ))
            session.commit()
        session.rollback()

        with pytest.raises(IntegrityError):
            session.execute(update(ToolExecutionRecord).where(
                ToolExecutionRecord.id == record.id
            ).values(request_snapshot={"tampered": True}))
            session.commit()
        session.rollback()

        session.execute(update(ToolExecutionRecord).where(
            ToolExecutionRecord.id == record.id
        ).values(
            status="RUNNING", lease_owner="worker-1", lease_token="lease-1",
            lease_expires_at=datetime.now(timezone.utc),
        ))
        session.commit()
        session.execute(update(ToolExecutionRecord).where(
            ToolExecutionRecord.id == record.id
        ).values(
            status="SUCCEEDED", provenance={"exit_code": 0}, exit_code=0,
            completed_at=datetime.now(timezone.utc),
        ))
        session.commit()

        with pytest.raises(IntegrityError):
            session.execute(update(ToolExecutionRecord).where(
                ToolExecutionRecord.id == record.id
            ).values(error_message="post-terminal mutation"))
            session.commit()
        session.rollback()

        with pytest.raises(IntegrityError):
            session.execute(delete(ToolExecutionRecord).where(
                ToolExecutionRecord.id == record.id
            ))
            session.commit()
        session.rollback()

    engine.dispose()
