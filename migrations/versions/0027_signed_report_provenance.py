"""Add immutable signed report provenance fields."""

from alembic import op
import sqlalchemy as sa

revision = "0027_signed_report_provenance"
down_revision = "0026_evidence_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reports", sa.Column("signed_artifact_id", sa.Uuid(), nullable=True))
    op.add_column("reports", sa.Column("signed_sha256", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("signout_reason", sa.Text(), nullable=True))
    with op.batch_alter_table("reports") as batch_op:
        batch_op.create_foreign_key(
            "fk_reports_signed_artifact_id",
            "artifacts",
            ["signed_artifact_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("reports") as batch_op:
        batch_op.drop_constraint("fk_reports_signed_artifact_id", type_="foreignkey")
    op.drop_column("reports", "signout_reason")
    op.drop_column("reports", "signed_sha256")
    op.drop_column("reports", "signed_artifact_id")
