"""Add durable, tenant-scoped artifact upload idempotency reservations.

Revision ID: 0058_artifact_upload_intents
Revises: 0056_phenotype_observation_fingerprint
"""
import sqlalchemy as sa
from alembic import op

revision = "0058_artifact_upload_intents"
down_revision = "0057_clinical_intake_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "artifact_upload_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('RESERVED', 'COMMITTED', 'RECOVERY_REQUIRED')",
            name="ck_artifact_upload_intent_status",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id"),
        sa.UniqueConstraint(
            "organization_id",
            "case_id",
            "idempotency_key_sha256",
            name="uq_artifact_upload_intent_scope_key",
        ),
    )
    op.create_index(
        "ix_artifact_upload_intents_status_created",
        "artifact_upload_intents",
        ["status", "created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_artifact_upload_intents_status_created",
        table_name="artifact_upload_intents",
    )
    op.drop_table("artifact_upload_intents")
