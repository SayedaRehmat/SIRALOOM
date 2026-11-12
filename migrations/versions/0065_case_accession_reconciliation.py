"""Persist explicit historical accession reconciliation without fabricating requests.

Revision ID: 0065_case_accession_reconciliation
Revises: 0064_accession_procedure_approval
"""
from alembic import op
import sqlalchemy as sa

revision = "0065_case_accession_reconciliation"
down_revision = "0064_accession_procedure_approval"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_accession_reconciliations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("prior_status", sa.String(40), nullable=False),
        sa.Column("new_status", sa.String(40), nullable=False),
        sa.Column("source_evidence_reference", sa.Text(), nullable=False),
        sa.Column("reviewed_scope", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", name="uq_case_accession_reconciliation_case"),
        sa.CheckConstraint("prior_status = 'LEGACY_UNRECONCILED'", name="ck_case_reconciliation_prior_legacy"),
        sa.CheckConstraint("new_status = 'RECONCILED'", name="ck_case_reconciliation_new_reconciled"),
    )
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_clinical_request_history_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'clinical request revisions, verifications and decisions are immutable';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_clinical_request_revisions_immutable
            BEFORE UPDATE OR DELETE ON clinical_request_revisions
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_clinical_request_history_mutation()
        """)
        op.execute("""
            CREATE TRIGGER trg_referrer_verifications_immutable
            BEFORE UPDATE OR DELETE ON referrer_verifications
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_clinical_request_history_mutation()
        """)
        op.execute("""
            CREATE TRIGGER trg_accession_decisions_immutable
            BEFORE UPDATE OR DELETE ON accession_decisions
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_clinical_request_history_mutation()
        """)
        op.execute("""
            CREATE FUNCTION siraloom_reject_case_reconciliation_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                RAISE EXCEPTION 'case accession reconciliation history is immutable';
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_case_accession_reconciliation_immutable
            BEFORE UPDATE OR DELETE ON case_accession_reconciliations
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_case_reconciliation_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        for table, prefix in (
            ("clinical_request_revisions", "clinical_request_revisions"),
            ("referrer_verifications", "referrer_verifications"),
            ("accession_decisions", "accession_decisions"),
            ("case_accession_reconciliations", "case_accession_reconciliation"),
        ):
            op.execute(
                "CREATE TRIGGER trg_" + prefix + "_no_update BEFORE UPDATE ON " + table +
                " BEGIN SELECT RAISE(ABORT, 'clinical request history is immutable'); END"
            )
            op.execute(
                "CREATE TRIGGER trg_" + prefix + "_no_delete BEFORE DELETE ON " + table +
                " BEGIN SELECT RAISE(ABORT, 'clinical request history is immutable'); END"
            )


def downgrade():
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM case_accession_reconciliations")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Refusing to downgrade: historical accession reconciliation evidence would be lost."
        )
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_clinical_request_revisions_immutable ON clinical_request_revisions")
        op.execute("DROP TRIGGER IF EXISTS trg_referrer_verifications_immutable ON referrer_verifications")
        op.execute("DROP TRIGGER IF EXISTS trg_accession_decisions_immutable ON accession_decisions")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_clinical_request_history_mutation()")
        op.execute("DROP TRIGGER IF EXISTS trg_case_accession_reconciliation_immutable ON case_accession_reconciliations")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_case_reconciliation_mutation()")
    elif connection.dialect.name == "sqlite":
        for prefix in (
            "clinical_request_revisions",
            "referrer_verifications",
            "accession_decisions",
            "case_accession_reconciliation",
        ):
            op.execute("DROP TRIGGER IF EXISTS trg_" + prefix + "_no_update")
            op.execute("DROP TRIGGER IF EXISTS trg_" + prefix + "_no_delete")
    op.drop_table("case_accession_reconciliations")
