"""Persist immutable source-bound family genotype matrix snapshots.

Revision ID: 0066_family_genotype_matrix_snapshots
Revises: 0065_inheritance_family_matrix_fingerprint
"""
import sqlalchemy as sa
from alembic import op

revision = "0066_family_genotype_matrix_snapshots"
down_revision = "0065_inheritance_family_matrix_fingerprint"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "family_genotype_matrix_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("matrix_fingerprint", sa.Text(), nullable=False),
        sa.Column("matrix_payload", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("schema_version = 1", name="ck_family_genotype_matrix_snapshot_schema"),
        sa.CheckConstraint("length(matrix_fingerprint) = 64", name="ck_family_genotype_matrix_snapshot_fingerprint_length"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"]),
        sa.ForeignKeyConstraint(["variant_id"], ["variants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id", "matrix_fingerprint",
            name="uq_family_genotype_matrix_snapshot_fingerprint",
        ),
    )
    op.create_index(
        "ix_family_genotype_matrix_snapshot_analysis_variant",
        "family_genotype_matrix_snapshots",
        ["analysis_id", "variant_id"],
    )
    # Batch mode preserves SQLite migration support while emitting ordinary
    # ALTER TABLE operations on PostgreSQL.
    with op.batch_alter_table("inheritance_assessments") as batch_op:
        batch_op.add_column(
            sa.Column("family_matrix_snapshot_id", sa.Uuid(), nullable=True),
        )
        batch_op.create_foreign_key(
            "fk_inheritance_assessment_family_matrix_snapshot",
            "family_genotype_matrix_snapshots",
            ["family_matrix_snapshot_id"],
            ["id"],
        )

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_family_genotype_matrix_snapshot_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'family genotype matrix snapshots are immutable';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_family_genotype_matrix_snapshot_no_update
            BEFORE UPDATE OR DELETE ON family_genotype_matrix_snapshots
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_family_genotype_matrix_snapshot_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_family_genotype_matrix_snapshot_no_update
            BEFORE UPDATE ON family_genotype_matrix_snapshots
            BEGIN SELECT RAISE(ABORT, 'family genotype matrix snapshots are immutable'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_family_genotype_matrix_snapshot_no_delete
            BEFORE DELETE ON family_genotype_matrix_snapshots
            BEGIN SELECT RAISE(ABORT, 'family genotype matrix snapshots are immutable'); END
        """)


def downgrade():
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM family_genotype_matrix_snapshots")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Refusing to downgrade: immutable family genotype matrix snapshots are referenced by clinical assessments."
        )
    if connection.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_family_genotype_matrix_snapshot_no_update "
            "ON family_genotype_matrix_snapshots"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS siraloom_reject_family_genotype_matrix_snapshot_mutation()"
        )
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_family_genotype_matrix_snapshot_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_family_genotype_matrix_snapshot_no_delete")
    with op.batch_alter_table("inheritance_assessments") as batch_op:
        batch_op.drop_constraint(
            "fk_inheritance_assessment_family_matrix_snapshot",
            type_="foreignkey",
        )
        batch_op.drop_column("family_matrix_snapshot_id")
    op.drop_index(
        "ix_family_genotype_matrix_snapshot_analysis_variant",
        table_name="family_genotype_matrix_snapshots",
    )
    op.drop_table("family_genotype_matrix_snapshots")
