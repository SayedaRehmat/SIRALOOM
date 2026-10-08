"""Add confirmation record version identity constraint.

Revision ID: 0045_confirmation_record_identity
Revises: 0044_report_version_identity
"""
from alembic import op
import sqlalchemy as sa

revision = "0045_confirmation_record_identity"
down_revision = "0044_report_version_identity"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            """
            SELECT analysis_id, variant_id, version, COUNT(*) AS row_count
            FROM confirmation_records
            GROUP BY analysis_id, variant_id, version
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            "Cannot add confirmation record identity constraint: duplicate "
            "(analysis_id, variant_id, version) rows already exist. "
            "Resolve clinical-history duplicates explicitly before migrating."
        )

    op.create_unique_constraint(
        "uq_confirmation_record_version_identity",
        "confirmation_records",
        ["analysis_id", "variant_id", "version"],
    )


def downgrade():
    op.drop_constraint(
        "uq_confirmation_record_version_identity",
        "confirmation_records",
        type_="unique",
    )
