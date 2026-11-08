"""Add append-only pedigree member and relationship lifecycle revisions.

Revision ID: 0068_pedigree_member_relationship_revisions
Revises: 0067_segregation_observation_revisions
"""
import sqlalchemy as sa
from alembic import op

revision = "0068_pedigree_member_relationship_revisions"
down_revision = "0067_segregation_observation_revisions"
branch_labels = None
depends_on = None


def _create_immutable_triggers(table: str, stem: str) -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute(f"""
            CREATE TRIGGER trg_{stem}_no_update_delete
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_pedigree_revision_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute(f"""
            CREATE TRIGGER trg_{stem}_no_update
            BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, 'pedigree lifecycle records are append-only'); END
        """)
        op.execute(f"""
            CREATE TRIGGER trg_{stem}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, 'pedigree lifecycle records are append-only'); END
        """)


def upgrade():
    op.create_table(
        "pedigree_member_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("supersedes_revision_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("revision_fingerprint", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 2", name="ck_pedigree_member_revision_version"),
        sa.CheckConstraint("revision_type IN ('CORRECTED', 'RETRACTED')", name="ck_pedigree_member_revision_type"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_pedigree_member_revision_reason"),
        sa.CheckConstraint("length(revision_fingerprint) = 64", name="ck_pedigree_member_revision_fingerprint"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["member_id"], ["pedigree_members.id"]),
        sa.ForeignKeyConstraint(["supersedes_revision_id"], ["pedigree_member_revisions.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id", "version", name="uq_pedigree_member_revision_version"),
        sa.UniqueConstraint("supersedes_revision_id", name="uq_pedigree_member_revision_successor"),
        sa.UniqueConstraint("case_id", "revision_fingerprint", name="uq_pedigree_member_revision_fingerprint"),
    )
    op.create_index(
        "ix_pedigree_member_revisions_member_version",
        "pedigree_member_revisions", ["member_id", "version"],
    )

    op.create_table(
        "pedigree_relationship_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_id", sa.Uuid(), nullable=False),
        sa.Column("supersedes_revision_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("revision_fingerprint", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 2", name="ck_pedigree_relationship_revision_version"),
        sa.CheckConstraint("revision_type IN ('CORRECTED', 'RETRACTED')", name="ck_pedigree_relationship_revision_type"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_pedigree_relationship_revision_reason"),
        sa.CheckConstraint("length(revision_fingerprint) = 64", name="ck_pedigree_relationship_revision_fingerprint"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["relationship_id"], ["pedigree_relationships.id"]),
        sa.ForeignKeyConstraint(["supersedes_revision_id"], ["pedigree_relationship_revisions.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("relationship_id", "version", name="uq_pedigree_relationship_revision_version"),
        sa.UniqueConstraint("supersedes_revision_id", name="uq_pedigree_relationship_revision_successor"),
        sa.UniqueConstraint("case_id", "revision_fingerprint", name="uq_pedigree_relationship_revision_fingerprint"),
    )
    op.create_index(
        "ix_pedigree_relationship_revisions_relationship_version",
        "pedigree_relationship_revisions", ["relationship_id", "version"],
    )

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_pedigree_revision_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'pedigree lifecycle records are append-only';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
    _create_immutable_triggers("pedigree_members", "pedigree_member")
    _create_immutable_triggers("pedigree_relationships", "pedigree_relationship")
    _create_immutable_triggers("pedigree_member_revisions", "pedigree_member_revision")
    _create_immutable_triggers("pedigree_relationship_revisions", "pedigree_relationship_revision")


def downgrade():
    connection = op.get_bind()
    member_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM pedigree_member_revisions")
    ).scalar_one()
    relationship_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM pedigree_relationship_revisions")
    ).scalar_one()
    if member_count or relationship_count:
        raise RuntimeError(
            "Refusing to downgrade: pedigree correction history is immutable clinical provenance."
        )

    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_pedigree_member_no_update_delete ON pedigree_members")
        op.execute("DROP TRIGGER IF EXISTS trg_pedigree_relationship_no_update_delete ON pedigree_relationships")
        op.execute("DROP TRIGGER IF EXISTS trg_pedigree_member_revision_no_update_delete ON pedigree_member_revisions")
        op.execute("DROP TRIGGER IF EXISTS trg_pedigree_relationship_revision_no_update_delete ON pedigree_relationship_revisions")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_pedigree_revision_mutation()")
    elif connection.dialect.name == "sqlite":
        for trigger in (
            "trg_pedigree_member_no_update",
            "trg_pedigree_member_no_delete",
            "trg_pedigree_relationship_no_update",
            "trg_pedigree_relationship_no_delete",
            "trg_pedigree_member_revision_no_update",
            "trg_pedigree_member_revision_no_delete",
            "trg_pedigree_relationship_revision_no_update",
            "trg_pedigree_relationship_revision_no_delete",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    op.drop_index("ix_pedigree_relationship_revisions_relationship_version", table_name="pedigree_relationship_revisions")
    op.drop_table("pedigree_relationship_revisions")
    op.drop_index("ix_pedigree_member_revisions_member_version", table_name="pedigree_member_revisions")
    op.drop_table("pedigree_member_revisions")
