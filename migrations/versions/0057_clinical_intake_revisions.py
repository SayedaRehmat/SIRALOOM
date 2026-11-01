"""Add append-only, versioned clinical intake revisions.

Revision ID: 0057_clinical_intake_revisions
Revises: 0056_phenotype_observation_fingerprint
"""
import sqlalchemy as sa
from alembic import op

revision = "0057_clinical_intake_revisions"
down_revision = "0056_phenotype_observation_fingerprint"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinical_intake_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("revision_fingerprint", sa.Text(), nullable=False),
        sa.Column("intake_status", sa.Text(), nullable=False),
        sa.Column("phenotype_review_status", sa.Text(), nullable=False),
        sa.Column("family_history_review_status", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("phenotype_review_note", sa.Text(), nullable=True),
        sa.Column("family_history_review_note", sa.Text(), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_clinical_intake_revision_positive_version"),
        sa.CheckConstraint(
            "intake_status IN ('DRAFT', 'COMPLETE', 'NOT_APPLICABLE')",
            name="ck_clinical_intake_revision_status",
        ),
        sa.CheckConstraint(
            "phenotype_review_status IN ('COMPLETE', 'NOT_ASSESSED', 'NOT_APPLICABLE', 'PENDING')",
            name="ck_clinical_intake_phenotype_review_status",
        ),
        sa.CheckConstraint(
            "family_history_review_status IN ('COMPLETE', 'NOT_ASSESSED', 'NOT_APPLICABLE', 'PENDING')",
            name="ck_clinical_intake_family_review_status",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "version", name="uq_clinical_intake_case_version"),
        sa.UniqueConstraint("case_id", "revision_fingerprint", name="uq_clinical_intake_case_fingerprint"),
    )
    op.create_index(
        "ix_clinical_intake_revisions_case_version",
        "clinical_intake_revisions",
        ["case_id", "version"],
        unique=False,
    )


def downgrade():
    connection = op.get_bind()
    revision_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM clinical_intake_revisions")
    ).scalar_one()
    if revision_count:
        raise RuntimeError(
            "Refusing to downgrade clinical intake revisions: this would destroy "
            "recorded clinical context and review attestations."
        )
    op.drop_index("ix_clinical_intake_revisions_case_version", table_name="clinical_intake_revisions")
    op.drop_table("clinical_intake_revisions")
