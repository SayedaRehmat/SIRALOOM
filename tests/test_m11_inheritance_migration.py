from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_unvalidated_inheritance_results_are_retired_by_migration(tmp_path, monkeypatch):
    database = tmp_path / "inheritance-score-migration.sqlite"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0050_phenotype_observation_status")

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO inheritance_assessments "
                "(id, analysis_id, variant_id, model, status, score, rationale, "
                "observation_fingerprint, reviewer_note, created_by, created_at) "
                "VALUES (:id, :analysis, :variant, :model, :status, :score, :rationale, "
                ":fingerprint, NULL, 'reviewer', CURRENT_TIMESTAMP)"
            ),
            [
                {
                    "id": "10000000-0000-0000-0000-000000000001",
                    "analysis": "20000000-0000-0000-0000-000000000001",
                    "variant": "30000000-0000-0000-0000-000000000001",
                    "model": "AD",
                    "status": "CONSISTENT",
                    "score": 80,
                    "rationale": "Affected with variant; unaffected without variant",
                    "fingerprint": "a" * 64,
                },
                {
                    "id": "10000000-0000-0000-0000-000000000002",
                    "analysis": "20000000-0000-0000-0000-000000000001",
                    "variant": "30000000-0000-0000-0000-000000000002",
                    "model": "AR",
                    "status": "INSUFFICIENT_DATA",
                    "score": 0,
                    "rationale": "No interpretable genotype/phenotype observations are available.",
                    "fingerprint": "b" * 64,
                },
            ],
        )

    command.upgrade(config, "head")
    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT status, score, rationale FROM inheritance_assessments ORDER BY id")
        ).all()
        assert rows[0].status == "REQUIRES_REVIEW"
        assert rows[0].score is None
        assert rows[0].rationale.startswith("Retired unvalidated heuristic")
        assert rows[1].status == "INSUFFICIENT_DATA"
        assert rows[1].score is None
        score_column = next(
            column
            for column in inspect(connection).get_columns("inheritance_assessments")
            if column["name"] == "score"
        )
        assert score_column["nullable"] is True
    engine.dispose()
