"""Add confirmation, follow-up and secondary-finding governance records."""
from alembic import op
import sqlalchemy as sa

revision = "0017_confirmation_followup_secondary_findings"
down_revision = "0016_technical_qc_assay_quality"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "confirmation_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_record_id", sa.Uuid(), sa.ForeignKey("confirmation_records.id"), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="NOT_REQUIRED"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("laboratory", sa.Text(), nullable=True),
        sa.Column("accession", sa.Text(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_confirmation_records_variant", "confirmation_records", ["analysis_id", "variant_id", "version"])
    op.create_table(
        "follow_up_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=True),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PLANNED"),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responsible_role", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_follow_up_plans_case", "follow_up_plans", ["case_id", "analysis_id"])
    op.create_table(
        "secondary_finding_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_decision_id", sa.Uuid(), sa.ForeignKey("secondary_finding_decisions.id"), nullable=True),
        sa.Column("policy_name", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("eligibility", sa.Text(), nullable=False, server_default="REVIEW"),
        sa.Column("consent_status", sa.Text(), nullable=False, server_default="NOT_DOCUMENTED"),
        sa.Column("disposition", sa.Text(), nullable=False, server_default="REVIEW"),
        sa.Column("status", sa.Text(), nullable=False, server_default="DRAFT"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("gene_disease_context", sa.JSON(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_id", "variant_id", "version"),
    )
    op.create_index("ix_secondary_finding_decisions_analysis", "secondary_finding_decisions", ["analysis_id", "variant_id", "version"])

def downgrade():
    op.drop_index("ix_secondary_finding_decisions_analysis", table_name="secondary_finding_decisions")
    op.drop_table("secondary_finding_decisions")
    op.drop_index("ix_follow_up_plans_case", table_name="follow_up_plans")
    op.drop_table("follow_up_plans")
    op.drop_index("ix_confirmation_records_variant", table_name="confirmation_records")
    op.drop_table("confirmation_records")
