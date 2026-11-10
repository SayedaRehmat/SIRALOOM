"""Create versioned clinical requests and separate laboratory authorities.

Revision ID: 0063_clinical_requests_accession
Revises: 0062_artifact_validation_dispatches
"""
from alembic import op
import sqlalchemy as sa

revision = "0063_clinical_requests_accession"
down_revision = "0062_artifact_validation_dispatches"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinical_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", name="fk_accession_procedures_organization_id_organizations"), nullable=False),
        sa.Column("request_identifier", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="DRAFT"),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "request_identifier", name="uq_clinical_request_case_identifier"),
        sa.CheckConstraint("status IN ('DRAFT','SUBMITTED','UNDER_REVIEW','NEEDS_INFORMATION','ACCEPTED','REJECTED','CLOSED','REASSESSMENT_REQUIRED')", name="ck_clinical_request_status"),
    )
    op.create_index("ix_clinical_requests_org_case", "clinical_requests", ["organization_id", "case_id"])
    op.create_table(
        "clinical_request_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("clinical_requests.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("request_id", "version", name="uq_clinical_request_revision_version"),
        sa.UniqueConstraint("request_id", "fingerprint", name="uq_clinical_request_revision_fingerprint"),
        sa.CheckConstraint("version > 0", name="ck_clinical_request_revision_positive"),
    )
    op.create_table(
        "referrer_verifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("clinical_requests.id"), nullable=False),
        sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("clinical_request_revisions.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("outcome_note", sa.Text(), nullable=False),
        sa.Column("verified_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('VERIFIED','UNABLE_TO_VERIFY')", name="ck_referrer_verification_status"),
    )
    op.create_table(
        "accession_procedures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("procedure_identifier", sa.Text(), nullable=False),
        sa.Column("procedure_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id", name="fk_accession_procedures_approved_by_users"), nullable=False),
        sa.Column("approval_evidence_reference", sa.Text(), nullable=False),
        sa.Column("allows_unverified_referrer_exception", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "procedure_identifier", "procedure_version", name="uq_accession_procedure_version"),
        sa.CheckConstraint("status IN ('APPROVED','WITHDRAWN')", name="ck_accession_procedure_status"),
    )
    op.create_table(
        "accession_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("clinical_requests.id"), nullable=False),
        sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("clinical_request_revisions.id"), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("verification_id", sa.Uuid(), sa.ForeignKey("referrer_verifications.id")),
        sa.Column("exception_procedure_id", sa.Uuid(), sa.ForeignKey("accession_procedures.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('ACCEPT','REJECT','NEEDS_INFORMATION')", name="ck_accession_decision"),
        sa.CheckConstraint("(decision != 'ACCEPT') OR (verification_id IS NOT NULL OR exception_procedure_id IS NOT NULL)", name="ck_accession_acceptance_basis"),
    )
    op.create_table(
        "organization_capability_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("grant_reason", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("revocation_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("capability IN ('REFERRER_VERIFY','ACCESSION_DECIDE','CLINICAL_ATTEST','CAPABILITY_ADMIN','HISTORY_RECONCILE')", name="ck_org_capability"),
    )
    op.create_index("ix_org_capability_active", "organization_capability_assignments", ["organization_id", "user_id", "capability", "revoked_at"])
    op.create_table(
        "clinical_attestations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("clinical_requests.id"), nullable=False),
        sa.Column("request_revision_id", sa.Uuid(), sa.ForeignKey("clinical_request_revisions.id"), nullable=False),
        sa.Column("clinical_intake_revision_id", sa.Uuid(), sa.ForeignKey("clinical_intake_revisions.id")),
        sa.Column("attestation_type", sa.Text(), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Preserve old cases without manufacturing historical referral/acceptance evidence.
    with op.batch_alter_table("cases") as batch:
        batch.add_column(sa.Column("accession_reconciliation_status", sa.Text(), nullable=False, server_default="LEGACY_UNRECONCILED"))
        batch.create_check_constraint("ck_case_accession_reconciliation_status", "accession_reconciliation_status IN ('LEGACY_UNRECONCILED','NEW_WORKFLOW','RECONCILED')")


def downgrade():
    connection = op.get_bind()
    for table in ("clinical_attestations", "accession_decisions", "referrer_verifications", "clinical_request_revisions", "clinical_requests", "organization_capability_assignments", "accession_procedures"):
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(f"Refusing to downgrade: {table} contains clinical history.")
    with op.batch_alter_table("cases") as batch:
        batch.drop_constraint("ck_case_accession_reconciliation_status", type_="check")
        batch.drop_column("accession_reconciliation_status")
    op.drop_table("clinical_attestations")
    op.drop_index("ix_org_capability_active", table_name="organization_capability_assignments")
    op.drop_table("organization_capability_assignments")
    op.drop_table("accession_decisions")
    op.drop_table("accession_procedures")
    op.drop_table("referrer_verifications")
    op.drop_table("clinical_request_revisions")
    op.drop_index("ix_clinical_requests_org_case", table_name="clinical_requests")
    op.drop_table("clinical_requests")
