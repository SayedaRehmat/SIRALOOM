"""Add durable case export dispatch outbox.

Revision ID: 0039_case_export_dispatch_outbox
Revises: 0038_acmg_source_assertions
"""

from alembic import op
import sqlalchemy as sa


revision = "0039_case_export_dispatch_outbox"
down_revision = "0038_acmg_source_assertions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "case_exports",
        sa.Column("queue_task_id", sa.Text(), nullable=True),
    )
    op.create_table(
        "case_export_dispatches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_export_id", sa.UUID(), nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_export_id"], ["case_exports.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_export_id",
            "dispatch_generation",
            name="uq_case_export_dispatch_generation",
        ),
    )
    op.create_index(
        "ix_case_export_dispatches_status",
        "case_export_dispatches",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_case_export_dispatches_status", table_name="case_export_dispatches")
    op.drop_table("case_export_dispatches")
    op.drop_column("case_exports", "queue_task_id")
