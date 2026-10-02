"""Add durable resource discovery provenance."""

from alembic import op
import sqlalchemy as sa

revision = "0034_resource_discovery"
down_revision = "0033_resource_staging"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "resource_discoveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("canonical_source_url", sa.Text(), nullable=False),
        sa.Column("artifact_url", sa.Text(), nullable=False),
        sa.Column("release_identity", sa.Text(), nullable=False),
        sa.Column("access_mode", sa.Text(), nullable=False),
        sa.Column("license_status", sa.Text(), nullable=False),
        sa.Column("license_url", sa.Text(), nullable=True),
        sa.Column("terms_url", sa.Text(), nullable=True),
        sa.Column("checksum_status", sa.Text(), nullable=False),
        sa.Column("expected_sha256", sa.Text(), nullable=True),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("authority_evidence_url", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="DISCOVERED"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_id", "release_identity", "artifact_url"),
    )
    op.create_index(
        "ix_resource_discoveries_resource_status",
        "resource_discoveries",
        ["resource_id", "status"],
    )


def downgrade():
    op.drop_index("ix_resource_discoveries_resource_status", table_name="resource_discoveries")
    op.drop_table("resource_discoveries")
