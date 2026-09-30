"""Persist population observation provenance.

Revision ID: 0025_population_observation_provenance
Revises: 0024_annotation_observation_provenance
"""

from alembic import op
import sqlalchemy as sa

revision = "0025_population_observation_provenance"
down_revision = "0024_annotation_observation_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("population_observations", sa.Column("source_record_id", sa.Text(), nullable=True))
    op.add_column("population_observations", sa.Column("request_fingerprint", sa.Text(), nullable=True))
    op.add_column("population_observations", sa.Column("response_sha256", sa.Text(), nullable=True))
    op.add_column("population_observations", sa.Column("request_metadata", sa.JSON(), nullable=True))
    op.add_column("population_observations", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text(
        "UPDATE population_observations SET request_metadata = '{}' "
        "WHERE request_metadata IS NULL"
    ))
    with op.batch_alter_table("population_observations") as batch_op:
        batch_op.alter_column("request_metadata", existing_type=sa.JSON(), nullable=False)


def downgrade():
    op.drop_column("population_observations", "observed_at")
    op.drop_column("population_observations", "request_metadata")
    op.drop_column("population_observations", "response_sha256")
    op.drop_column("population_observations", "request_fingerprint")
    op.drop_column("population_observations", "source_record_id")
