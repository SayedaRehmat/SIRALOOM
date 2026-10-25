from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_m11_full_sqlite_upgrade_reaches_qc_head(tmp_path, monkeypatch):
    db = tmp_path / "m11.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(cfg, "head")
    inspector = inspect(create_engine(f"sqlite:///{db}"))
    assert "technical_qc_observations" in inspector.get_table_names()
    assert "qc_assessments" in inspector.get_table_names()
    qc_column_details = {c["name"]: c for c in inspector.get_columns("qc_assessments")}
    qc_columns = set(qc_column_details)
    assert "observation_snapshot" in qc_columns
    assert qc_column_details["observation_snapshot"]["nullable"] is True
    analysis_cols = {c["name"] for c in inspector.get_columns("analyses")}
    assert "assay_id" in analysis_cols
    annotation_cols = {c["name"] for c in inspector.get_columns("annotations")}
    assert {
        "resource_id",
        "request_fingerprint",
        "response_sha256",
        "request_metadata",
        "observed_at",
        "retry_count",
    }.issubset(annotation_cols)
    population_cols = {c["name"] for c in inspector.get_columns("population_observations")}
    assert {
        "source_record_id",
        "request_fingerprint",
        "response_sha256",
        "request_metadata",
        "observed_at",
    }.issubset(population_cols)
    specimen_constraints = inspector.get_unique_constraints("specimens")
    assert any(
        constraint.get("name") == "uq_specimen_case_identifier"
        and constraint.get("column_names") == ["case_id", "specimen_identifier"]
        for constraint in specimen_constraints
    )


def test_qc_observation_snapshot_migration_downgrades_without_touching_prior_schema(tmp_path, monkeypatch):
    db = tmp_path / "qc-snapshot-downgrade.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0052_remove_unvalidated_reportability_priorities")

    inspector = inspect(create_engine(url))
    assert "observation_snapshot" not in {
        column["name"] for column in inspector.get_columns("qc_assessments")
    }
    assert "qc_assessments" in inspector.get_table_names()
