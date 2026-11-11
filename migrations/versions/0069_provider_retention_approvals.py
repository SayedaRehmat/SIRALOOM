"""Persist release-specific raw provider retention approvals and decision history.

Revision ID: 0069_provider_retention_approvals
Revises: 0068_evidence_response_artifacts
"""
from alembic import op
import sqlalchemy as sa

revision = "0069_provider_retention_approvals"
down_revision = "0068_evidence_response_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_retention_approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("resource_discovery_id", sa.Uuid(), sa.ForeignKey("resource_discoveries.id"), nullable=False),
        sa.Column("release_identity", sa.Text(), nullable=False),
        sa.Column("permission_scope", sa.JSON(), nullable=False),
        sa.Column("license_url", sa.Text()),
        sa.Column("terms_url", sa.Text()),
        sa.Column("terms_evidence_artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id")),
        sa.Column("terms_evidence_sha256", sa.Text()),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="APPROVED"),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('APPROVED', 'REVOKED', 'EXPIRED')", name="ck_provider_retention_approval_status"),
        sa.CheckConstraint("json_array_length(permission_scope) > 0", name="ck_provider_retention_scope_nonempty"),
        sa.UniqueConstraint("organization_id", "resource_discovery_id", "version", name="uq_provider_retention_release_version"),
    )
    op.create_index(
        "ix_provider_retention_approval_lookup",
        "provider_retention_approvals",
        ["organization_id", "resource_discovery_id", "status"],
    )
    op.create_table(
        "provider_retention_approval_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("approval_id", sa.Uuid(), sa.ForeignKey("provider_retention_approvals.id"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("before_status", sa.Text()),
        sa.Column("after_status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("permission_scope", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('APPROVE', 'REVOKE', 'EXPIRE')", name="ck_provider_retention_action"),
    )
    op.create_index(
        "ix_provider_retention_actions_approval_created",
        "provider_retention_approval_actions",
        ["approval_id", "created_at"],
    )
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_provider_retention_action_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'provider retention approval actions are append-only';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_provider_retention_action_immutable
            BEFORE UPDATE OR DELETE ON provider_retention_approval_actions
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_provider_retention_action_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_provider_retention_action_immutable_update
            BEFORE UPDATE ON provider_retention_approval_actions
            BEGIN SELECT RAISE(ABORT, 'provider retention approval actions are append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_provider_retention_action_immutable_delete
            BEFORE DELETE ON provider_retention_approval_actions
            BEGIN SELECT RAISE(ABORT, 'provider retention approval actions are append-only'); END
        """)


def downgrade():
    connection = op.get_bind()
    count = connection.execute(sa.text(
        "SELECT COUNT(*) FROM provider_retention_approval_actions"
    )).scalar_one()
    if count:
        raise RuntimeError("Refusing to downgrade: provider retention approval decisions exist.")
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_provider_retention_action_immutable ON provider_retention_approval_actions")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_provider_retention_action_mutation()")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_provider_retention_action_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS trg_provider_retention_action_immutable_delete")
    op.drop_index("ix_provider_retention_actions_approval_created", table_name="provider_retention_approval_actions")
    op.drop_table("provider_retention_approval_actions")
    op.drop_index("ix_provider_retention_approval_lookup", table_name="provider_retention_approvals")
    op.drop_table("provider_retention_approvals")
