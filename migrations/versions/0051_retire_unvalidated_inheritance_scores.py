"""Retire heuristic inheritance scores and conclusions.

Revision ID: 0051_retire_unvalidated_inheritance_scores
Revises: 0050_phenotype_observation_status
"""

import sqlalchemy as sa
from alembic import op

revision = "0051_retire_unvalidated_inheritance_scores"
down_revision = "0050_phenotype_observation_status"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("inheritance_assessments", recreate="always") as batch:
            batch.alter_column(
                "score",
                existing_type=sa.Integer(),
                nullable=True,
            )
    else:
        op.alter_column(
            "inheritance_assessments",
            "score",
            existing_type=sa.Integer(),
            nullable=True,
        )

    op.execute(
        sa.text(
            "UPDATE inheritance_assessments "
            "SET score = NULL, "
            "status = CASE WHEN status IN ('CONSISTENT', 'CONTRADICTED') "
            "THEN 'REQUIRES_REVIEW' ELSE status END, "
            "rationale = CASE WHEN status IN ('CONSISTENT', 'CONTRADICTED') "
            "THEN 'Retired unvalidated heuristic conclusion. Review the recorded family observations.' "
            "ELSE rationale END"
        )
    )


def downgrade():
    # The superseded numeric results are intentionally not reconstructed.
    # Reintroducing them would restore unvalidated interpretation claims.
    pass
