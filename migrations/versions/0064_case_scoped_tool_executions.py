"""Allow common tool executions during case intake before Analysis exists.

Revision ID: 0064_case_scoped_tool_executions
Revises: 0063_execution_environment_provenance
"""
from alembic import op
import sqlalchemy as sa


revision = "0064_case_scoped_tool_executions"
down_revision = "0063_execution_environment_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tool_execution_records",
        sa.Column("case_id", sa.Uuid(), nullable=True),
    )
    op.execute("""
        UPDATE tool_execution_records
        SET case_id = (
            SELECT analyses.case_id
            FROM analyses
            WHERE analyses.id = tool_execution_records.analysis_id
        )
    """)
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.alter_column("tool_execution_records", "analysis_id", existing_type=sa.Uuid(), nullable=True)
        op.alter_column("tool_execution_records", "case_id", existing_type=sa.Uuid(), nullable=False)
        op.create_foreign_key(
            "fk_tool_execution_records_case_id_cases",
            "tool_execution_records", "cases", ["case_id"], ["id"],
        )
        op.execute("""
            CREATE OR REPLACE FUNCTION siraloom_guard_tool_execution_record()
            RETURNS trigger AS $siraloom$
            BEGIN
                IF OLD.execution_id IS DISTINCT FROM NEW.execution_id
                   OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
                   OR OLD.request_fingerprint IS DISTINCT FROM NEW.request_fingerprint
                   OR OLD.organization_id IS DISTINCT FROM NEW.organization_id
                   OR OLD.case_id IS DISTINCT FROM NEW.case_id
                   OR OLD.analysis_id IS DISTINCT FROM NEW.analysis_id
                   OR OLD.environment_registration_id IS DISTINCT FROM NEW.environment_registration_id
                   OR OLD.tool_id IS DISTINCT FROM NEW.tool_id
                   OR OLD.tool_version IS DISTINCT FROM NEW.tool_version
                   OR OLD.tool_profile_id IS DISTINCT FROM NEW.tool_profile_id
                   OR OLD.executable_sha256 IS DISTINCT FROM NEW.executable_sha256
                   OR OLD.platform IS DISTINCT FROM NEW.platform
                   OR OLD.operation IS DISTINCT FROM NEW.operation
                   OR OLD.request_snapshot::text IS DISTINCT FROM NEW.request_snapshot::text
                   OR OLD.environment_snapshot::text IS DISTINCT FROM NEW.environment_snapshot::text
                   OR OLD.input_manifest::text IS DISTINCT FROM NEW.input_manifest::text THEN
                    RAISE EXCEPTION 'tool execution identity and request snapshot are immutable';
                END IF;
                IF OLD.status IN ('SUCCEEDED', 'FAILED') THEN
                    RAISE EXCEPTION 'terminal tool execution records are immutable';
                END IF;
                IF NOT (
                    (OLD.status = 'PENDING' AND NEW.status IN ('PENDING', 'RUNNING', 'FAILED', 'INTERRUPTED'))
                    OR (OLD.status = 'RUNNING' AND NEW.status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED'))
                    OR (OLD.status = 'INTERRUPTED' AND NEW.status IN ('INTERRUPTED', 'RUNNING'))
                ) THEN
                    RAISE EXCEPTION 'invalid tool execution status transition: % -> %', OLD.status, NEW.status;
                END IF;
                RETURN NEW;
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
    elif connection.dialect.name == "sqlite":
        with op.batch_alter_table("tool_execution_records", recreate="always") as batch:
            batch.alter_column("analysis_id", existing_type=sa.Uuid(), nullable=True)
            batch.alter_column("case_id", existing_type=sa.Uuid(), nullable=False)
            batch.create_foreign_key(
                "fk_tool_execution_records_case_id_cases", "cases", ["case_id"], ["id"]
            )
        op.execute("DROP TRIGGER IF EXISTS trg_tool_execution_record_identity_immutable")
        op.execute("""
            CREATE TRIGGER trg_tool_execution_record_identity_immutable
            BEFORE UPDATE ON tool_execution_records
            WHEN OLD.execution_id IS NOT NEW.execution_id
              OR OLD.idempotency_key IS NOT NEW.idempotency_key
              OR OLD.request_fingerprint IS NOT NEW.request_fingerprint
              OR OLD.organization_id IS NOT NEW.organization_id
              OR OLD.case_id IS NOT NEW.case_id
              OR OLD.analysis_id IS NOT NEW.analysis_id
              OR OLD.environment_registration_id IS NOT NEW.environment_registration_id
              OR OLD.tool_id IS NOT NEW.tool_id
              OR OLD.tool_version IS NOT NEW.tool_version
              OR OLD.tool_profile_id IS NOT NEW.tool_profile_id
              OR OLD.executable_sha256 IS NOT NEW.executable_sha256
              OR OLD.platform IS NOT NEW.platform
              OR OLD.operation IS NOT NEW.operation
              OR OLD.request_snapshot IS NOT NEW.request_snapshot
              OR OLD.environment_snapshot IS NOT NEW.environment_snapshot
              OR OLD.input_manifest IS NOT NEW.input_manifest
            BEGIN SELECT RAISE(ABORT, 'tool execution identity and request snapshot are immutable'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_tool_execution_record_no_delete
            BEFORE DELETE ON tool_execution_records
            BEGIN SELECT RAISE(ABORT, 'tool execution records are an immutable audit ledger'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_tool_execution_record_state_guard
            BEFORE UPDATE ON tool_execution_records
            WHEN OLD.status IN ('SUCCEEDED', 'FAILED')
              OR NOT (
                (OLD.status = 'PENDING' AND NEW.status IN ('PENDING', 'RUNNING', 'FAILED', 'INTERRUPTED'))
                OR (OLD.status = 'RUNNING' AND NEW.status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED'))
                OR (OLD.status = 'INTERRUPTED' AND NEW.status IN ('INTERRUPTED', 'RUNNING'))
              )
            BEGIN SELECT RAISE(ABORT, 'invalid or terminal tool execution status transition'); END
        """)
    op.create_index(
        "ix_tool_execution_case_created",
        "tool_execution_records",
        ["case_id", "created_at"],
    )


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text(
        "SELECT 1 FROM tool_execution_records WHERE analysis_id IS NULL LIMIT 1"
    )).first():
        raise RuntimeError(
            "Cannot downgrade: case-scoped executions without an Analysis would lose their scope."
        )
    op.drop_index("ix_tool_execution_case_created", table_name="tool_execution_records")
    if connection.dialect.name == "postgresql":
        op.drop_constraint(
            "fk_tool_execution_records_case_id_cases",
            "tool_execution_records",
            type_="foreignkey",
        )
        op.alter_column("tool_execution_records", "analysis_id", existing_type=sa.Uuid(), nullable=False)
        op.drop_column("tool_execution_records", "case_id")
        # Restore the pre-0064 immutable identity guard.
        op.execute("""
            CREATE OR REPLACE FUNCTION siraloom_guard_tool_execution_record()
            RETURNS trigger AS $siraloom$
            BEGIN
                IF OLD.execution_id IS DISTINCT FROM NEW.execution_id
                   OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
                   OR OLD.request_fingerprint IS DISTINCT FROM NEW.request_fingerprint
                   OR OLD.organization_id IS DISTINCT FROM NEW.organization_id
                   OR OLD.analysis_id IS DISTINCT FROM NEW.analysis_id
                   OR OLD.environment_registration_id IS DISTINCT FROM NEW.environment_registration_id
                   OR OLD.tool_id IS DISTINCT FROM NEW.tool_id
                   OR OLD.tool_version IS DISTINCT FROM NEW.tool_version
                   OR OLD.tool_profile_id IS DISTINCT FROM NEW.tool_profile_id
                   OR OLD.executable_sha256 IS DISTINCT FROM NEW.executable_sha256
                   OR OLD.platform IS DISTINCT FROM NEW.platform
                   OR OLD.operation IS DISTINCT FROM NEW.operation
                   OR OLD.request_snapshot::text IS DISTINCT FROM NEW.request_snapshot::text
                   OR OLD.environment_snapshot::text IS DISTINCT FROM NEW.environment_snapshot::text
                   OR OLD.input_manifest::text IS DISTINCT FROM NEW.input_manifest::text THEN
                    RAISE EXCEPTION 'tool execution identity and request snapshot are immutable';
                END IF;
                IF OLD.status IN ('SUCCEEDED', 'FAILED') THEN
                    RAISE EXCEPTION 'terminal tool execution records are immutable';
                END IF;
                RETURN NEW;
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
    else:
        op.execute("DROP TRIGGER IF EXISTS trg_tool_execution_record_identity_immutable")
        op.execute("DROP TRIGGER IF EXISTS trg_tool_execution_record_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_tool_execution_record_state_guard")
        with op.batch_alter_table("tool_execution_records", recreate="always") as batch:
            batch.drop_constraint("fk_tool_execution_records_case_id_cases", type_="foreignkey")
            batch.drop_column("case_id")
            batch.alter_column("analysis_id", existing_type=sa.Uuid(), nullable=False)
        # Recreate the existing SQLite audit triggers from revision 0063.
        op.execute("""
            CREATE TRIGGER trg_tool_execution_record_identity_immutable
            BEFORE UPDATE ON tool_execution_records
            WHEN OLD.execution_id IS NOT NEW.execution_id
              OR OLD.idempotency_key IS NOT NEW.idempotency_key
              OR OLD.request_fingerprint IS NOT NEW.request_fingerprint
              OR OLD.organization_id IS NOT NEW.organization_id
              OR OLD.analysis_id IS NOT NEW.analysis_id
              OR OLD.environment_registration_id IS NOT NEW.environment_registration_id
              OR OLD.tool_id IS NOT NEW.tool_id
              OR OLD.tool_version IS NOT NEW.tool_version
              OR OLD.tool_profile_id IS NOT NEW.tool_profile_id
              OR OLD.executable_sha256 IS NOT NEW.executable_sha256
              OR OLD.platform IS NOT NEW.platform
              OR OLD.operation IS NOT NEW.operation
              OR OLD.request_snapshot IS NOT NEW.request_snapshot
              OR OLD.environment_snapshot IS NOT NEW.environment_snapshot
              OR OLD.input_manifest IS NOT NEW.input_manifest
            BEGIN SELECT RAISE(ABORT, 'tool execution identity and request snapshot are immutable'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_tool_execution_record_no_delete
            BEFORE DELETE ON tool_execution_records
            BEGIN SELECT RAISE(ABORT, 'tool execution records are an immutable audit ledger'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_tool_execution_record_state_guard
            BEFORE UPDATE ON tool_execution_records
            WHEN OLD.status IN ('SUCCEEDED', 'FAILED')
              OR NOT (
                (OLD.status = 'PENDING' AND NEW.status IN ('PENDING', 'RUNNING', 'FAILED', 'INTERRUPTED'))
                OR (OLD.status = 'RUNNING' AND NEW.status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED'))
                OR (OLD.status = 'INTERRUPTED' AND NEW.status IN ('INTERRUPTED', 'RUNNING'))
              )
            BEGIN SELECT RAISE(ABORT, 'invalid or terminal tool execution status transition'); END
        """)
