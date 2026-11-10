"""Enforce immutable organization-scoped assay versions.

Revision ID: 0066_assay_version_governance
Revises: 0065_case_accession_reconciliation
"""
from alembic import op
import sqlalchemy as sa

revision = "0066_assay_version_governance"
down_revision = "0065_case_accession_reconciliation"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    duplicates = connection.execute(sa.text(
        "SELECT COUNT(*) FROM ("
        "SELECT organization_id, name, version FROM assays "
        "GROUP BY organization_id, name, version HAVING COUNT(*) > 1"
        ") AS duplicate_assay_versions"
    )).scalar_one()
    if duplicates:
        raise RuntimeError(
            "Cannot enforce assay version identity: duplicate organization/name/version rows exist."
        )
    invalid_statuses = connection.execute(sa.text(
        "SELECT COUNT(*) FROM assays WHERE status NOT IN ('ACTIVE','INACTIVE')"
    )).scalar_one()
    if invalid_statuses:
        raise RuntimeError(
            "Cannot enforce assay status lifecycle: unsupported assay statuses exist."
        )

    with op.batch_alter_table("assays") as batch:
        batch.create_unique_constraint(
            "uq_assay_org_name_version",
            ["organization_id", "name", "version"],
        )
        batch.create_check_constraint(
            "ck_assay_status",
            "status IN ('ACTIVE','INACTIVE')",
        )

    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_assay_identity_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.name IS DISTINCT FROM OLD.name
                   OR NEW.version IS DISTINCT FROM OLD.version
                   OR NEW.assay_type IS DISTINCT FROM OLD.assay_type
                   OR NEW.configuration IS DISTINCT FROM OLD.configuration
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'assay identity and configuration are immutable; create a new version';
                END IF;
                RETURN NEW;
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_assay_identity_immutable
            BEFORE UPDATE ON assays
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_assay_identity_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_assay_identity_immutable
            BEFORE UPDATE ON assays
            WHEN OLD.organization_id IS NOT NEW.organization_id
              OR OLD.name IS NOT NEW.name
              OR OLD.version IS NOT NEW.version
              OR OLD.assay_type IS NOT NEW.assay_type
              OR OLD.configuration IS NOT NEW.configuration
              OR OLD.created_at IS NOT NEW.created_at
            BEGIN
                SELECT RAISE(ABORT, 'assay identity and configuration are immutable; create a new version');
            END
        """)


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_assay_identity_immutable ON assays")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_assay_identity_mutation()")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_assay_identity_immutable")
    with op.batch_alter_table("assays") as batch:
        batch.drop_constraint("ck_assay_status", type_="check")
        batch.drop_constraint("uq_assay_org_name_version", type_="unique")
