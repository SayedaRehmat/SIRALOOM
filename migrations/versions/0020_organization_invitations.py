"""Add durable organization invitations for multi-tenant onboarding."""
from alembic import op
import sqlalchemy as sa

revision = "0020_organization_invitations"
down_revision = "0019_partition_scheduler_resources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("invited_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("accepted_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_organization_invitations_org_status",
        "organization_invitations",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_organization_invitations_email_status",
        "organization_invitations",
        ["email", "status"],
    )


def downgrade():
    op.drop_index("ix_organization_invitations_email_status", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_org_status", table_name="organization_invitations")
    op.drop_table("organization_invitations")
