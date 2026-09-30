"""Persist exact annotation observation provenance.

Revision ID: 0024_annotation_observation_provenance
Revises: 0023_reanalysis_change_event_fingerprint
"""

from alembic import op
import sqlalchemy as sa

revision = "0024_annotation_observation_provenance"
down_revision = "0023_reanalysis_change_event_fingerprint"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "annotations",
        sa.Column("resource_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "annotations",
        sa.Column("request_fingerprint", sa.Text(), nullable=True),
    )
    op.add_column(
        "annotations",
        sa.Column("response_sha256", sa.Text(), nullable=True),
    )
    op.add_column(
        "annotations",
        sa.Column("request_metadata", sa.JSON(), nullable=True),
    )
    op.add_column(
        "annotations",
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "annotations",
        sa.Column("retry_count", sa.Integer(), nullable=True),
    )
    op.execute(sa.text(
        "UPDATE annotations "
        "SET request_metadata = '{}' "
        "WHERE request_metadata IS NULL"
    ))
    op.execute(sa.text(
        "UPDATE annotations "
        "SET retry_count = 0 "
        "WHERE retry_count IS NULL"
    ))
    with op.batch_alter_table("annotations") as batch_op:
        batch_op.create_foreign_key(
            "fk_annotations_resource_id_resources",
            "resources",
            ["resource_id"],
            ["id"],
        )
        batch_op.alter_column(
            "request_metadata",
            existing_type=sa.JSON(),
            nullable=False,
        )
        batch_op.alter_column(
            "retry_count",
            existing_type=sa.Integer(),
            nullable=False,
        )


def downgrade():
    with op.batch_alter_table("annotations") as batch_op:
        batch_op.drop_constraint(
            "fk_annotations_resource_id_resources",
            type_="foreignkey",
        )
    op.drop_column("annotations", "retry_count")
    op.drop_column("annotations", "observed_at")
    op.drop_column("annotations", "request_metadata")
    op.drop_column("annotations", "response_sha256")
    op.drop_column("annotations", "request_fingerprint")
    op.drop_column("annotations", "resource_id")
