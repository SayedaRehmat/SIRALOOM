"""Add immutable review versioning and classification lineage metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0008_review_workflow"
down_revision = "0007_classification_metadata"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("acmg_assessments") as batch:
        batch.add_column(sa.Column("review_version", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("classifications") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("supersedes_classification_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("review_version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("reviewed_by", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_classifications_supersedes",
            "classifications",
            ["supersedes_classification_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_classifications_reviewed_by",
            "users",
            ["reviewed_by"],
            ["id"],
        )

    with op.batch_alter_table("review_actions") as batch:
        batch.add_column(sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("expected_version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("resulting_version", sa.Integer(), nullable=False, server_default="0"))
        batch.create_unique_constraint(
            "uq_review_action_analysis_variant_sequence",
            ["analysis_id", "variant_id", "sequence_number"],
        )


def downgrade():
    with op.batch_alter_table("review_actions") as batch:
        batch.drop_constraint("uq_review_action_analysis_variant_sequence", type_="unique")
        batch.drop_column("resulting_version")
        batch.drop_column("expected_version")
        batch.drop_column("sequence_number")

    with op.batch_alter_table("classifications") as batch:
        batch.drop_constraint("fk_classifications_reviewed_by", type_="foreignkey")
        batch.drop_constraint("fk_classifications_supersedes", type_="foreignkey")
        batch.drop_column("approved_at")
        batch.drop_column("reviewed_by")
        batch.drop_column("review_version")
        batch.drop_column("supersedes_classification_id")
        batch.drop_column("version")

    with op.batch_alter_table("acmg_assessments") as batch:
        batch.drop_column("review_version")
