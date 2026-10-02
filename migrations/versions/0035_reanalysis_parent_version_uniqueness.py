"""Make reanalysis child versions unique per parent analysis.

Independent root analyses for one case may all use analysis_version=1.
Only child analyses participate in the per-parent version sequence.
"""

from alembic import op
import sqlalchemy as sa


revision = "0035_reanalysis_parent_version_uniqueness"
down_revision = "0034_resource_discovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_analyses_parent_version",
        "analyses",
        ["parent_analysis_id", "analysis_version"],
        unique=True,
        postgresql_where=sa.text("parent_analysis_id IS NOT NULL"),
        sqlite_where=sa.text("parent_analysis_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_analyses_parent_version", table_name="analyses")
