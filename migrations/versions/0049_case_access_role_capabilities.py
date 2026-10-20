"""Remove case grant capabilities unsupported by member roles.

Revision ID: 0049_case_access_role_capabilities
Revises: 0048_case_access_grants
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0049_case_access_role_capabilities"
down_revision = "0048_case_access_grants"
branch_labels = None
depends_on = None


WRITE_ROLES = (
    "platform_admin", "organization_admin", "lab_director",
    "clinical_geneticist", "bioinformatician", "lab_scientist",
)
REVIEW_ROLES = (
    "platform_admin", "organization_admin", "lab_director",
    "clinical_geneticist", "reviewer",
)


def upgrade():
    grants = sa.table(
        "case_access_grants",
        sa.column("case_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("can_write", sa.Boolean()),
        sa.column("can_review", sa.Boolean()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    cases = sa.table(
        "cases",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
    )
    memberships = sa.table(
        "organization_memberships",
        sa.column("organization_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("role", sa.String()),
    )
    eligible_membership = cases.join(
        memberships,
        cases.c.organization_id == memberships.c.organization_id,
    )
    updated_at = datetime.now(timezone.utc)

    write_allowed = sa.exists(
        sa.select(sa.literal(1))
        .select_from(eligible_membership)
        .where(
            cases.c.id == grants.c.case_id,
            memberships.c.user_id == grants.c.user_id,
            memberships.c.role.in_(WRITE_ROLES),
        )
    )
    review_allowed = sa.exists(
        sa.select(sa.literal(1))
        .select_from(eligible_membership)
        .where(
            cases.c.id == grants.c.case_id,
            memberships.c.user_id == grants.c.user_id,
            memberships.c.role.in_(REVIEW_ROLES),
        )
    )
    op.execute(
        sa.update(grants)
        .where(grants.c.can_write.is_(True), ~write_allowed)
        .values(can_write=False, updated_at=updated_at)
    )
    op.execute(
        sa.update(grants)
        .where(grants.c.can_review.is_(True), ~review_allowed)
        .values(can_review=False, updated_at=updated_at)
    )


def downgrade():
    # Re-enabling role-incompatible grants would be unsafe. The data correction
    # is intentionally irreversible; the schema remains managed by revision 0048.
    pass
