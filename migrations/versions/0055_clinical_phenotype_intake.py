"""Extend phenotype observations for clinical intake and family subjects.

Revision ID: 0055_clinical_phenotype_intake
Revises: 0054_artifact_analysis_id_index
"""
import sqlalchemy as sa
from alembic import op

revision = "0055_clinical_phenotype_intake"
down_revision = "0054_artifact_analysis_id_index"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("phenotype_observations", sa.Column(
        "canonical_hpo_id", sa.Text(), nullable=True
    ))
    op.add_column("phenotype_observations", sa.Column(
        "subject_member_id",
        sa.Uuid(),
        sa.ForeignKey("pedigree_members.id"),
        nullable=True,
    ))
    op.add_column("phenotype_observations", sa.Column(
        "observed_at", sa.DateTime(timezone=True), nullable=True
    ))
    op.add_column("phenotype_observations", sa.Column(
        "clinical_attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
    ))
    op.add_column("phenotype_observations", sa.Column(
        "ontology_resolution", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
    ))

    op.drop_index("uq_phenotype_case_term_status", table_name="phenotype_observations")
    op.drop_index("uq_phenotype_analysis_term_status", table_name="phenotype_observations")
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
            "Cannot downgrade family-aware phenotype observations: multiple subjects "
            "for the same case/analysis/term/status cannot be represented by the prior schema."
        )
    for name in (
        "uq_phenotype_case_proband_term_status",
        "uq_phenotype_case_member_term_status",
        "uq_phenotype_analysis_proband_term_status",
        "uq_phenotype_analysis_member_term_status",
    ):
        op.drop_index(name, table_name="phenotype_observations")
    op.create_index(
        "uq_phenotype_case_term_status", "phenotype_observations",
        ["case_id", "hpo_id", "phenotype_status"], unique=True,
        sqlite_where=sa.text("analysis_id IS NULL"),
        postgresql_where=sa.text("analysis_id IS NULL"),
    )
    op.create_index(
        "uq_phenotype_analysis_term_status", "phenotype_observations",
        ["case_id", "analysis_id", "hpo_id", "phenotype_status"], unique=True,
        sqlite_where=sa.text("analysis_id IS NOT NULL"),
        postgresql_where=sa.text("analysis_id IS NOT NULL"),
    )
    op.drop_column("phenotype_observations", "ontology_resolution")
    op.drop_column("phenotype_observations", "clinical_attributes")
    op.drop_column("phenotype_observations", "observed_at")
    op.drop_column("phenotype_observations", "subject_member_id")
    op.drop_column("phenotype_observations", "canonical_hpo_id")
