"""Add deterministic evidence fingerprints for idempotent evidence creation."""
from alembic import op
import sqlalchemy as sa

revision = "0003_evidence_fingerprint"
down_revision = "0002_variant_normalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("evidence_fingerprint", sa.Text(), nullable=True))
        batch.create_unique_constraint("uq_evidence_analysis_fingerprint", ["analysis_id", "evidence_fingerprint"])


def downgrade() -> None:
    with op.batch_alter_table("evidence") as batch:
        batch.drop_constraint("uq_evidence_analysis_fingerprint", type_="unique")
        batch.drop_column("evidence_fingerprint")
