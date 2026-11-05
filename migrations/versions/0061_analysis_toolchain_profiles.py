"""Persist the immutable BCFtools/HTSlib execution profile per analysis.

Revision ID: 0061_analysis_toolchain_profiles
Revises: 0060_caller_ploidy_policy_revisions
"""
from alembic import op
import sqlalchemy as sa

revision = "0061_analysis_toolchain_profiles"
down_revision = "0060_caller_ploidy_policy_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("analyses", sa.Column("toolchain_profile_id", sa.Text(), nullable=False, server_default="bcftools-1.25-htslib-1.25-linux-64"))
    op.add_column("analyses", sa.Column("toolchain_bcftools_version", sa.Text(), nullable=False, server_default="1.25"))
    op.add_column("analyses", sa.Column("toolchain_htslib_version", sa.Text(), nullable=False, server_default="1.25"))
    op.add_column("analyses", sa.Column("toolchain_queue", sa.Text(), nullable=False, server_default="bioinformatics.bcftools.1_25"))
    op.add_column("analyses", sa.Column("toolchain_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.create_index("ix_analyses_toolchain_queue_status", "analyses", ["toolchain_queue", "status"], unique=False)
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_analysis_toolchain_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                IF OLD.toolchain_profile_id IS DISTINCT FROM NEW.toolchain_profile_id
                   OR OLD.toolchain_bcftools_version IS DISTINCT FROM NEW.toolchain_bcftools_version
                   OR OLD.toolchain_htslib_version IS DISTINCT FROM NEW.toolchain_htslib_version
                   OR OLD.toolchain_queue IS DISTINCT FROM NEW.toolchain_queue
                   OR OLD.toolchain_snapshot IS DISTINCT FROM NEW.toolchain_snapshot THEN
                    RAISE EXCEPTION 'analysis toolchain provenance is immutable';
                END IF;
                RETURN NEW;
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_analysis_toolchain_immutable
            BEFORE UPDATE ON analyses
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_analysis_toolchain_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_analysis_toolchain_immutable
            BEFORE UPDATE ON analyses
            WHEN OLD.toolchain_profile_id != NEW.toolchain_profile_id
              OR OLD.toolchain_bcftools_version != NEW.toolchain_bcftools_version
              OR OLD.toolchain_htslib_version != NEW.toolchain_htslib_version
              OR OLD.toolchain_queue != NEW.toolchain_queue
              OR OLD.toolchain_snapshot != NEW.toolchain_snapshot
            BEGIN SELECT RAISE(ABORT, 'analysis toolchain provenance is immutable'); END
        """)


def downgrade():
    connection = op.get_bind()
    count = connection.execute(sa.text(
        "SELECT COUNT(*) FROM analyses WHERE toolchain_profile_id != 'bcftools-1.25-htslib-1.25-linux-64'"
    )).scalar_one()
    if count:
        raise RuntimeError("Refusing to downgrade: non-default analysis toolchain assignments would lose provenance.")
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_analysis_toolchain_immutable ON analyses")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_analysis_toolchain_mutation()")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_analysis_toolchain_immutable")
    op.drop_index("ix_analyses_toolchain_queue_status", table_name="analyses")
    for column in ("toolchain_snapshot", "toolchain_queue", "toolchain_htslib_version", "toolchain_bcftools_version", "toolchain_profile_id"):
        op.drop_column("analyses", column)
