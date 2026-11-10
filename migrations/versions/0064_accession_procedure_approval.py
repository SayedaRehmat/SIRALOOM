"""Require independent approval before accession exception procedures become effective.

Revision ID: 0064_accession_procedure_approval
Revises: 0063_clinical_requests_accession
"""
from alembic import op
import sqlalchemy as sa

revision = "0064_accession_procedure_approval"
down_revision = "0063_clinical_requests_accession"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("accession_procedures") as batch:
        batch.drop_constraint("ck_accession_procedure_status", type_="check")
        batch.alter_column("approved_by", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True))
        batch.create_check_constraint(
            "ck_accession_procedure_status",
            "status IN ('PENDING_APPROVAL','APPROVED','WITHDRAWN')",
        )


def downgrade():
    connection = op.get_bind()
    pending = connection.execute(
        sa.text("SELECT COUNT(*) FROM accession_procedures WHERE status = 'PENDING_APPROVAL'")
    ).scalar_one()
    if pending:
        raise RuntimeError(
            "Refusing to downgrade while pending accession procedures exist."
        )
    with op.batch_alter_table("accession_procedures") as batch:
        batch.drop_constraint("ck_accession_procedure_status", type_="check")
        batch.drop_column("created_by")
        batch.alter_column("approved_by", existing_type=sa.Uuid(), nullable=False)
        batch.create_check_constraint(
            "ck_accession_procedure_status",
            "status IN ('APPROVED','WITHDRAWN')",
        )
