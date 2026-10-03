"""Add durable analysis dispatch outbox.

The dispatch intent is committed with the analysis QUEUED state so a database
commit cannot be followed by a lost broker publication.
"""

from alembic import op
import sqlalchemy as sa


revision = "0036_analysis_dispatch_outbox"
down_revision = "0035_reanalysis_parent_version_uniqueness"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_dispatches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "dispatch_generation", name="uq_analysis_dispatch_generation"),
    )
    op.create_index("ix_analysis_dispatches_status", "analysis_dispatches", ["status"], unique=False)


def downgrade():
    op.drop_index("ix_analysis_dispatches_status", table_name="analysis_dispatches")
    op.drop_table("analysis_dispatches")
