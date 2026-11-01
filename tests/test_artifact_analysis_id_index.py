from sqlalchemy import create_engine, inspect

from backend.app.infrastructure.db.base import Base


def test_artifact_analysis_id_lookup_index_exists():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    indexes = inspect(engine).get_indexes("artifacts")

    assert any(
        index["name"] == "ix_artifacts_analysis_id"
        and index["column_names"] == ["analysis_id"]
        for index in indexes
    )
