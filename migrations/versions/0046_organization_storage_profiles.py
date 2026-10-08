"""Add organization-scoped storage profiles.

Revision ID: 0046_organization_storage_profiles
Revises: 0045_confirmation_record_identity
"""

from alembic import op
import sqlalchemy as sa

revision = "0046_organization_storage_profiles"
down_revision = "0045_confirmation_record_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_storage_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("backend_type", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            "version",
            name="uq_org_storage_profile_version",
        ),
    )

    op.create_index(
        "uq_org_storage_profile_active",
        "organization_storage_profiles",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade():
    op.drop_index(
        "uq_org_storage_profile_active",
        table_name="organization_storage_profiles",
    )
    op.drop_table("organization_storage_profiles")
