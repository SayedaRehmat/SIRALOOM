from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, delete, insert, inspect, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    Analysis,
    ExecutionEnvironmentRegistration,
    Organization,
    User,
)


def test_postgres_upgrade_from_supported_0070_database_preserves_rows_and_guards():
    source_url = make_url(__import__("os").environ["DATABASE_URL"])
    if source_url.get_backend_name() != "postgresql":
        pytest.skip("PostgreSQL prior-release migration qualification requires PostgreSQL.")

    database_name = "siraloom_migration_" + uuid4().hex[:16]
    admin_engine = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target_url = source_url.set(database=database_name)
    target_engine = None
    database_created = False
    original_database_url = os.environ.get("DATABASE_URL")
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        database_created = True
        target_engine = create_engine(target_url)
        cfg = Config(str(Path(__file__).parents[2] / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", str(target_url).replace("%", "%%"))
        # migrations/env.py deliberately gives DATABASE_URL precedence over
        # sqlalchemy.url. Point that variable at the isolated database too;
        # otherwise the upgrade mutates the shared CI database while this
        # test inserts fixture rows into an empty temporary database.
        os.environ["DATABASE_URL"] = str(target_url)

        # Construct a populated supported prior-release (0070) database.
        command.upgrade(cfg, "0070_resource_release_artifacts")
        organization_id = uuid4()
        case_id = uuid4()
        analysis_id = uuid4()
        user_id = uuid4()
        with Session(target_engine) as session:
            organization = Organization(id=organization_id, name="PostgreSQL Migration Lab")
            session.add(organization)
            session.flush()
            user = User(
                id=user_id,
                organization_id=organization_id,
                display_name="Migration Operator",
                role="lab_admin",
                status="ACTIVE",
            )
            session.add(user)
            session.flush()

            case_table = Table("cases", MetaData(), autoload_with=target_engine)
            case_values = {
                "id": case_id,
                "organization_id": organization_id,
                "case_identifier": "PG-MIGRATION-CASE",
                "status": "OPEN",
                "accession_reconciliation_status": "NEW_WORKFLOW",
                "clinical_context": {},
                "language": "en",
                "created_by": user_id,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            session.execute(insert(case_table).values({
                key: value for key, value in case_values.items() if key in case_table.c
            }))
            analysis = Analysis(
                id=analysis_id,
                case_id=case_id,
                analysis_type="GERMLINE",
                workflow_id="germline-standard",
                workflow_version="1",
                status="QUEUED",
                reference_build="GRCh38",
                created_by=user_id,
            )
            session.add(analysis)
            session.commit()

        command.upgrade(cfg, "0071_execution_environment_provenance")
        environment_id = uuid4()
        with Session(target_engine) as session:
            environment = ExecutionEnvironmentRegistration(
                id=environment_id,
                organization_id=organization_id,
                owner_scope="LABORATORY",
                environment_id="postgres-migration-lab",
                profile_version="1",
                profile_fingerprint="b" * 64,
                profile_json={"environment_id": "postgres-migration-lab"},
                qualification_status="ENVIRONMENT_QUALIFIED",
                created_by=user_id,
            )
            session.add(environment)
            session.commit()

        execution_table = Table("tool_execution_records", MetaData(), autoload_with=target_engine)
        with target_engine.begin() as connection:
            connection.execute(insert(execution_table).values(
                id=uuid4(),
                execution_id="legacy-postgres-execution",
                idempotency_key="c" * 64,
                request_fingerprint="d" * 64,
                organization_id=organization_id,
                analysis_id=analysis_id,
                environment_registration_id=environment_id,
                tool_id="bcftools",
                tool_version="1.25",
                tool_profile_id="bcftools-1.25",
                executable_sha256="e" * 64,
                platform="linux-64",
                operation="normalize",
                request_snapshot={},
                environment_snapshot={},
                input_manifest=[],
                output_manifest=[],
                status="PENDING",
                attempt=0,
            ))

        # The upgrade must backfill case_id, permit analysis_id to be NULL,
        # and add the case-to-environment relationship without rebuilding data.
        command.upgrade(cfg, "head")
        with target_engine.connect() as connection:
            row = connection.execute(text(
                "SELECT case_id, analysis_id FROM tool_execution_records "
                "WHERE execution_id = 'legacy-postgres-execution'"
            )).one()
            assert row.case_id == case_id
            assert row.analysis_id == analysis_id
            case_columns = {
                item["name"]: item for item in inspect(connection).get_columns("cases")
            }
            assert case_columns["execution_environment_registration_id"]["nullable"] is True
            assert any(
                item["name"] == "fk_cases_execution_environment_registration"
                for item in inspect(connection).get_foreign_keys("cases")
            )

        # Verify the PostgreSQL trigger guards on the populated upgraded DB.
        def assert_trigger_rejects(statement):
            with target_engine.connect() as connection:
                transaction = connection.begin()
                try:
                    with pytest.raises(DBAPIError):
                        connection.execute(statement)
                finally:
                    transaction.rollback()

        assert_trigger_rejects(
            update(ExecutionEnvironmentRegistration)
            .where(ExecutionEnvironmentRegistration.id == environment_id)
            .values(profile_version="2")
        )
        assert_trigger_rejects(
            delete(ExecutionEnvironmentRegistration)
            .where(ExecutionEnvironmentRegistration.id == environment_id)
        )

        with target_engine.begin() as connection:
            connection.execute(text(
                "UPDATE tool_execution_records SET status='RUNNING', lease_owner='worker-1', "
                "lease_token='lease-1', lease_expires_at=now() "
                "WHERE execution_id='legacy-postgres-execution'"
            ))
            connection.execute(text(
                "UPDATE tool_execution_records SET status='SUCCEEDED', provenance='{\"exit_code\":0}'::json, "
                "exit_code=0, completed_at=now() WHERE execution_id='legacy-postgres-execution'"
            ))
        assert_trigger_rejects(text(
            "UPDATE tool_execution_records SET output_manifest='[]'::json "
            "WHERE execution_id='legacy-postgres-execution'"
        ))
        assert_trigger_rejects(text(
            "DELETE FROM tool_execution_records WHERE execution_id='legacy-postgres-execution'"
        ))
    finally:
        if original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_database_url
        if target_engine is not None:
            target_engine.dispose()
        if database_created:
            with admin_engine.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        admin_engine.dispose()
