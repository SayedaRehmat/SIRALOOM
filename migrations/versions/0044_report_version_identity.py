"""Enforce report version identity.

Revision ID: 0044_report_version_identity
Revises: 0043_classification_version_identity
"""

from alembic import op
import sqlalchemy as sa

revision = "0044_report_version_identity"
down_revision = "0043_classification_version_identity"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            """
            SELECT case_id, report_type, report_version, COUNT(*) AS duplicate_count
            FROM reports
            GROUP BY case_id, report_type, report_version
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicates is not None:
        raise RuntimeError(
            "Cannot add report version identity constraint: duplicate "
            "case_id/report_type/report_version rows already exist. Resolve "
            "the duplicate clinical report history explicitly before migrating."
        )

    op.create_index(
        "uq_report_version_identity",
        "reports",
        ["case_id", "report_type", "report_version"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_report_version_identity", table_name="reports")
