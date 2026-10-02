"""Add durable resource change impact tracking."""

from alembic import op
import sqlalchemy as sa

revision = "0035_resource_change_impacts"
down_revision = "0034_resource_discovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "resource_change_impacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("adoption_event_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("previous_resource_id", sa.Uuid(), nullable=False),
        sa.Column("previous_resource_version", sa.Text(), nullable=False),
        sa.Column("adopted_resource_id", sa.Uuid(), nullable=False),
        sa.Column("adopted_resource_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING_REANALYSIS"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["adoption_event_id"], ["audit_events.id"]),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["previous_resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["adopted_resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("adoption_event_id", "analysis_id", name="uq_resource_change_impact_event_analysis"),
    )
    op.create_index(
        "ix_resource_change_impacts_org_status",
        "resource_change_impacts",
        ["organization_id", "status"],
    )


def downgrade():
    op.drop_index("ix_resource_change_impacts_org_status", table_name="resource_change_impacts")
    op.drop_table("resource_change_impacts")
