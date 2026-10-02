"""Persist exact governed runtime resource execution provenance."""

from alembic import op
import sqlalchemy as sa


revision = "0031_resource_execution_records"
down_revision = "0030_workflow_decision_records"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "resource_execution_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("batch_key", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("requested_resource_id", sa.Uuid(), nullable=True),
        sa.Column("fallback_resource_id", sa.Uuid(), nullable=True),
        sa.Column("qualification_id", sa.Uuid(), nullable=False),
        sa.Column("qualification_version", sa.Text(), nullable=False),
        sa.Column("resource_version", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("provider_version", sa.Text(), nullable=False),
        sa.Column("access_method", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("dataset", sa.Text(), nullable=True),
        sa.Column("contract_hash", sa.Text(), nullable=False),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="STARTED"),
        sa.Column("request_fingerprint", sa.Text(), nullable=True),
        sa.Column("response_sha256", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["requested_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["fallback_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["qualification_id"], ["resource_qualifications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_resource_execution_records_analysis_step",
        "resource_execution_records",
        ["analysis_id", "step_id", "created_at"],
    )
    op.create_index(
        "ix_resource_execution_records_contract_hash",
        "resource_execution_records",
        ["contract_hash"],
    )


def downgrade():
    op.drop_index(
        "ix_resource_execution_records_contract_hash",
        table_name="resource_execution_records",
    )
    op.drop_index(
        "ix_resource_execution_records_analysis_step",
        table_name="resource_execution_records",
    )
    op.drop_table("resource_execution_records")
