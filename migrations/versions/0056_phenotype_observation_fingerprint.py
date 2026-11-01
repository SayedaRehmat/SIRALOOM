"""Use observation-level identity for longitudinal phenotype records.

Revision ID: 0056_phenotype_observation_fingerprint
Revises: 0055_clinical_phenotype_intake
"""
import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0056_phenotype_observation_fingerprint"
down_revision = "0055_clinical_phenotype_intake"
branch_labels = None
depends_on = None


def _fingerprint(row):
    identity = {
        "hpo_id": row["hpo_id"],
        "phenotype_status": row["phenotype_status"],
        "subject_member_id": str(row["subject_member_id"]) if row["subject_member_id"] else None,
        "observed_at": row["observed_at"].isoformat() if row["observed_at"] else None,
        "label": row["label"],
        "onset": row["onset"],
        "severity": row["severity"],
        "clinical_attributes": row["clinical_attributes"] or {},
        "source": row["source"],
        "evidence": row["evidence"] or {},
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upgrade():
    op.add_column(
        "phenotype_observations",
        sa.Column("record_fingerprint", sa.String(length=64), nullable=True),
    )
    connection = op.get_bind()
    table = sa.table(
        "phenotype_observations",
        sa.column("id", sa.Uuid()),
        sa.column("hpo_id", sa.Text()),
        sa.column("phenotype_status", sa.Text()),
        sa.column("subject_member_id", sa.Uuid()),
        sa.column("observed_at", sa.DateTime(timezone=True)),
        sa.column("label", sa.Text()),
        sa.column("onset", sa.Text()),
        sa.column("severity", sa.Text()),
        sa.column("clinical_attributes", sa.JSON()),
        sa.column("source", sa.Text()),
        sa.column("evidence", sa.JSON()),
        sa.column("record_fingerprint", sa.String(64)),
    )
    rows = connection.execute(sa.select(table)).mappings().all()
    for row in rows:
        connection.execute(
            table.update().where(table.c.id == row["id"]).values(
                record_fingerprint=_fingerprint(row)
            )
        )

    for name in (
        "uq_phenotype_case_proband_term_status",
        "uq_phenotype_case_member_term_status",
        "uq_phenotype_analysis_proband_term_status",
        "uq_phenotype_analysis_member_term_status",
    ):
        op.drop_index(name, table_name="phenotype_observations")

    op.create_index(
        "uq_phenotype_case_record_fingerprint",
        "phenotype_observations",
        ["case_id", "record_fingerprint"],
        unique=True,
        sqlite_where=sa.text("analysis_id IS NULL AND record_fingerprint IS NOT NULL"),
        postgresql_where=sa.text("analysis_id IS NULL AND record_fingerprint IS NOT NULL"),
    )
    op.create_index(
        "uq_phenotype_analysis_record_fingerprint",
        "phenotype_observations",
        ["case_id", "analysis_id", "record_fingerprint"],
        unique=True,
        sqlite_where=sa.text("analysis_id IS NOT NULL AND record_fingerprint IS NOT NULL"),
        postgresql_where=sa.text("analysis_id IS NOT NULL AND record_fingerprint IS NOT NULL"),
    )


def downgrade():
    connection = op.get_bind()
    duplicates = connection.execute(sa.text(
        "SELECT COUNT(*) FROM ("
        "SELECT case_id, analysis_id, hpo_id, phenotype_status "
        "FROM phenotype_observations GROUP BY case_id, analysis_id, hpo_id, phenotype_status "
        "HAVING COUNT(*) > 1) AS incompatible"
    )).scalar_one()
    if duplicates:
        raise RuntimeError(
            "Cannot downgrade longitudinal phenotype observations: multiple records "
            "for the same term/status cannot be represented by the prior schema."
        )
    op.drop_index("uq_phenotype_case_record_fingerprint", table_name="phenotype_observations")
    op.drop_index("uq_phenotype_analysis_record_fingerprint", table_name="phenotype_observations")
    op.create_index(
        "uq_phenotype_case_proband_term_status", "phenotype_observations",
        ["case_id", "hpo_id", "phenotype_status"], unique=True,
        sqlite_where=sa.text("analysis_id IS NULL AND subject_member_id IS NULL"),
        postgresql_where=sa.text("analysis_id IS NULL AND subject_member_id IS NULL"),
    )
    op.create_index(
        "uq_phenotype_case_member_term_status", "phenotype_observations",
        ["case_id", "subject_member_id", "hpo_id", "phenotype_status"], unique=True,
        sqlite_where=sa.text("analysis_id IS NULL AND subject_member_id IS NOT NULL"),
        postgresql_where=sa.text("analysis_id IS NULL AND subject_member_id IS NOT NULL"),
    )
    op.create_index(
        "uq_phenotype_analysis_proband_term_status", "phenotype_observations",
        ["case_id", "analysis_id", "hpo_id", "phenotype_status"], unique=True,
        sqlite_where=sa.text("analysis_id IS NOT NULL AND subject_member_id IS NULL"),
        postgresql_where=sa.text("analysis_id IS NOT NULL AND subject_member_id IS NULL"),
    )
    op.create_index(
        "uq_phenotype_analysis_member_term_status", "phenotype_observations",
        ["case_id", "analysis_id", "subject_member_id", "hpo_id", "phenotype_status"], unique=True,
        sqlite_where=sa.text("analysis_id IS NOT NULL AND subject_member_id IS NOT NULL"),
        postgresql_where=sa.text("analysis_id IS NOT NULL AND subject_member_id IS NOT NULL"),
    )
    op.drop_column("phenotype_observations", "record_fingerprint")
