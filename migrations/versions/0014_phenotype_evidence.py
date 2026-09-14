"""Add structured phenotype observations for HPO-driven prioritization."""
from alembic import op
import sqlalchemy as sa

revision = "0014_phenotype_evidence"
down_revision = "0013_reportability_decisions"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "phenotype_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=True),
        sa.Column("hpo_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("onset", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="CLINICAL_INPUT"),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "analysis_id", "hpo_id", "present"),
    )
    op.create_index("ix_phenotype_observations_case_analysis", "phenotype_observations", ["case_id", "analysis_id"])

def downgrade():
    op.drop_index("ix_phenotype_observations_case_analysis", table_name="phenotype_observations")
    op.drop_table("phenotype_observations")
