"""Govern active scientific resource identity in the registry."""

from alembic import op
import sqlalchemy as sa

revision = "0022_resource_registry_active_identity"
down_revision = "0021_reanalysis_change_awareness"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_resources_active_identity",
        "resources",
        ["name", "provider", "resource_type", "genome_build"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade():
    op.drop_index("uq_resources_active_identity", table_name="resources")
