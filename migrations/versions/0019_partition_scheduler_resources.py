"""Add resource-aware durable leases to genomic partitions."""
from alembic import op
import sqlalchemy as sa

revision = "0019_partition_scheduler_resources"
down_revision = "0018_analysis_partitions"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("analysis_partitions", recreate="auto") as batch:
        batch.add_column(sa.Column("resource_class", sa.Text(), nullable=False, server_default="STANDARD"))
        batch.add_column(sa.Column("cpu_request", sa.Float(), nullable=False, server_default="1.0"))
        batch.add_column(sa.Column("memory_mb", sa.Integer(), nullable=False, server_default="1024"))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("lease_owner", sa.Text(), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("error_code", sa.Text(), nullable=True))
        batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_analysis_partitions_lease", "analysis_partitions", ["status", "lease_expires_at"])


def downgrade():
    op.drop_index("ix_analysis_partitions_lease", table_name="analysis_partitions")
    with op.batch_alter_table("analysis_partitions", recreate="auto") as batch:
        for name in ("completed_at", "started_at", "error_message", "error_code", "lease_expires_at", "lease_owner", "attempt", "memory_mb", "cpu_request", "resource_class"):
            batch.drop_column(name)
