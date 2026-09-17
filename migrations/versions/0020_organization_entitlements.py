"""Add organization_entitlements for trial/plan licensing and usage limits."""
from alembic import op
import sqlalchemy as sa

revision = "0020_organization_entitlements"
down_revision = "0019_partition_scheduler_resources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_entitlements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False, unique=True),
        sa.Column("plan", sa.Text(), nullable=False, server_default="TRIAL"),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("max_analyses", sa.Integer(), nullable=True),
        sa.Column("analyses_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_vcf_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_organization_entitlements_org", "organization_entitlements", ["organization_id"]
    )


def downgrade():
    op.drop_index("ix_organization_entitlements_org", table_name="organization_entitlements")
    op.drop_table("organization_entitlements")
