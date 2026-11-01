"""Persist immutable, provenance-backed specimen ploidy evidence revisions.

Revision ID: 0059_specimen_ploidy_evidence
Revises: 0058_artifact_upload_intents
"""
import sqlalchemy as sa
from alembic import op

revision = "0059_specimen_ploidy_evidence"
down_revision = "0058_artifact_upload_intents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "specimen_ploidy_evidence_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("specimen_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("revision_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reference_build", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("region_copy_number", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_specimen_ploidy_revision_positive_version"),
        sa.CheckConstraint("schema_version = 1", name="ck_specimen_ploidy_schema_version"),
        sa.CheckConstraint(
            "status IN ('VERIFIED', 'UNVERIFIED', 'CONFLICTED', 'MOSAIC_OR_COMPLEX')",
            name="ck_specimen_ploidy_evidence_status",
        ),
        sa.CheckConstraint(
            "(status != 'VERIFIED') OR "
            "(reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND source_type IS NOT NULL AND evidence_reference IS NOT NULL)",
            name="ck_specimen_ploidy_verified_provenance",
        ),
        sa.ForeignKeyConstraint(["specimen_id"], ["specimens.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["audit_event_id"], ["audit_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("specimen_id", "version", name="uq_specimen_ploidy_evidence_version"),
        sa.UniqueConstraint("specimen_id", "revision_fingerprint", name="uq_specimen_ploidy_evidence_fingerprint"),
        sa.UniqueConstraint("audit_event_id", name="uq_specimen_ploidy_evidence_audit_event"),
    )
    op.create_index(
        "ix_specimen_ploidy_evidence_specimen_version",
        "specimen_ploidy_evidence_revisions",
        ["specimen_id", "version"],
        unique=False,
    )


def downgrade():
    connection = op.get_bind()
    revision_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM specimen_ploidy_evidence_revisions")
    ).scalar_one()
    if revision_count:
        raise RuntimeError(
            "Refusing to downgrade specimen ploidy evidence revisions: this would "
            "destroy reviewed specimen evidence and its audit linkage."
        )
    op.drop_index(
        "ix_specimen_ploidy_evidence_specimen_version",
        table_name="specimen_ploidy_evidence_revisions",
    )
    op.drop_table("specimen_ploidy_evidence_revisions")
