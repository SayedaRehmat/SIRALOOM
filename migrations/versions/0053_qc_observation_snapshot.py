"""Persist the exact technical-QC observations used by each assessment.

Revision ID: 0053_qc_observation_snapshot
Revises: 0052_remove_unvalidated_reportability_priorities
"""

import sqlalchemy as sa
from alembic import op

revision = "0053_qc_observation_snapshot"
down_revision = "0052_remove_unvalidated_reportability_priorities"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "qc_assessments",
        sa.Column("observation_snapshot", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("qc_assessments", "observation_snapshot")
