"""Persist lab execution environment registrations and tool execution provenance.

Revision ID: 0071_execution_environment_provenance
Revises: 0070_resource_release_artifacts
"""
from alembic import op
import sqlalchemy as sa


revision = "0071_execution_environment_provenance"
down_revision = "0070_resource_release_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "execution_environment_registrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("owner_scope", sa.Text(), nullable=False),
        sa.Column("environment_id", sa.Text(), nullable=False),
        sa.Column("profile_version", sa.Text(), nullable=False),
        sa.Column("profile_fingerprint", sa.Text(), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("qualification_status", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(owner_scope = 'LABORATORY' AND organization_id IS NOT NULL) OR "
            "(owner_scope = 'SIRALOOM' AND organization_id IS NULL)",
            name="ck_execution_environment_owner_scope",
        ),
        sa.CheckConstraint(
            "qualification_status IN ('DISCOVERED', 'STAGED', 'QUALIFICATION_PENDING', "
            "'ENVIRONMENT_QUALIFIED', 'SUSPENDED', 'RETIRED')",
            name="ck_execution_environment_qualification_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_execution_environment_lab_version",
        "execution_environment_registrations",
        ["organization_id", "environment_id", "profile_version"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
        sqlite_where=sa.text("organization_id IS NOT NULL"),
    )
    op.create_index(
        "uq_execution_environment_global_version",
        "execution_environment_registrations",
        ["environment_id", "profile_version"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
        sqlite_where=sa.text("organization_id IS NULL"),
    )

    op.create_table(
        "tool_execution_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("environment_registration_id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.Text(), nullable=False),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column("tool_profile_id", sa.Text(), nullable=False),
        sa.Column("executable_sha256", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("environment_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_manifest", sa.JSON(), nullable=False),
        sa.Column("output_manifest", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_token", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout_sha256", sa.Text(), nullable=True),
        sa.Column("stderr_sha256", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')",
            name="ck_tool_execution_status",
        ),
        sa.CheckConstraint(
            "length(executable_sha256) = 64",
            name="ck_tool_execution_executable_sha256_length",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR status != 'RUNNING'",
            name="ck_tool_execution_running_lease",
        ),
        sa.CheckConstraint(
            "status != 'SUCCEEDED' OR "
            "(provenance IS NOT NULL AND exit_code = 0 AND completed_at IS NOT NULL)",
            name="ck_tool_execution_success_has_provenance",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(
            ["environment_registration_id"], ["execution_environment_registrations.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "execution_id", name="uq_tool_execution_org_execution"
        ),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_tool_execution_org_idempotency"
        ),
    )
    op.create_index(
        "ix_tool_execution_analysis_created",
        "tool_execution_records",
        ["analysis_id", "created_at"],
    )
    op.create_index(
        "ix_tool_execution_org_status_created",
        "tool_execution_records",
        ["organization_id", "status", "created_at"],
    )

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_execution_environment_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'execution environment registrations are append-only; register a new profile version';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_execution_environment_append_only
            BEFORE UPDATE OR DELETE ON execution_environment_registrations
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_execution_environment_mutation()
        """)
        op.execute("""
            CREATE FUNCTION siraloom_guard_tool_execution_record()
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
        op.execute("""
            CREATE TRIGGER trg_tool_execution_record_guard
            BEFORE UPDATE ON tool_execution_records
            FOR EACH ROW EXECUTE FUNCTION siraloom_guard_tool_execution_record()
        """)
        op.execute("""
            CREATE FUNCTION siraloom_reject_tool_execution_delete()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'tool execution records are an immutable audit ledger';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_tool_execution_record_no_delete
            BEFORE DELETE ON tool_execution_records
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_tool_execution_delete()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_execution_environment_append_only_update
            BEFORE UPDATE ON execution_environment_registrations
            BEGIN SELECT RAISE(ABORT, 'execution environment registrations are append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_execution_environment_append_only_delete
            BEFORE DELETE ON execution_environment_registrations
            BEGIN SELECT RAISE(ABORT, 'execution environment registrations are append-only'); END
        """)
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


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_tool_execution_record_no_delete ON tool_execution_records")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_tool_execution_delete()")
        op.execute("DROP TRIGGER IF EXISTS trg_tool_execution_record_guard ON tool_execution_records")
        op.execute("DROP FUNCTION IF EXISTS siraloom_guard_tool_execution_record()")
        op.execute("DROP TRIGGER IF EXISTS trg_execution_environment_append_only ON execution_environment_registrations")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_execution_environment_mutation()")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_tool_execution_record_state_guard")
        op.execute("DROP TRIGGER IF EXISTS trg_tool_execution_record_identity_immutable")
        op.execute("DROP TRIGGER IF EXISTS trg_tool_execution_record_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_execution_environment_append_only_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_execution_environment_append_only_update")
    op.drop_index("ix_tool_execution_org_status_created", table_name="tool_execution_records")
    op.drop_index("ix_tool_execution_analysis_created", table_name="tool_execution_records")
    op.drop_table("tool_execution_records")
    op.drop_index("uq_execution_environment_global_version", table_name="execution_environment_registrations")
    op.drop_index("uq_execution_environment_lab_version", table_name="execution_environment_registrations")
    op.drop_table("execution_environment_registrations")
