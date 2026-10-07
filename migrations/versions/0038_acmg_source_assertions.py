"""Persist criterion-level source ACMG/ClinGen assertions separately from classification."""
from alembic import op
import sqlalchemy as sa

revision = "0038_acmg_source_assertions"
down_revision = "0037_merge_organization_invitations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "acmg_source_assertions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("criterion", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("strength", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("source_version", sa.Text(), nullable=True),
        sa.Column("source_record_id", sa.Text(), nullable=True),
        sa.Column("source_classification", sa.Text(), nullable=True),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("gene", sa.Text(), nullable=True),
        sa.Column("mondo_id", sa.Text(), nullable=True),
        sa.Column("expert_panel", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("pmids", sa.JSON(), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("assertion_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["variant_id"], ["variants.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assertion_fingerprint"),
        sa.UniqueConstraint("analysis_id", "evidence_id", "criterion"),
    )


def downgrade():
    op.drop_table("acmg_source_assertions")
