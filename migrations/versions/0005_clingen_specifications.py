"""add ClinGen specification snapshots

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_clingen_specifications"
down_revision = "0004_population_analysis_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clingen_specifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("specification_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("framework", sa.Text(), nullable=False),
        sa.Column("source_iri", sa.Text(), nullable=True),
        sa.Column("modified_at", sa.Text(), nullable=True),
        sa.Column("gene_scope", sa.JSON(), nullable=False),
        sa.Column("disease_scope", sa.JSON(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validated_for_automation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("specification_id", "version", name="uq_clingen_specification_version"),
    )


def downgrade():
    op.drop_table("clingen_specifications")
