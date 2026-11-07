"""Add immutable laboratory identity evidence for pedigree sample bindings.

Revision ID: 0064_pedigree_sample_identity_evidence
Revises: 0063_pedigree_sample_identity_bindings
"""
import sqlalchemy as sa
from alembic import op

revision = "0064_pedigree_sample_identity_evidence"
down_revision = "0063_pedigree_sample_identity_bindings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pedigree_sample_identity_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("method_version", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_evidence_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_fingerprint", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "evidence_type IN ('CHAIN_OF_CUSTODY', 'SAMPLE_IDENTITY_QC')",
            name="ck_pedigree_sample_identity_evidence_type",
        ),
        sa.CheckConstraint(
            "result IN ('PASS', 'FAIL', 'INDETERMINATE')",
            name="ck_pedigree_sample_identity_evidence_result",
        ),
        sa.CheckConstraint(
            "review_status IN ('PENDING', 'ACCEPTED', 'REJECTED')",
            name="ck_pedigree_sample_identity_evidence_review_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_pedigree_sample_identity_evidence_positive_version"),
        sa.CheckConstraint(
            "(review_status = 'PENDING' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR "
            "(review_status IN ('ACCEPTED', 'REJECTED') AND reviewed_by IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND review_reason IS NOT NULL)",
            name="ck_pedigree_sample_identity_evidence_review_provenance",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["binding_id"], ["pedigree_sample_bindings.id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["supersedes_evidence_id"], ["pedigree_sample_identity_evidence.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "evidence_fingerprint", name="uq_pedigree_sample_identity_evidence_fingerprint"),
        sa.UniqueConstraint("supersedes_evidence_id", name="uq_pedigree_sample_identity_evidence_successor"),
        sa.UniqueConstraint("binding_id", "evidence_type", "version", name="uq_pedigree_sample_identity_evidence_version"),
    )
    op.create_index(
        "ix_pedigree_sample_identity_evidence_binding_type",
        "pedigree_sample_identity_evidence",
        ["case_id", "binding_id", "evidence_type", "version"],
    )

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_pedigree_sample_identity_evidence_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'pedigree sample identity evidence is immutable; append a new version';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_pedigree_sample_identity_evidence_no_update
            BEFORE UPDATE OR DELETE ON pedigree_sample_identity_evidence
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_pedigree_sample_identity_evidence_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_pedigree_sample_identity_evidence_no_update
            BEFORE UPDATE ON pedigree_sample_identity_evidence
            BEGIN SELECT RAISE(ABORT, 'pedigree sample identity evidence is immutable; append a new version'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_pedigree_sample_identity_evidence_no_delete
            BEFORE DELETE ON pedigree_sample_identity_evidence
            BEGIN SELECT RAISE(ABORT, 'pedigree sample identity evidence is immutable; append a new version'); END
        """)


def downgrade():
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM pedigree_sample_identity_evidence")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Refusing to downgrade pedigree sample identity evidence: this would destroy laboratory provenance."
        )
    if connection.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_pedigree_sample_identity_evidence_no_update "
            "ON pedigree_sample_identity_evidence"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS siraloom_reject_pedigree_sample_identity_evidence_mutation()"
        )
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_pedigree_sample_identity_evidence_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_pedigree_sample_identity_evidence_no_delete")
    op.drop_index(
        "ix_pedigree_sample_identity_evidence_binding_type",
        table_name="pedigree_sample_identity_evidence",
    )
    op.drop_table("pedigree_sample_identity_evidence")
