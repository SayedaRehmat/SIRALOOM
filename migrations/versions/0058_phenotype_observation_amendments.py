"""Add append-only phenotype observation amendment events.

Revision ID: 0058_phenotype_observation_amendments
Revises: 0057_clinical_intake_revisions
"""
import sqlalchemy as sa
from alembic import op

revision = "0058_phenotype_observation_amendments"
down_revision = "0057_clinical_intake_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "phenotype_observation_amendments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("replacement_observation_id", sa.Uuid(), nullable=True),
        sa.Column("amendment_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("amendment_fingerprint", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amendment_type IN ('SUPERSEDED', 'RETRACTED')", name="ck_phenotype_amendment_type"),
        sa.CheckConstraint(
            "(amendment_type = 'SUPERSEDED' AND replacement_observation_id IS NOT NULL) OR "
            "(amendment_type = 'RETRACTED' AND replacement_observation_id IS NULL)",
            name="ck_phenotype_amendment_replacement",
        ),
        sa.CheckConstraint(
            "replacement_observation_id IS NULL OR observation_id <> replacement_observation_id",
            name="ck_phenotype_amendment_not_self_replacement",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["observation_id"], ["phenotype_observations.id"]),
        sa.ForeignKeyConstraint(["replacement_observation_id"], ["phenotype_observations.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_id", name="uq_phenotype_amendment_observation"),
        sa.UniqueConstraint("case_id", "amendment_fingerprint", name="uq_phenotype_amendment_case_fingerprint"),
    )
    op.create_index(
        "ix_phenotype_amendments_case_recorded",
        "phenotype_observation_amendments",
        ["case_id", "recorded_at"],
        unique=False,
    )


def downgrade():
    connection = op.get_bind()
    amendment_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM phenotype_observation_amendments")
    ).scalar_one()
    if amendment_count:
        raise RuntimeError(
            "Refusing to downgrade phenotype amendments: this would destroy clinical correction and retraction history."
        )
    op.drop_index("ix_phenotype_amendments_case_recorded", table_name="phenotype_observation_amendments")
    op.drop_table("phenotype_observation_amendments")
