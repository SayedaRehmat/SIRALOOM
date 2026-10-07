"""Add fencing token to analysis partition leases.

Revision ID: 0040_partition_lease_fencing
Revises: 0039_case_export_dispatch_outbox
"""

from alembic import op
import sqlalchemy as sa


revision = "0040_partition_lease_fencing"
down_revision = "0039_case_export_dispatch_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_partitions",
        sa.Column("lease_token", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_partitions", "lease_token")
