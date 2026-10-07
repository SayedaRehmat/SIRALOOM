"""Enforce exact governed annotation observation identity.

Revision ID: 0041_annotation_observation_identity
Revises: 0040_partition_lease_fencing
"""

from alembic import op

revision = "0041_annotation_observation_identity"
down_revision = "0040_partition_lease_fencing"
branch_labels = None
depends_on = None


def upgrade():
    # New workflow observations always carry a governed resource_id. Keep
    # legacy resource_id=NULL observations readable, but do not allow any new
    # governed release to create duplicate observations for the same scientific
    # identity.
    op.create_index(
        "uq_annotations_observation_identity",
        "annotations",
        [
            "analysis_id",
            "variant_id",
            "provider_name",
            "provider_version",
            "resource_id",
            "resource_version",
        ],
        unique=True,
        postgresql_where=__import__("sqlalchemy").text("resource_id IS NOT NULL"),
        sqlite_where=__import__("sqlalchemy").text("resource_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index(
        "uq_annotations_observation_identity",
        table_name="annotations",
    )
