"""Persist the queue task identity for durable analysis execution."""
from alembic import op
import sqlalchemy as sa

revision = "0012_durable_analysis_queue"
down_revision = "0011_artifact_ingestion"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("analyses", sa.Column("queue_task_id", sa.Text(), nullable=True))
    op.create_index("ix_analyses_queue_task_id", "analyses", ["queue_task_id"])

def downgrade():
    op.drop_index("ix_analyses_queue_task_id", table_name="analyses")
    op.drop_column("analyses", "queue_task_id")
