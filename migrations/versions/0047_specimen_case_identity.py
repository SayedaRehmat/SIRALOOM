"""Enforce specimen identifier uniqueness within a case.

Revision ID: 0047_specimen_case_identity
Revises: 0046_organization_storage_profiles
"""

from alembic import op
import sqlalchemy as sa

revision = "0047_specimen_case_identity"
down_revision = "0046_organization_storage_profiles"
branch_labels = None
depends_on = None


def upgrade():
    # Never delete or silently rename clinical records during a schema migration.
    # Require an operator to resolve any legacy collisions explicitly first.
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            """
            SELECT case_id, specimen_identifier, COUNT(*) AS row_count
            FROM specimens
            WHERE specimen_identifier IS NOT NULL
            GROUP BY case_id, specimen_identifier
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            "Cannot enforce specimen identity: duplicate specimen_identifier "
            f"{duplicate.specimen_identifier!r} exists in case {duplicate.case_id}. "
            "Resolve the duplicate specimen records explicitly, then rerun migration 0047."
        )

    # Batch mode supports SQLite CI/dev databases and emits the equivalent
    # ALTER TABLE constraint operation on PostgreSQL.
    with op.batch_alter_table("specimens") as batch_op:
        batch_op.create_unique_constraint(
            "uq_specimen_case_identifier",
            ["case_id", "specimen_identifier"],
        )


def downgrade():
    with op.batch_alter_table("specimens") as batch_op:
        batch_op.drop_constraint(
            "uq_specimen_case_identifier",
            type_="unique",
        )
