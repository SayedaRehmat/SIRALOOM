"""Persist immutable, qualified caller/assay ploidy policy revisions.

Revision ID: 0060_caller_ploidy_policy_revisions
Revises: 0059_specimen_ploidy_evidence
"""
import sqlalchemy as sa
from alembic import op

revision = "0060_caller_ploidy_policy_revisions"
down_revision = "0059_specimen_ploidy_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "caller_ploidy_policy_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assay_id", sa.Uuid(), nullable=False),
        sa.Column("caller_id", sa.Text(), nullable=False),
        sa.Column("caller_version", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("reference_build", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("validation_evidence_reference", sa.Text(), nullable=True),
        sa.Column("region_copy_number_to_gt_ploidy", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("qualified_by", sa.Uuid(), nullable=True),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revision_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("schema_version = 1", name="ck_caller_ploidy_policy_schema_version"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'QUALIFIED', 'RETIRED')",
            name="ck_caller_ploidy_policy_status",
        ),
        sa.CheckConstraint(
            "(status != 'QUALIFIED') OR "
            "(qualified_by IS NOT NULL AND qualified_at IS NOT NULL "
            "AND validation_evidence_reference IS NOT NULL)",
            name="ck_caller_ploidy_policy_qualified_provenance",
        ),
        sa.ForeignKeyConstraint(["assay_id"], ["assays.id"]),
        sa.ForeignKeyConstraint(["qualified_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["audit_event_id"], ["audit_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assay_id", "caller_id", "caller_version", "policy_version", "reference_build", "status",
            name="uq_caller_ploidy_policy_exact_version_status",
        ),
        sa.UniqueConstraint("assay_id", "revision_fingerprint", name="uq_caller_ploidy_policy_fingerprint"),
        sa.UniqueConstraint("audit_event_id", name="uq_caller_ploidy_policy_audit_event"),
    )
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_caller_ploidy_policy_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'caller ploidy policy revisions are append-only';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_caller_ploidy_policy_no_update
            BEFORE UPDATE OR DELETE ON caller_ploidy_policy_revisions
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_caller_ploidy_policy_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_caller_ploidy_policy_no_update
            BEFORE UPDATE ON caller_ploidy_policy_revisions
            BEGIN SELECT RAISE(ABORT, 'caller ploidy policy revisions are append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_caller_ploidy_policy_no_delete
            BEFORE DELETE ON caller_ploidy_policy_revisions
            BEGIN SELECT RAISE(ABORT, 'caller ploidy policy revisions are append-only'); END
        """)
    op.create_index(
        "ix_caller_ploidy_policy_assay_caller_build_status",
        "caller_ploidy_policy_revisions",
        ["assay_id", "caller_id", "caller_version", "reference_build", "status"],
        unique=False,
    )


def downgrade():
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM caller_ploidy_policy_revisions")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Refusing to downgrade caller ploidy policy revisions: this would "
            "destroy versioned assay qualification evidence."
        )
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_caller_ploidy_policy_no_update ON caller_ploidy_policy_revisions")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_caller_ploidy_policy_mutation()")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_caller_ploidy_policy_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_caller_ploidy_policy_no_delete")
    op.drop_index(
        "ix_caller_ploidy_policy_assay_caller_build_status",
        table_name="caller_ploidy_policy_revisions",
    )
    op.drop_table("caller_ploidy_policy_revisions")
