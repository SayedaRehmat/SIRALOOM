"""Make resource change-event identity concurrency-safe."""

import hashlib

from alembic import op
import sqlalchemy as sa

revision = "0023_reanalysis_change_event_fingerprint"
down_revision = "0022_resource_registry_active_identity"
branch_labels = None
depends_on = None


def _fingerprint(organization_id, trigger_type, resource_kind, resource_name, new_version, new_checksum):
    material = "\x1f".join([
        str(organization_id),
        trigger_type,
        resource_kind,
        resource_name,
        new_version or "",
        new_checksum or "",
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def upgrade():
    op.add_column(
        "reanalysis_change_events",
        sa.Column("change_fingerprint", sa.Text(), nullable=True),
    )

    table = sa.table(
        "reanalysis_change_events",
        sa.column("id", sa.Uuid()),
        sa.column("organization_id", sa.Uuid()),
        sa.column("trigger_type", sa.Text()),
        sa.column("resource_kind", sa.Text()),
        sa.column("resource_name", sa.Text()),
        sa.column("new_version", sa.Text()),
        sa.column("new_checksum", sa.Text()),
        sa.column("change_fingerprint", sa.Text()),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            table.c.id,
            table.c.organization_id,
            table.c.trigger_type,
            table.c.resource_kind,
            table.c.resource_name,
            table.c.new_version,
            table.c.new_checksum,
        )
    ).fetchall()

    for row in rows:
        bind.execute(
            table.update()
            .where(table.c.id == row.id)
            .values(change_fingerprint=_fingerprint(
                row.organization_id,
                row.trigger_type,
                row.resource_kind,
                row.resource_name,
                row.new_version,
                row.new_checksum,
            ))
        )

    with op.batch_alter_table("reanalysis_change_events") as batch_op:
        batch_op.alter_column("change_fingerprint", nullable=False)
    op.create_index(
        "uq_reanalysis_change_events_fingerprint",
        "reanalysis_change_events",
        ["change_fingerprint"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "uq_reanalysis_change_events_fingerprint",
        table_name="reanalysis_change_events",
    )
    op.drop_column("reanalysis_change_events", "change_fingerprint")
