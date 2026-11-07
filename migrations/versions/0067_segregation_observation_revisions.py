"""Add append-only revisions to manually reported segregation observations.

Revision ID: 0067_segregation_observation_revisions
Revises: 0066_family_genotype_matrix_snapshots
"""
import sqlalchemy as sa
from alembic import op

revision = "0067_segregation_observation_revisions"
down_revision = "0066_family_genotype_matrix_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "segregation_observation_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("root_observation_id", sa.Uuid(), nullable=False),
        sa.Column("supersedes_revision_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("observation_fingerprint", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 2", name="ck_segregation_observation_revision_version"),
        sa.CheckConstraint("length(observation_fingerprint) = 64", name="ck_segregation_observation_revision_fingerprint_length"),
        sa.ForeignKeyConstraint(["root_observation_id"], ["segregation_observations.id"]),
        sa.ForeignKeyConstraint(["supersedes_revision_id"], ["segregation_observation_revisions.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("root_observation_id", "version", name="uq_segregation_observation_revision_version"),
        sa.UniqueConstraint("root_observation_id", "observation_fingerprint", name="uq_segregation_observation_revision_fingerprint"),
        sa.UniqueConstraint("supersedes_revision_id", name="uq_segregation_observation_revision_successor"),
    )
    op.create_index(
        "ix_segregation_observation_revision_root",
        "segregation_observation_revisions",
        ["root_observation_id", "version"],
    )

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_segregation_observation_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'segregation observations are append-only';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_segregation_observation_no_update
            BEFORE UPDATE OR DELETE ON segregation_observations
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_segregation_observation_mutation()
        """)
        op.execute("""
            CREATE TRIGGER trg_segregation_observation_revision_no_update
            BEFORE UPDATE OR DELETE ON segregation_observation_revisions
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_segregation_observation_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        for table, stem in (
            ("segregation_observations", "segregation_observation"),
            ("segregation_observation_revisions", "segregation_observation_revision"),
        ):
            op.execute(f"""
                CREATE TRIGGER trg_{stem}_no_update
                BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'segregation observations are append-only'); END
            """)
            op.execute(f"""
                CREATE TRIGGER trg_{stem}_no_delete
                BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'segregation observations are append-only'); END
            """)


def downgrade():
    connection = op.get_bind()
    revision_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM segregation_observation_revisions")
    ).scalar_one()
    root_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM segregation_observations")
    ).scalar_one()
    if revision_count or root_count:
        raise RuntimeError(
            "Refusing to downgrade: segregation observation history is immutable clinical review provenance."
        )

    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_segregation_observation_no_update ON segregation_observations")
        op.execute("DROP TRIGGER IF EXISTS trg_segregation_observation_revision_no_update ON segregation_observation_revisions")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_segregation_observation_mutation()")
    elif connection.dialect.name == "sqlite":
        for trigger in (
            "trg_segregation_observation_no_update",
            "trg_segregation_observation_no_delete",
            "trg_segregation_observation_revision_no_update",
            "trg_segregation_observation_revision_no_delete",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    op.drop_index(
        "ix_segregation_observation_revision_root",
        table_name="segregation_observation_revisions",
    )
    op.drop_table("segregation_observation_revisions")
