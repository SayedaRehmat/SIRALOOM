"""Add per-user case access grants.

Revision ID: 0048_case_access_grants
Revises: 0047_specimen_case_identity
"""

from uuid import UUID, uuid4

from alembic import op
import sqlalchemy as sa


revision = "0048_case_access_grants"
down_revision = "0047_specimen_case_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_access_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("can_read", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_write", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "can_read OR can_write OR can_review",
            name="ck_case_access_grants_nonempty",
        ),
        sa.CheckConstraint(
            "(NOT can_write OR can_read) AND (NOT can_review OR can_read)",
            name="ck_case_access_grants_capabilities_include_read",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "user_id", name="uq_case_access_grants_case_user"),
    )
    op.create_index("ix_case_access_grants_user_id", "case_access_grants", ["user_id"])

    # Preserve the access that existing tenants have today. This is a one-time
    # migration snapshot: subsequently joining an organization does not grant
    # access to historical or future cases without an explicit case grant.
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT c.id AS case_id, m.user_id
            FROM cases AS c
            JOIN organization_memberships AS m
              ON m.organization_id = c.organization_id
             AND m.status = 'ACTIVE'
            """
        )
    )
    table = sa.table(
        "case_access_grants",
        sa.column("id", sa.Uuid()),
        sa.column("case_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("can_read", sa.Boolean()),
        sa.column("can_write", sa.Boolean()),
        sa.column("can_review", sa.Boolean()),
        sa.column("granted_by", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    batch = []
    for row in rows:
        batch.append(
            {
                "id": uuid4(),
                "case_id": UUID(str(row.case_id)),
                "user_id": UUID(str(row.user_id)),
                "can_read": True,
                "can_write": True,
                "can_review": True,
                "granted_by": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        if len(batch) == 1000:
            connection.execute(table.insert(), batch)
            batch.clear()
    if batch:
        connection.execute(table.insert(), batch)


def downgrade():
    op.drop_index("ix_case_access_grants_user_id", table_name="case_access_grants")
    op.drop_table("case_access_grants")
