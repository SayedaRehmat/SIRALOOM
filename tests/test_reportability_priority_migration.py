import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _alembic(tmp_path: Path, revision: str) -> None:
    database = tmp_path / "reportability-migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite+pysqlite:///{database}"
    environment["REDIS_URL"] = "redis://localhost:6379/0"
    environment["ARTIFACT_ROOT"] = str(tmp_path / "artifacts")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_reportability_priority_migration_preserves_history_and_allows_null(tmp_path):
    database = tmp_path / "reportability-migration.db"
    _alembic(tmp_path, "0051_retire_unvalidated_inheritance_scores")

    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO reportability_decisions (
                    id, analysis_id, variant_id, classification_id, version,
                    policy_name, policy_version, disposition, priority_score,
                    priority_band, reasons, status, review_version,
                    created_at, updated_at
                ) VALUES (
                    '00000000-0000-0000-0000-000000000001',
                    '00000000-0000-0000-0000-000000000002',
                    '00000000-0000-0000-0000-000000000003',
                    '00000000-0000-0000-0000-000000000004',
                    1, 'legacy-policy', '1.0.0', 'REVIEW', 60,
                    'REVIEW', '[]', 'PROPOSED', 0,
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00'
                )
                """
            )
        )

    _alembic(tmp_path, "head")

    with engine.connect() as connection:
        legacy = connection.execute(
            text(
                "SELECT priority_score, priority_band FROM reportability_decisions "
                "WHERE id = '00000000-0000-0000-0000-000000000001'"
            )
        ).one()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO reportability_decisions (
                    id, analysis_id, variant_id, classification_id, version,
                    policy_name, policy_version, disposition, reasons, status,
                    review_version, created_at, updated_at
                ) VALUES (
                    '00000000-0000-0000-0000-000000000005',
                    '00000000-0000-0000-0000-000000000002',
                    '00000000-0000-0000-0000-000000000003',
                    '00000000-0000-0000-0000-000000000004',
                    2, 'current-policy', '2.0.0', 'REVIEW', '[]', 'PROPOSED', 0,
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00'
                )
                """
            )
        )
        current = connection.execute(
            text(
                "SELECT priority_score, priority_band FROM reportability_decisions "
                "WHERE id = '00000000-0000-0000-0000-000000000005'"
            )
        ).one()
    assert tuple(legacy) == (60, "REVIEW")
    assert tuple(current) == (None, None)
    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("reportability_decisions")
    }
    assert columns["priority_score"]["nullable"] is True
    assert columns["priority_band"]["nullable"] is True
    assert columns["priority_score"]["default"] is None
    assert columns["priority_band"]["default"] is None
