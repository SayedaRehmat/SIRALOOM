"""Merge the organization-invitation branch into the canonical migration chain.

The invitation migration was historically created from 0019 while the main
schema chain continued through 0020_organization_entitlements. This merge
preserves both histories and restores a single Alembic head.
"""

from alembic import op


revision = "0037_merge_organization_invitation_branch"
down_revision = (
    "0036_analysis_dispatch_outbox",
    "0020_organization_invitations",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
