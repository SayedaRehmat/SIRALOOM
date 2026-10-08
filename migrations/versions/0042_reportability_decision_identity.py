"""Enforce reportability decision version identity.

Revision ID: 0042_reportability_decision_identity
Revises: 0041_annotation_observation_identity
"""

from alembic import op
import sqlalchemy as sa

revision = "0042_reportability_decision_identity"
down_revision = "0041_annotation_observation_identity"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            """
            SELECT analysis_id, variant_id, version, COUNT(*) AS duplicate_count
            FROM reportability_decisions
            GROUP BY analysis_id, variant_id, version
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicates is not None:
        raise RuntimeError(
            "Cannot add reportability decision identity constraint: duplicate "
            "analysis_id/variant_id/version rows already exist. Resolve the "
            "duplicate reportability history explicitly before migrating."
        )

    op.create_index(
        "uq_reportability_decision_identity",
        "reportability_decisions",
        ["analysis_id", "variant_id", "version"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "uq_reportability_decision_identity",
        table_name="reportability_decisions",
    )
