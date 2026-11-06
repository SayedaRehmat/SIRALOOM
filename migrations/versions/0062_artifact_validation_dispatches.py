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


def downgrade():
    op.drop_index("ix_artifact_validation_dispatch_case_status", table_name="artifact_validation_dispatches")
    op.drop_index("ix_artifact_validation_dispatch_status_created", table_name="artifact_validation_dispatches")
    op.drop_table("artifact_validation_dispatches")
