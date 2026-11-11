import os
import subprocess
import sys
from pathlib import Path


def test_alembic_replays_to_head_on_sqlite(tmp_path):
    db = tmp_path / "migration-test.db"
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": f"sqlite+pysqlite:///{db}",
        "REDIS_URL": "redis://localhost:6379/0",
        "ARTIFACT_ROOT": str(tmp_path / "artifacts"),
        "GENEBE_ENABLED": "false",
    })
    root = Path(__file__).resolve().parents[1]
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert upgrade.returncode == 0, upgrade.stderr

    current = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert current.returncode == 0, current.stderr
    assert "(head)" in current.stdout + current.stderr

def test_postgresql_assay_immutability_trigger_compares_json_as_jsonb():
    root = Path(__file__).resolve().parents[1]
    migration = (root / "migrations/versions/0066_assay_version_governance.py").read_text(encoding="utf-8")
    assert "NEW.configuration::jsonb IS DISTINCT FROM OLD.configuration::jsonb" in migration
    assert "NEW.configuration IS DISTINCT FROM OLD.configuration" not in migration
