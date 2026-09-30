"""Add reanalysis lineage, immutable resource snapshots, change events, candidates and notifications."""
from alembic import op
import sqlalchemy as sa

revision = "0021_reanalysis_change_awareness"
down_revision = "0020_organization_entitlements"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("analyses", sa.Column("analysis_version", sa.Integer(), nullable=False, server_default="1"))

    op.create_table(
        "analysis_resource_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=True),
        sa.Column("resource_kind", sa.Text(), nullable=False),
        sa.Column("resource_name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("version", sa.Text(), nullable=True),
        sa.Column("checksum", sa.Text(), nullable=True),
        sa.Column("genome_build", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_id", "resource_kind", "resource_name", "version", "checksum"),
    )

    op.create_table(
        "reanalysis_change_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=True),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column("resource_kind", sa.Text(), nullable=False),
        sa.Column("resource_name", sa.Text(), nullable=False),
        sa.Column("previous_version", sa.Text(), nullable=True),
        sa.Column("new_version", sa.Text(), nullable=True),
        sa.Column("previous_checksum", sa.Text(), nullable=True),
        sa.Column("new_checksum", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )

    op.create_table(
        "reanalysis_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("parent_analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("change_event_id", sa.Uuid(), sa.ForeignKey("reanalysis_change_events.id"), nullable=True),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column("earliest_affected_step", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("child_analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("parent_analysis_id", "change_event_id"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("notification_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="UNREAD"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=True),
        sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("reanalysis_candidates.id"), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_analysis_resource_snapshots_analysis", "analysis_resource_snapshots", ["analysis_id"])
    op.create_index("ix_reanalysis_candidates_org_status", "reanalysis_candidates", ["organization_id", "status"])
    op.create_index("ix_notifications_user_status", "notifications", ["user_id", "status"])


def downgrade():
    op.drop_index("ix_notifications_user_status", table_name="notifications")
    op.drop_index("ix_reanalysis_candidates_org_status", table_name="reanalysis_candidates")
    op.drop_index("ix_analysis_resource_snapshots_analysis", table_name="analysis_resource_snapshots")
    op.drop_table("notifications")
    op.drop_table("reanalysis_candidates")
    op.drop_table("reanalysis_change_events")
    op.drop_table("analysis_resource_snapshots")
    op.drop_column("analyses", "analysis_version")
