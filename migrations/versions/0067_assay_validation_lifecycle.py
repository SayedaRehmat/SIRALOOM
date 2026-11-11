"""Add immutable assay validation submissions and approval decisions.

Revision ID: 0067_assay_validation_lifecycle
Revises: 0066_assay_version_governance
"""
from alembic import op
import sqlalchemy as sa

revision = "0067_assay_validation_lifecycle"
down_revision = "0066_assay_version_governance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assay_validation_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("assay_id", sa.Uuid(), sa.ForeignKey("assays.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("validation_type", sa.String(20), nullable=False),
        sa.Column("protocol_identifier", sa.Text(), nullable=False),
        sa.Column("protocol_version", sa.Text(), nullable=False),
        sa.Column("intended_use", sa.Text(), nullable=False),
        sa.Column("specimen_types", sa.JSON(), nullable=False),
        sa.Column("variant_classes", sa.JSON(), nullable=False),
        sa.Column("reference_builds", sa.JSON(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("workflow_version", sa.Text(), nullable=False),
        sa.Column("pipeline_components", sa.JSON(), nullable=False),
        sa.Column("performance_specifications", sa.JSON(), nullable=False),
        sa.Column("study_design_summary", sa.Text(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("evidence_manifest", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("assay_validation_submissions.id")),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("assay_id", "revision", name="uq_assay_validation_submission_revision"),
        sa.CheckConstraint("revision > 0", name="ck_assay_validation_revision_positive"),
        sa.CheckConstraint("validation_type IN ('VALIDATION','VERIFICATION')", name="ck_assay_validation_type"),
        sa.CheckConstraint("sample_count > 0", name="ck_assay_validation_sample_count_positive"),
    )
    op.create_index(
        "ix_assay_validation_org_assay",
        "assay_validation_submissions",
        ["organization_id", "assay_id", "revision"],
    )
    op.create_table(
        "assay_validation_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("submission_id", sa.Uuid(), sa.ForeignKey("assay_validation_submissions.id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.Text()),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('APPROVE','REJECT','SUSPEND','WITHDRAW','SUPERSEDE')",
            name="ck_assay_validation_decision",
        ),
        sa.CheckConstraint(
            "(decision != 'APPROVE') OR "
            "(evidence_reference IS NOT NULL AND effective_at IS NOT NULL "
            "AND expires_at IS NOT NULL AND expires_at > effective_at)",
            name="ck_assay_validation_approval_evidence_and_dates",
        ),
    )
    op.create_index(
        "ix_assay_validation_decision_latest",
        "assay_validation_decisions",
        ["submission_id", "created_at", "id"],
    )

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_assay_validation_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'assay validation submissions and decisions are append-only';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        for table, suffix in (
            ("assay_validation_submissions", "submission"),
            ("assay_validation_decisions", "decision"),
        ):
            op.execute(
                f"CREATE TRIGGER trg_assay_validation_{suffix}_immutable "
                f"BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION siraloom_reject_assay_validation_mutation()"
            )
    elif connection.dialect.name == "sqlite":
        for table, suffix in (
            ("assay_validation_submissions", "submission"),
            ("assay_validation_decisions", "decision"),
        ):
            op.execute(
                f"CREATE TRIGGER trg_assay_validation_{suffix}_immutable_update "
                f"BEFORE UPDATE ON {table} BEGIN "
                "SELECT RAISE(ABORT, 'assay validation submissions and decisions are append-only'); END"
            )
            op.execute(
                f"CREATE TRIGGER trg_assay_validation_{suffix}_immutable_delete "
                f"BEFORE DELETE ON {table} BEGIN "
                "SELECT RAISE(ABORT, 'assay validation submissions and decisions are append-only'); END"
            )


def downgrade():
    connection = op.get_bind()
    submissions = connection.execute(
        sa.text("SELECT COUNT(*) FROM assay_validation_submissions")
    ).scalar_one()
    decisions = connection.execute(
        sa.text("SELECT COUNT(*) FROM assay_validation_decisions")
    ).scalar_one()
    if submissions or decisions:
        raise RuntimeError(
            "Refusing to downgrade: assay validation evidence and decisions would be destroyed."
        )
    if connection.dialect.name == "postgresql":
        for table, suffix in (
            ("assay_validation_submissions", "submission"),
            ("assay_validation_decisions", "decision"),
        ):
            op.execute(f"DROP TRIGGER IF EXISTS trg_assay_validation_{suffix}_immutable ON {table}")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_assay_validation_mutation()")
    elif connection.dialect.name == "sqlite":
        for suffix in ("submission", "decision"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_assay_validation_{suffix}_immutable_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_assay_validation_{suffix}_immutable_delete")
    op.drop_index("ix_assay_validation_decision_latest", table_name="assay_validation_decisions")
    op.drop_table("assay_validation_decisions")
    op.drop_index("ix_assay_validation_org_assay", table_name="assay_validation_submissions")
    op.drop_table("assay_validation_submissions")
