"""Add durable workflow decision records."""

from alembic import op
import sqlalchemy as sa


revision = "0030_workflow_decision_records"
down_revision = "0029_resource_organization_approval"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_decision_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome_kind", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fallback_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lab_action_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("fallback_resource_id", sa.Uuid(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["fallback_resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workflow_decision_records_analysis_step",
        "workflow_decision_records",
        ["analysis_id", "step_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_workflow_decision_records_analysis_step", table_name="workflow_decision_records")
    op.drop_table("workflow_decision_records")
