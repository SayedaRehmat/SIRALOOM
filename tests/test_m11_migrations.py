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
    analysis_cols = {c["name"] for c in inspector.get_columns("analyses")}
    assert "assay_id" in analysis_cols
