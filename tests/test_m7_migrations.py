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
    assert "0019_partition_scheduler_resources" in current.stdout + current.stderr
