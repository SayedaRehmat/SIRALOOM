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
        batch.create_foreign_key("fk_accession_procedures_created_by_users", "users", ["created_by"], ["id"])        batch.alter_column(
            "approval_evidence_reference",
            new_column_name="procedure_evidence_reference",
            existing_type=sa.Text(),
            existing_nullable=False,
        )
        batch.add_column(sa.Column("approval_evidence_reference", sa.Text(), nullable=True))        # A procedure previously marked APPROVED under the single-person model
        # is not grandfathered into the new separation-of-duties policy.
        # Preserve its former approver as the submitter and require fresh
        # independent approval before it can authorize an exception.
        op.execute(sa.text("""
            UPDATE accession_procedures
            SET created_by = approved_by, approved_by = NULL, status = 'PENDING_APPROVAL'
            WHERE status = 'APPROVED'
        """))
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
        sa.text(
            "SELECT COUNT(*) FROM accession_procedures "
            "WHERE status = 'PENDING_APPROVAL' OR approved_by IS NULL "
            "OR approval_evidence_reference IS NOT NULL"
        )
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
        batch.drop_column("approval_evidence_reference")
        batch.alter_column(
            "procedure_evidence_reference",
            new_column_name="approval_evidence_reference",
            existing_type=sa.Text(),
            existing_nullable=False,
        )
        batch.alter_column("approved_by", existing_type=sa.Uuid(), nullable=False)
        batch.create_check_constraint(
            "ck_accession_procedure_status",
            "status IN ('APPROVED','WITHDRAWN')",
        )
