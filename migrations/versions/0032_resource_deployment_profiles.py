"""Add explicit trial/laboratory resource deployment profiles."""

from alembic import op
import sqlalchemy as sa


revision = "0032_resource_deployment_profiles"
down_revision = "0031_resource_execution_records"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "resource_deployment_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("profile_type", sa.Text(), nullable=False),
        sa.Column("profile_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )
    op.create_index(
        "ix_resource_deployment_profiles_type_status",
        "resource_deployment_profiles",
        ["profile_type", "status"],
    )


def downgrade():
    op.drop_index(
        "ix_resource_deployment_profiles_type_status",
        table_name="resource_deployment_profiles",
    )
    op.drop_table("resource_deployment_profiles")
