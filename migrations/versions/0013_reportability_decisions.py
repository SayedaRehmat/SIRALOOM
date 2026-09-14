"""Add first-class versioned reportability decisions."""
from alembic import op
import sqlalchemy as sa

revision = "0013_reportability_decisions"
down_revision = "0012_durable_analysis_queue"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "reportability_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("classification_id", sa.Uuid(), sa.ForeignKey("classifications.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_decision_id", sa.Uuid(), sa.ForeignKey("reportability_decisions.id"), nullable=True),
        sa.Column("policy_name", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("priority_band", sa.Text(), nullable=False, server_default="ROUTINE"),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("review_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reportability_decisions_analysis_variant", "reportability_decisions", ["analysis_id", "variant_id"])

def downgrade():
    op.drop_index("ix_reportability_decisions_analysis_variant", table_name="reportability_decisions")
    op.drop_table("reportability_decisions")
