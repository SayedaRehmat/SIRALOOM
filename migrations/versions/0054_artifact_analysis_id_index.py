"""Index artifacts by analysis for reportability and workflow lineage queries."""

from alembic import op

revision = "0054_artifact_analysis_id_index"
down_revision = "0053_qc_observation_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_artifacts_analysis_id",
        "artifacts",
        ["analysis_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_artifacts_analysis_id", table_name="artifacts")
