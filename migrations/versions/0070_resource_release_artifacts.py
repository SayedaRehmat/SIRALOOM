"""Persist immutable source-release artifacts and bind scientific evidence to them.

Revision ID: 0070_resource_release_artifacts
Revises: 0069_provider_retention_approvals
"""
from alembic import op
import sqlalchemy as sa

revision = "0070_resource_release_artifacts"
down_revision = "0069_provider_retention_approvals"
branch_labels = None
depends_on = None

_TABLES = ("annotations", "population_observations", "evidence")


def upgrade():
    op.create_table(
        "resource_release_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("resource_staging_id", sa.Uuid(), sa.ForeignKey("resource_stagings.id"), nullable=False, unique=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id")),
        sa.Column("resource_version", sa.Text(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("storage_backend", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("integrity_status", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(sha256) = 64", name="ck_resource_release_sha256_length"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_resource_release_size_nonnegative"),
        sa.UniqueConstraint("resource_id", "resource_version", "sha256", name="uq_resource_release_identity"),
    )
    op.create_index(
        "ix_resource_release_resource_version",
        "resource_release_artifacts", ["resource_id", "resource_version"],
    )
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(
                "source_release_artifact_id", sa.Uuid(),
                sa.ForeignKey("resource_release_artifacts.id", name=f"fk_{table}_source_release_artifact"),
                nullable=True,
            ))
            batch.add_column(sa.Column("source_release_sha256", sa.Text(), nullable=True))
            batch.add_column(sa.Column("source_release_size_bytes", sa.BigInteger(), nullable=True))
            batch.add_column(sa.Column(
                "source_release_status", sa.Text(), nullable=False,
                server_default="NOT_AVAILABLE",
            ))
            batch.create_check_constraint(
                f"ck_{table}_source_release_status",
                "source_release_status IN ('VERIFIED', 'CAPTURED', 'NOT_AVAILABLE')",
            )
            batch.create_check_constraint(
                f"ck_{table}_source_release_digest",
                "source_release_sha256 IS NULL OR length(source_release_sha256) = 64",
            )
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_resource_release_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'resource release artifacts are immutable';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_resource_release_artifact_immutable
            BEFORE UPDATE OR DELETE ON resource_release_artifacts
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_resource_release_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_resource_release_artifact_immutable_update
            BEFORE UPDATE ON resource_release_artifacts
            BEGIN SELECT RAISE(ABORT, 'resource release artifacts are immutable'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_resource_release_artifact_immutable_delete
            BEFORE DELETE ON resource_release_artifacts
            BEGIN SELECT RAISE(ABORT, 'resource release artifacts are immutable'); END
        """)


def downgrade():
    connection = op.get_bind()
    count = connection.execute(sa.text(
        "SELECT COUNT(*) FROM resource_release_artifacts"
    )).scalar_one()
    if count:
        raise RuntimeError("Refusing to downgrade: immutable source-release artifacts exist.")
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_resource_release_artifact_immutable ON resource_release_artifacts")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_resource_release_mutation()")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_resource_release_artifact_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS trg_resource_release_artifact_immutable_delete")
    for table in reversed(_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_source_release_digest", type_="check")
            batch.drop_constraint(f"ck_{table}_source_release_status", type_="check")
            batch.drop_column("source_release_status")
            batch.drop_column("source_release_size_bytes")
            batch.drop_column("source_release_sha256")
            batch.drop_column("source_release_artifact_id")
    op.drop_index("ix_resource_release_resource_version", table_name="resource_release_artifacts")
    op.drop_table("resource_release_artifacts")
