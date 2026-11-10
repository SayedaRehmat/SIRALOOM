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
        batch.add_column(sa.Column("created_by", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_accession_procedures_created_by_users", "users", ["created_by"], ["id"])
        batch.create_check_constraint(
            "ck_accession_procedure_status",
            "status IN ('PENDING_APPROVAL','APPROVED','WITHDRAWN')",
        )
        batch.create_check_constraint(
            "ck_accession_procedure_approved_by",
            "(status != 'APPROVED') OR (approved_by IS NOT NULL)",
        )


def downgrade():
    connection = op.get_bind()
    unsafe_rows = connection.execute(
        sa.text("SELECT COUNT(*) FROM accession_procedures WHERE status = 'PENDING_APPROVAL' OR approved_by IS NULL")
    ).scalar_one()
    if unsafe_rows:
        raise RuntimeError(
            "Refusing to downgrade while pending or unapproved accession procedure history exists."
        )
    with op.batch_alter_table("accession_procedures") as batch:
        batch.drop_constraint("fk_accession_procedures_created_by_users", type_="foreignkey")
        batch.drop_constraint("ck_accession_procedure_approved_by", type_="check")
        batch.drop_constraint("ck_accession_procedure_status", type_="check")
        batch.drop_column("created_by")
        batch.alter_column("approved_by", existing_type=sa.Uuid(), nullable=False)
        batch.create_check_constraint(
            "ck_accession_procedure_status",
            "status IN ('APPROVED','WITHDRAWN')",
        )
