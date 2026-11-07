"""Add immutable, versioned family-member/specimen/VCF-sample bindings.

Revision ID: 0063_pedigree_sample_identity_bindings
Revises: 0062_phenotype_observation_amendments
"""
import sqlalchemy as sa
from alembic import op

revision = "0063_pedigree_sample_identity_bindings"
down_revision = "0062_phenotype_observation_amendments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pedigree_sample_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("pedigree_member_id", sa.Uuid(), nullable=False),
        sa.Column("specimen_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_sha256", sa.Text(), nullable=False),
        sa.Column("sample_name", sa.Text(), nullable=False),
        sa.Column("binding_status", sa.Text(), nullable=False, server_default="UNVERIFIED"),
        sa.Column("binding_method", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_binding_id", sa.Uuid(), nullable=True),
        sa.Column("binding_fingerprint", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "binding_status IN ('UNVERIFIED', 'VERIFIED', 'REJECTED')",
            name="ck_pedigree_sample_binding_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_pedigree_sample_binding_version_positive"),
        sa.CheckConstraint(
            "(binding_status = 'UNVERIFIED' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR "
            "(binding_status IN ('VERIFIED', 'REJECTED') AND reviewed_by IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND review_reason IS NOT NULL)",
            name="ck_pedigree_sample_binding_review_provenance",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["pedigree_member_id"], ["pedigree_members.id"]),
        sa.ForeignKeyConstraint(["specimen_id"], ["specimens.id"]),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["supersedes_binding_id"], ["pedigree_sample_bindings.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "binding_fingerprint", name="uq_pedigree_sample_binding_fingerprint"),
        sa.UniqueConstraint(
            "case_id", "pedigree_member_id", "specimen_id", "analysis_id",
            "artifact_id", "sample_name", "version",
            name="uq_pedigree_sample_binding_version",
        ),
    )
    op.create_index(
        "ix_pedigree_sample_bindings_member_specimen",
        "pedigree_sample_bindings",
        ["case_id", "pedigree_member_id", "specimen_id"],
    )
    op.create_index(
        "ix_pedigree_sample_bindings_analysis_artifact",
        "pedigree_sample_bindings",
        ["analysis_id", "artifact_id"],
    )

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_pedigree_sample_binding_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'pedigree sample bindings are immutable; append a new version';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_pedigree_sample_bindings_no_update
            BEFORE UPDATE OR DELETE ON pedigree_sample_bindings
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_pedigree_sample_binding_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_pedigree_sample_bindings_no_update
            BEFORE UPDATE ON pedigree_sample_bindings
            BEGIN SELECT RAISE(ABORT, 'pedigree sample bindings are immutable; append a new version'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_pedigree_sample_bindings_no_delete
            BEFORE DELETE ON pedigree_sample_bindings
            BEGIN SELECT RAISE(ABORT, 'pedigree sample bindings are immutable; append a new version'); END
        """)


def downgrade():
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM pedigree_sample_bindings")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Refusing to downgrade family sample identity bindings: this would destroy identity provenance."
        )
    if connection.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_pedigree_sample_bindings_no_update "
            "ON pedigree_sample_bindings"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS siraloom_reject_pedigree_sample_binding_mutation()"
        )
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_pedigree_sample_bindings_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_pedigree_sample_bindings_no_delete")
    op.drop_index("ix_pedigree_sample_bindings_analysis_artifact", table_name="pedigree_sample_bindings")
    op.drop_index("ix_pedigree_sample_bindings_member_specimen", table_name="pedigree_sample_bindings")
    op.drop_table("pedigree_sample_bindings")
