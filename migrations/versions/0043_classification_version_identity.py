"""Enforce classification version identity.

Revision ID: 0043_classification_version_identity
Revises: 0042_reportability_decision_identity
"""

from alembic import op
import sqlalchemy as sa

revision = "0043_classification_version_identity"
down_revision = "0042_reportability_decision_identity"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            """
            SELECT analysis_id, variant_id, version, COUNT(*) AS duplicate_count
            FROM classifications
            GROUP BY analysis_id, variant_id, version
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicates is not None:
        raise RuntimeError(
            "Cannot add classification version identity constraint: duplicate "
            "analysis_id/variant_id/version rows already exist. Resolve the "
            "duplicate classification history explicitly before migrating."
        )

    op.create_index(
        "uq_classification_version_identity",
        "classifications",
        ["analysis_id", "variant_id", "version"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "uq_classification_version_identity",
        table_name="classifications",
    )
