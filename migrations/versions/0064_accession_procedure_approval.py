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


def _add_approval_constraints():
    op.create_check_constraint(
        "ck_accession_procedure_evidence_reference",
        "accession_procedures",
        "procedure_evidence_reference IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_accession_procedure_approved_by",
        "accession_procedures",
        "(status != 'APPROVED') OR (approved_by IS NOT NULL AND created_by IS NOT NULL AND approved_by != created_by AND approval_evidence_reference IS NOT NULL)",
    )


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # PostgreSQL uses direct ALTER TABLE operations so dependent foreign
        # keys (notably accession_decisions.exception_procedure_id) remain intact.
        op.drop_constraint(
            "ck_accession_procedure_status", "accession_procedures", type_="check"
        )
        op.alter_column(
            "accession_procedures", "approved_by",
            existing_type=sa.Uuid(), nullable=True,
        )
        op.add_column(
            "accession_procedures", sa.Column("created_by", sa.Uuid(), nullable=True)
        )
        op.create_foreign_key(
            "fk_accession_procedures_created_by_users",
            "accession_procedures", "users", ["created_by"], ["id"],
        )
        op.alter_column(
            "accession_procedures", "approval_evidence_reference",
            existing_type=sa.Text(), nullable=True,
        )
        op.add_column(
            "accession_procedures",
            sa.Column("procedure_evidence_reference", sa.Text(), nullable=True),
        )
        op.create_check_constraint(
            "ck_accession_procedure_status",
            "accession_procedures",
            "status IN ('PENDING_APPROVAL','APPROVED','WITHDRAWN')",
        )
    else:
        # SQLite requires batch table recreation for nullability/column changes.
        with op.batch_alter_table("accession_procedures") as batch:
            batch.drop_constraint("ck_accession_procedure_status", type_="check")
            batch.alter_column("approved_by", existing_type=sa.Uuid(), nullable=True)
            batch.add_column(sa.Column("created_by", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                "fk_accession_procedures_created_by_users", "users", ["created_by"], ["id"]
            )
            batch.alter_column("approval_evidence_reference", existing_type=sa.Text(), nullable=True)
            batch.add_column(sa.Column("procedure_evidence_reference", sa.Text(), nullable=True))
            batch.create_check_constraint(
                "ck_accession_procedure_status",
                "status IN ('PENDING_APPROVAL','APPROVED','WITHDRAWN')",
            )

    # The old field contained the controlled procedure reference, not an
    # independent approval record. Preserve it under its correct meaning.
    op.execute(sa.text(
        "UPDATE accession_procedures "
        "SET procedure_evidence_reference = approval_evidence_reference, "
        "approval_evidence_reference = NULL"
    ))

    # A procedure previously marked APPROVED under the single-person model
    # is not grandfathered into the new separation-of-duties policy.
    op.execute(sa.text(
        "UPDATE accession_procedures SET created_by = approved_by, "
        "approved_by = NULL, status = 'PENDING_APPROVAL' "
        "WHERE status = 'APPROVED'"
    ))

    if connection.dialect.name == "postgresql":
        _add_approval_constraints()
    else:
        with op.batch_alter_table("accession_procedures") as batch:
            batch.create_check_constraint(
                "ck_accession_procedure_evidence_reference",
                "procedure_evidence_reference IS NOT NULL",
            )
            batch.create_check_constraint(
                "ck_accession_procedure_approved_by",
                "(status != 'APPROVED') OR (approved_by IS NOT NULL AND created_by IS NOT NULL AND approved_by != created_by AND approval_evidence_reference IS NOT NULL)",
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
            "Refusing to downgrade while pending or independently approved procedure history exists."
        )

    op.execute(sa.text(
        "UPDATE accession_procedures SET approval_evidence_reference = procedure_evidence_reference"
    ))
    if connection.dialect.name == "postgresql":
        op.drop_constraint(
            "ck_accession_procedure_approved_by", "accession_procedures", type_="check"
        )
        op.drop_constraint(
            "ck_accession_procedure_evidence_reference", "accession_procedures", type_="check"
        )
        op.drop_constraint(
            "fk_accession_procedures_created_by_users", "accession_procedures", type_="foreignkey"
        )
        op.drop_constraint(
            "ck_accession_procedure_status", "accession_procedures", type_="check"
        )
        op.drop_column("accession_procedures", "created_by")
        op.drop_column("accession_procedures", "procedure_evidence_reference")
        op.alter_column(
            "approved_by", "accession_procedures",
            existing_type=sa.Uuid(), nullable=False,
        )
        op.alter_column(
            "approval_evidence_reference", "accession_procedures",
            existing_type=sa.Text(), nullable=False,
        )
        op.create_check_constraint(
            "ck_accession_procedure_status",
            "accession_procedures",
            "status IN ('APPROVED','WITHDRAWN')",
        )
    else:
        with op.batch_alter_table("accession_procedures") as batch:
            batch.drop_constraint("ck_accession_procedure_approved_by", type_="check")
            batch.drop_constraint("ck_accession_procedure_evidence_reference", type_="check")
            batch.drop_constraint("fk_accession_procedures_created_by_users", type_="foreignkey")
            batch.drop_constraint("ck_accession_procedure_status", type_="check")
            batch.drop_column("created_by")
            batch.drop_column("procedure_evidence_reference")
            batch.alter_column("approved_by", existing_type=sa.Uuid(), nullable=False)
            batch.alter_column("approval_evidence_reference", existing_type=sa.Text(), nullable=False)
            batch.create_check_constraint(
                "ck_accession_procedure_status",
                "status IN ('APPROVED','WITHDRAWN')",
            )
