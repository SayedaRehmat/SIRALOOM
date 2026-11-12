from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


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
    engine.dispose()
