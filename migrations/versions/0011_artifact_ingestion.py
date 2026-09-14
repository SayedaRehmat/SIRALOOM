"""Add specimen linkage, index pairing, and validation state to artifacts.

Uses Alembic batch operations so the development/test SQLite database can replay
all migrations while PostgreSQL uses the normal ALTER TABLE path.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_artifact_ingestion"
down_revision = "0010_organization_memberships"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("artifacts", recreate="auto") as batch:
        batch.add_column(sa.Column("specimen_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("paired_artifact_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("validation_status", sa.Text(), nullable=False, server_default="PENDING"))
        batch.create_foreign_key("fk_artifacts_specimen_id", "specimens", ["specimen_id"], ["id"])
        batch.create_foreign_key("fk_artifacts_paired_artifact_id", "artifacts", ["paired_artifact_id"], ["id"])
        batch.create_index("ix_artifacts_specimen_id", ["specimen_id"])
        batch.create_index("ix_artifacts_paired_artifact_id", ["paired_artifact_id"])


def downgrade():
    with op.batch_alter_table("artifacts", recreate="auto") as batch:
        batch.drop_index("ix_artifacts_paired_artifact_id")
        batch.drop_index("ix_artifacts_specimen_id")
        batch.drop_constraint("fk_artifacts_paired_artifact_id", type_="foreignkey")
        batch.drop_constraint("fk_artifacts_specimen_id", type_="foreignkey")
        batch.drop_column("validation_status")
        batch.drop_column("paired_artifact_id")
        batch.drop_column("specimen_id")
