"""PostgreSQL proof for backup artifact-target classification semantics."""

import os

import pytest
from sqlalchemy import create_engine, text

from scripts.laboratory_backup import ARTIFACT_STORAGE_PREFLIGHT_SQL


@pytest.mark.integration
def test_backup_storage_preflight_classifies_cloud_custom_legacy_and_orphaned_targets():
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

                classify = lambda: connection.execute(
                    text(ARTIFACT_STORAGE_PREFLIGHT_SQL)
                ).scalar_one()
                assert classify() == "NON_LEGACY_ARTIFACTS_PRESENT"

                connection.execute(
                    text("UPDATE organization_storage_profiles SET backend_type = 'FIREBASE_GCS'")
                )
                assert classify() == "CLOUD_ARTIFACTS_PRESENT"

                connection.execute(
                    text(
                        "UPDATE organization_storage_profiles SET "
                        "backend_type = 'LOCAL_FILESYSTEM', configuration = '{}'::jsonb"
                    )
                )
                assert classify() == "LOCAL_ARTIFACTS_ONLY"

                connection.execute(text("DELETE FROM organization_storage_profiles"))
                connection.execute(
                    text("UPDATE artifacts SET storage_uri = :uri"),
                    {"uri": "file:///lab-a/artifacts/source.vcf"},
                )
                assert classify() == "NON_LEGACY_ARTIFACTS_PRESENT"
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
