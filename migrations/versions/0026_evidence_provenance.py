"""Persist evidence and ClinGen observation provenance.

Revision ID: 0026_evidence_provenance
Revises: 0025_population_observation_provenance
"""

from alembic import op
import sqlalchemy as sa

revision = "0026_evidence_provenance"
down_revision = "0025_population_observation_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evidence", sa.Column("resource_id", sa.Uuid(), nullable=True))
    op.add_column("evidence", sa.Column("request_fingerprint", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("response_sha256", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("request_metadata", sa.JSON(), nullable=True))
    op.add_column("evidence", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_evidence_resource_id", "evidence", "resources", ["resource_id"], ["id"])
    op.execute(sa.text("UPDATE evidence SET request_metadata = '{}' WHERE request_metadata IS NULL"))
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.alter_column("request_metadata", existing_type=sa.JSON(), nullable=False)

    op.add_column("clingen_specifications", sa.Column("request_fingerprint", sa.Text(), nullable=True))
    op.add_column("clingen_specifications", sa.Column("response_sha256", sa.Text(), nullable=True))
    op.add_column("clingen_specifications", sa.Column("request_metadata", sa.JSON(), nullable=True))
    op.execute(sa.text("UPDATE clingen_specifications SET request_metadata = '{}' WHERE request_metadata IS NULL"))
    with op.batch_alter_table("clingen_specifications") as batch_op:
        batch_op.alter_column("request_metadata", existing_type=sa.JSON(), nullable=False)


def downgrade():
    op.drop_column("clingen_specifications", "request_metadata")
    op.drop_column("clingen_specifications", "response_sha256")
    op.drop_column("clingen_specifications", "request_fingerprint")
    op.drop_constraint("fk_evidence_resource_id", "evidence", type_="foreignkey")
    op.drop_column("evidence", "observed_at")
    op.drop_column("evidence", "request_metadata")
    op.drop_column("evidence", "response_sha256")
    op.drop_column("evidence", "request_fingerprint")
    op.drop_column("evidence", "resource_id")
