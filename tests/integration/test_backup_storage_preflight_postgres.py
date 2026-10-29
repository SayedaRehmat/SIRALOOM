"""PostgreSQL proof for backup artifact-target classification semantics."""

import json
import os

import pytest
from sqlalchemy import create_engine, text

from scripts.laboratory_backup import (
    ARTIFACT_STORAGE_PREFLIGHT_SQL,
    _artifact_uri_coverage_sql,
)


@pytest.mark.integration
def test_backup_storage_preflight_reports_profiles_and_artifact_roots():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        # Temporary tables isolate this global preflight query from unrelated
        # artifacts created by other integration tests in the shared database.
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text(
                        "CREATE TEMP TABLE organization_storage_profiles "
                        "(backend_type text, configuration jsonb)"
                    )
                )
                connection.execute(text("CREATE TEMP TABLE artifacts (storage_uri text NOT NULL)"))
                connection.execute(
                    text(
                        "INSERT INTO organization_storage_profiles "
                        "(backend_type, configuration) "
                        "VALUES (:backend, CAST(:configuration AS jsonb))"
                    ),
                    {
                        "backend": "LOCAL_FILESYSTEM",
                        "configuration": '{"target_id":"lab-artifact-root"}',
                    },
                )
                connection.execute(
                    text("INSERT INTO artifacts (storage_uri) VALUES (:uri)"),
                    {"uri": "file:///data/siraloom/artifacts/source.vcf"},
                )

                inventory = lambda: json.loads(
                    connection.execute(text(ARTIFACT_STORAGE_PREFLIGHT_SQL)).scalar_one()
                )
                first = inventory()
                assert first["cloud_present"] is False
                assert first["local_target_ids"] == ["lab-artifact-root"]
                assert first["nonlegacy_artifacts"] is False

                connection.execute(
                    text("UPDATE organization_storage_profiles SET backend_type = 'FIREBASE_GCS'")
                )
                assert inventory()["cloud_present"] is True

                connection.execute(
                    text(
                        "UPDATE organization_storage_profiles SET "
                        "backend_type = 'LOCAL_FILESYSTEM', configuration = '{}'::jsonb"
                    )
                )
                assert inventory() == {
                    "cloud_present": False,
                    "local_target_ids": [],
                    "nonlegacy_artifacts": False,
                }

                connection.execute(text("DELETE FROM organization_storage_profiles"))
                connection.execute(
                    text("UPDATE artifacts SET storage_uri = :uri"),
                    {"uri": "file:///lab-a/artifacts/source.vcf"},
                )
                assert inventory()["nonlegacy_artifacts"] is True

                connection.execute(
                    text("UPDATE artifacts SET storage_uri = :uri"),
                    {"uri": "file:///data/siraloom/labs/lab-a/artifacts/source.vcf"},
                )
                mapped = connection.execute(
                    text(_artifact_uri_coverage_sql(["/data/siraloom/labs/lab-a/artifacts"]))
                ).scalar_one()
                assert mapped == "ARTIFACT_URIS_MAPPED"
                connection.execute(
                    text("UPDATE artifacts SET storage_uri = :uri"),
                    {"uri": "file:///unconfigured/artifacts/source.vcf"},
                )
                unmapped = connection.execute(
                    text(_artifact_uri_coverage_sql(["/data/siraloom/labs/lab-a/artifacts"]))
                ).scalar_one()
                assert unmapped == "UNMAPPED_ARTIFACT_URI"
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
