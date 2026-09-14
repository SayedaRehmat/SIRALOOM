"""add ClinGen validation state metadata"""
from alembic import op
import sqlalchemy as sa
revision = "0006_clingen_validation_state"
down_revision = "0005_clingen_specifications"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("clingen_specifications", sa.Column("validation_status", sa.Text(), nullable=False, server_default="UNVALIDATED"))
    op.add_column("clingen_specifications", sa.Column("validated_by", sa.Text(), nullable=True))
    op.add_column("clingen_specifications", sa.Column("validation_reason", sa.Text(), nullable=True))
    op.add_column("clingen_specifications", sa.Column("validation_reference", sa.Text(), nullable=True))
    op.add_column("clingen_specifications", sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column("clingen_specifications", "validated_at")
    op.drop_column("clingen_specifications", "validation_reference")
    op.drop_column("clingen_specifications", "validation_reason")
    op.drop_column("clingen_specifications", "validated_by")
    op.drop_column("clingen_specifications", "validation_status")
