"""Add durable logical genomic partition manifests for streaming workflows."""
from alembic import op
import sqlalchemy as sa

revision = "0018_analysis_partitions"
down_revision = "0017_confirmation_followup_secondary_findings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_partitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("partition_key", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("record_start", sa.BigInteger(), nullable=False),
        sa.Column("record_end", sa.BigInteger(), nullable=False),
        sa.Column("variant_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("input_artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_id", "step_id", "partition_key"),
    )
    op.create_index("ix_analysis_partitions_analysis_step", "analysis_partitions", ["analysis_id", "step_id", "ordinal"])


def downgrade():
    op.drop_index("ix_analysis_partitions_analysis_step", table_name="analysis_partitions")
    op.drop_table("analysis_partitions")
