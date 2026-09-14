"""Add canonical variant identity fields."""
from alembic import op
import sqlalchemy as sa

revision = "0002_variant_normalization"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("variants") as batch:
        batch.add_column(sa.Column("canonical_key", sa.Text(), nullable=True))
        batch.create_unique_constraint("uq_variants_canonical_key", ["canonical_key"])


def downgrade() -> None:
    with op.batch_alter_table("variants") as batch:
        batch.drop_constraint("uq_variants_canonical_key", type_="unique")
        batch.drop_column("canonical_key")
