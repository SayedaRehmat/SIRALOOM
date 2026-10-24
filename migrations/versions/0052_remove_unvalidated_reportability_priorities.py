"""Remove unvalidated numeric reportability priority fields.

Revision ID: 0052_remove_unvalidated_reportability_priorities
Revises: 0051_retire_unvalidated_inheritance_scores
"""

import sqlalchemy as sa
from alembic import op

revision = "0052_remove_unvalidated_reportability_priorities"
down_revision = "0051_retire_unvalidated_inheritance_scores"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("reportability_decisions", recreate="always") as batch:
            batch.alter_column(
                "priority_score",
                existing_type=sa.Integer(),
                existing_server_default=sa.text("0"),
                nullable=True,
                server_default=None,
            )
            batch.alter_column(
                "priority_band",
                existing_type=sa.Text(),
                existing_server_default=sa.text("'ROUTINE'"),
                nullable=True,
                server_default=None,
            )
    else:
        op.alter_column(
            "reportability_decisions",
            "priority_score",
            existing_type=sa.Integer(),
            existing_server_default=sa.text("0"),
            nullable=True,
            server_default=None,
        )
        op.alter_column(
            "reportability_decisions",
            "priority_band",
            existing_type=sa.Text(),
            existing_server_default=sa.text("'ROUTINE'"),
            nullable=True,
            server_default=None,
        )


def downgrade():
    # Historical values are retained, but values for decisions created under
    # policy v2 are intentionally NULL and cannot be reconstructed.
    raise RuntimeError(
        "Cannot restore non-null reportability priority fields: policy v2 does not generate scores."
    )
