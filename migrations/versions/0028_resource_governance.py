"""Add tenant-scoped scientific resources and qualification records."""

from alembic import op
import sqlalchemy as sa

revision = "0028_resource_governance"
down_revision = "0027_signed_report_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "resources",
        sa.Column("organization_id", sa.Uuid(), nullable=True),
    )
    with op.batch_alter_table("resources") as batch_op:
        batch_op.create_foreign_key(
            "fk_resources_organization_id",
            "organizations",
            ["organization_id"],
            ["id"],
        )
        batch_op.drop_index("uq_resources_active_identity")
        batch_op.create_index(
            "uq_resources_active_identity",
            ["organization_id", "name", "provider", "resource_type", "genome_build"],
            unique=True,
            postgresql_where=sa.text("status = 'ACTIVE'"),
            sqlite_where=sa.text("status = 'ACTIVE'"),
        )

    op.create_table(
        "resource_qualifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("qualification_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("qualified_by", sa.Uuid(), nullable=True),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["qualified_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_id", "qualification_version"),
    )


def downgrade():
    op.drop_table("resource_qualifications")
    with op.batch_alter_table("resources") as batch_op:
        batch_op.drop_index("uq_resources_active_identity")
        batch_op.create_index(
            "uq_resources_active_identity",
            ["name", "provider", "resource_type", "genome_build"],
            unique=True,
            postgresql_where=sa.text("status = 'ACTIVE'"),
            sqlite_where=sa.text("status = 'ACTIVE'"),
        )
        batch_op.drop_constraint("fk_resources_organization_id", type_="foreignkey")
    op.drop_column("resources", "organization_id")
