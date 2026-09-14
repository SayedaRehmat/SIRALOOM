"""Add technical QC observations, assay QC profiles and analysis QC assessments."""
from alembic import op
import sqlalchemy as sa

revision = "0016_technical_qc_assay_quality"
down_revision = "0015_pedigree_inheritance_segregation"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("analyses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("assay_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key("fk_analyses_assay_id", "assays", ["assay_id"], ["id"])
    op.create_table(
        "technical_qc_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("metric_unit", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="NOT_ASSESSED"),
        sa.Column("source", sa.Text(), nullable=False, server_default="LAB_QC"),
        sa.Column("source_version", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_technical_qc_observations_analysis", "technical_qc_observations", ["analysis_id"])
    op.create_table(
        "qc_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("assay_id", sa.Uuid(), sa.ForeignKey("assays.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("profile_name", sa.Text(), nullable=True),
        sa.Column("profile_version", sa.Text(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("evaluated_rules", sa.JSON(), nullable=False),
        sa.Column("gate_status", sa.Text(), nullable=False, server_default="NOT_ASSESSED"),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qc_assessments_analysis", "qc_assessments", ["analysis_id"])

def downgrade():
    with op.batch_alter_table("analyses", schema=None) as batch_op:
        batch_op.drop_constraint("fk_analyses_assay_id", type_="foreignkey")
        batch_op.drop_column("assay_id")
    op.drop_index("ix_qc_assessments_analysis", table_name="qc_assessments")
    op.drop_table("qc_assessments")
    op.drop_index("ix_technical_qc_observations_analysis", table_name="technical_qc_observations")
    op.drop_table("technical_qc_observations")
