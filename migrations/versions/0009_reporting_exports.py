"""Finalize immutable reports and add durable case exports."""
from alembic import op
import sqlalchemy as sa

revision = "0009_reporting_exports"
down_revision = "0008_review_workflow"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reports") as batch:
        batch.add_column(sa.Column("approved_by", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_reports_approved_by", "users", ["approved_by"], ["id"])

    op.create_table(
        "case_exports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("include_artifacts", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("include_reports", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("include_evidence", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("include_audit", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("include_provenance", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_case_exports_case_id", "case_exports", ["case_id"])


def downgrade():
    op.drop_index("ix_case_exports_case_id", table_name="case_exports")
    op.drop_table("case_exports")
    with op.batch_alter_table("reports") as batch:
        batch.drop_constraint("fk_reports_approved_by", type_="foreignkey")
        batch.drop_column("approved_at")
        batch.drop_column("approved_by")
