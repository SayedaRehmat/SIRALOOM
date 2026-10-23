"""Represent explicit phenotype observation states.

Revision ID: 0050_phenotype_observation_status
Revises: 0049_case_access_role_capabilities
"""

import sqlalchemy as sa
from alembic import op

revision = "0050_phenotype_observation_status"
down_revision = "0049_case_access_role_capabilities"
branch_labels = None
depends_on = None


_STATUS_CHECK = (
    "phenotype_status IN ('PRESENT', 'ABSENT', 'EXCLUDED', 'UNKNOWN', 'NOT_ASSESSED')"
)
_PRESENT_CHECK = (
    "(phenotype_status = 'PRESENT' AND present) OR "
    "(phenotype_status <> 'PRESENT' AND NOT present)"
)
_CASE_STATUS_INDEX = "uq_phenotype_case_term_status"
_ANALYSIS_STATUS_INDEX = "uq_phenotype_analysis_term_status"


def upgrade():
    op.add_column(
        "phenotype_observations",
        sa.Column(
            "phenotype_status",
            sa.Text(),
            nullable=False,
            server_default="PRESENT",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE phenotype_observations "
            "SET phenotype_status = CASE WHEN present THEN 'PRESENT' ELSE 'ABSENT' END"
        )
    )

    if op.get_bind().dialect.name == "sqlite":
        # SQLite stores the original unnamed UNIQUE constraint as an autoindex.
        # Naming it during batch reflection allows a portable table rebuild.
        naming = {"uq": "%(table_name)s_%(column_0_name)s_key"}
        with op.batch_alter_table(
            "phenotype_observations", recreate="always", naming_convention=naming
        ) as batch:
            batch.drop_constraint(
                "phenotype_observations_case_id_key", type_="unique"
            )
            batch.create_check_constraint("ck_phenotype_observations_status", _STATUS_CHECK)
            batch.create_check_constraint(
                "ck_phenotype_observations_present_consistency", _PRESENT_CHECK
            )
    else:
        op.drop_constraint(
            "phenotype_observations_case_id_analysis_id_hpo_id_present_key",
            "phenotype_observations",
            type_="unique",
        )
        op.create_check_constraint(
            "ck_phenotype_observations_status", "phenotype_observations", _STATUS_CHECK
        )
        op.create_check_constraint(
            "ck_phenotype_observations_present_consistency",
            "phenotype_observations",
            _PRESENT_CHECK,
        )
    op.create_index(
        _CASE_STATUS_INDEX,
        "phenotype_observations",
        ["case_id", "hpo_id", "phenotype_status"],
        unique=True,
        sqlite_where=sa.text("analysis_id IS NULL"),
        postgresql_where=sa.text("analysis_id IS NULL"),
    )
    op.create_index(
        _ANALYSIS_STATUS_INDEX,
        "phenotype_observations",
        ["case_id", "analysis_id", "hpo_id", "phenotype_status"],
        unique=True,
        sqlite_where=sa.text("analysis_id IS NOT NULL"),
        postgresql_where=sa.text("analysis_id IS NOT NULL"),
    )


def downgrade():
    connection = op.get_bind()
    duplicate_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "SELECT case_id, analysis_id, hpo_id, present FROM phenotype_observations "
            "GROUP BY case_id, analysis_id, hpo_id, present "
            "HAVING COUNT(*) > 1) AS incompatible"
        )
    ).scalar_one()
    if duplicate_count:
        raise RuntimeError(
            "Cannot downgrade phenotype states: multiple non-present states for a term "
            "cannot be represented by the legacy schema."
        )

    op.drop_index(_CASE_STATUS_INDEX, table_name="phenotype_observations")
    op.drop_index(_ANALYSIS_STATUS_INDEX, table_name="phenotype_observations")
    if connection.dialect.name == "sqlite":
        naming = {"uq": "%(table_name)s_%(column_0_name)s_key"}
        with op.batch_alter_table(
            "phenotype_observations", recreate="always", naming_convention=naming
        ) as batch:
            batch.drop_constraint("ck_phenotype_observations_status", type_="check")
            batch.drop_constraint(
                "ck_phenotype_observations_present_consistency", type_="check"
            )
            batch.drop_column("phenotype_status")
            batch.create_unique_constraint(
                "phenotype_observations_case_id_analysis_id_hpo_id_present_key",
                ["case_id", "analysis_id", "hpo_id", "present"],
            )
    else:
        op.drop_constraint(
            "ck_phenotype_observations_present_consistency",
            "phenotype_observations",
            type_="check",
        )
        op.drop_constraint(
            "ck_phenotype_observations_status",
            "phenotype_observations",
            type_="check",
        )
        op.create_unique_constraint(
            "phenotype_observations_case_id_analysis_id_hpo_id_present_key",
            "phenotype_observations",
            ["case_id", "analysis_id", "hpo_id", "present"],
        )
        op.drop_column("phenotype_observations", "phenotype_status")
