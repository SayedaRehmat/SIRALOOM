"""Persist ClinGen specification lineage on classification snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "0007_classification_metadata"
down_revision = "0006_clingen_validation_state"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("classifications") as batch:
        batch.add_column(
            sa.Column("specification_provider", sa.Text(), nullable=True)
        )
        batch.add_column(
            sa.Column("specification_id", sa.Text(), nullable=True)
        )
        batch.add_column(
            sa.Column("specification_version", sa.Text(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade():
    with op.batch_alter_table("classifications") as batch:
        batch.drop_column("metadata")
        batch.drop_column("specification_version")
        batch.drop_column("specification_id")
        batch.drop_column("specification_provider")
