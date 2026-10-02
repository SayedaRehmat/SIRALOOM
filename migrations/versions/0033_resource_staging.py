"""Add durable resource staging and integrity state."""

from alembic import op
import sqlalchemy as sa


revision = "0033_resource_staging"
down_revision = "0032_resource_deployment_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "resource_stagings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_version", sa.Text(), nullable=False),
        sa.Column("staging_key", sa.Text(), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("destination_uri", sa.Text(), nullable=False),
        sa.Column("storage_backend", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="DISCOVERED"),
        sa.Column("expected_sha256", sa.Text(), nullable=True),
        sa.Column("observed_sha256", sa.Text(), nullable=True),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("observed_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_id", "resource_version", "staging_key"),
    )
    op.create_index(
        "ix_resource_stagings_resource_status",
        "resource_stagings",
        ["resource_id", "status"],
    )


def downgrade():
    op.drop_index(
        "ix_resource_stagings_resource_status",
        table_name="resource_stagings",
    )
    op.drop_table("resource_stagings")
