"""Scope population observations to an analysis for lineage and reanalysis safety."""
from alembic import op
import sqlalchemy as sa

revision = "0004_population_analysis_scope"
down_revision = "0003_evidence_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("population_observations") as batch:
        batch.add_column(sa.Column("analysis_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_population_observations_analysis",
            "analyses",
            ["analysis_id"],
            ["id"],
        )
        batch.create_unique_constraint(
            "uq_population_analysis_variant_resource_population",
            ["analysis_id", "variant_id", "resource_id", "population_code"],
        )


def downgrade() -> None:
    with op.batch_alter_table("population_observations") as batch:
        batch.drop_constraint("uq_population_analysis_variant_resource_population", type_="unique")
        batch.drop_constraint("fk_population_observations_analysis", type_="foreignkey")
        batch.drop_column("analysis_id")
