"""Merge the organization invitation branch with the release migration head.

The invitation migration was introduced from 0019 while the main migration
line continued through 0036. This merge revision restores one Alembic head
without changing either branch's schema operations.
"""

revision = "0037_merge_organization_invitations"
down_revision = ("0020_organization_invitations", "0036_analysis_dispatch_outbox")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
