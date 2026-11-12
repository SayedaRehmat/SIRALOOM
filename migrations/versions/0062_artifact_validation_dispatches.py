"""Add durable artifact-validation dispatch outbox.

Revision ID: 0062_artifact_validation_dispatches
Revises: 0061_analysis_toolchain_profiles
"""
from alembic import op
import sqlalchemy as sa

revision = "0062_artifact_validation_dispatches"
down_revision = "0061_analysis_toolchain_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "artifact_validation_dispatches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("toolchain_profile_id", sa.Text(), nullable=False),
        sa.Column("toolchain_bcftools_version", sa.Text(), nullable=False),
        sa.Column("toolchain_htslib_version", sa.Text(), nullable=False),
        sa.Column("toolchain_queue", sa.Text(), nullable=False),
        sa.Column("toolchain_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PUBLISHED', 'RUNNING', 'RETRYING', 'COMPLETED', 'FAILED')",
            name="ck_artifact_validation_dispatch_status",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", name="uq_artifact_validation_dispatch_artifact"),
    )
    op.create_index(
        "ix_artifact_validation_dispatch_status_created",
        "artifact_validation_dispatches",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_artifact_validation_dispatch_case_status",
        "artifact_validation_dispatches",
        ["case_id", "status"],
    )
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_artifact_validation_identity_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                IF OLD.artifact_id IS DISTINCT FROM NEW.artifact_id
                   OR OLD.organization_id IS DISTINCT FROM NEW.organization_id
                   OR OLD.case_id IS DISTINCT FROM NEW.case_id
                   OR OLD.toolchain_profile_id IS DISTINCT FROM NEW.toolchain_profile_id
                   OR OLD.toolchain_bcftools_version IS DISTINCT FROM NEW.toolchain_bcftools_version
                   OR OLD.toolchain_htslib_version IS DISTINCT FROM NEW.toolchain_htslib_version
                   OR OLD.toolchain_queue IS DISTINCT FROM NEW.toolchain_queue
                   OR OLD.toolchain_snapshot::text IS DISTINCT FROM NEW.toolchain_snapshot::text THEN
                    RAISE EXCEPTION 'artifact validation dispatch identity and toolchain provenance are immutable';
                END IF;
                RETURN NEW;
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_artifact_validation_identity_immutable
            BEFORE UPDATE ON artifact_validation_dispatches
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_artifact_validation_identity_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_artifact_validation_identity_immutable
            BEFORE UPDATE ON artifact_validation_dispatches
            WHEN OLD.artifact_id != NEW.artifact_id
              OR OLD.organization_id != NEW.organization_id
              OR OLD.case_id != NEW.case_id
              OR OLD.toolchain_profile_id != NEW.toolchain_profile_id
              OR OLD.toolchain_bcftools_version != NEW.toolchain_bcftools_version
              OR OLD.toolchain_htslib_version != NEW.toolchain_htslib_version
              OR OLD.toolchain_queue != NEW.toolchain_queue
              OR OLD.toolchain_snapshot != NEW.toolchain_snapshot
            BEGIN SELECT RAISE(ABORT, 'artifact validation dispatch identity and toolchain provenance are immutable'); END
        """)


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_artifact_validation_identity_immutable ON artifact_validation_dispatches")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_artifact_validation_identity_mutation()")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_artifact_validation_identity_immutable")
    op.drop_index("ix_artifact_validation_dispatch_case_status", table_name="artifact_validation_dispatches")
    op.drop_index("ix_artifact_validation_dispatch_status_created", table_name="artifact_validation_dispatches")
    op.drop_table("artifact_validation_dispatches")
