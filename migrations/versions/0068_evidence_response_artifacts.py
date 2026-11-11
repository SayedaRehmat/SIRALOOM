"""Bind provider response bytes to immutable artifact identities.

Revision ID: 0068_evidence_response_artifacts
Revises: 0067_assay_validation_lifecycle
"""
from alembic import op
import sqlalchemy as sa

revision = "0068_evidence_response_artifacts"
down_revision = "0067_assay_validation_lifecycle"
branch_labels = None
depends_on = None

_RESPONSE_COLUMNS = (
    ("response_artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id")),
    ("response_artifact_sha256", sa.String(64), None),
    ("response_artifact_size_bytes", sa.BigInteger(), None),
    ("response_retention_status", sa.Text(), None),
    ("response_retention_reason", sa.Text(), None),
)


def upgrade():
    for table in ("annotations", "population_observations", "evidence"):
        for name, type_, foreign_key in _RESPONSE_COLUMNS:
            op.add_column(
                table,
                sa.Column(
                    name,
                    type_,
                    foreign_key,
                    nullable=(name != "response_retention_status"),
                    server_default=("NOT_AVAILABLE" if name == "response_retention_status" else None),
                ),
            )
    op.create_check_constraint(
        "ck_evidence_response_retention_status",
        "evidence",
        "response_retention_status IN ('RETAINED', 'NOT_PERMITTED', 'REVIEW_REQUIRED', 'NOT_AVAILABLE')",
    )
    op.create_check_constraint(
        "ck_annotations_response_retention_status",
        "annotations",
        "response_retention_status IN ('RETAINED', 'NOT_PERMITTED', 'REVIEW_REQUIRED', 'NOT_AVAILABLE')",
    )
    op.create_check_constraint(
        "ck_population_response_retention_status",
        "population_observations",
        "response_retention_status IN ('RETAINED', 'NOT_PERMITTED', 'REVIEW_REQUIRED', 'NOT_AVAILABLE')",
    )
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION siraloom_reject_raw_provider_artifact_mutation()
            RETURNS trigger AS $siraloom$
            BEGIN
                IF OLD.artifact_type = 'PROVIDER_RESPONSE_RAW' THEN
                    RAISE EXCEPTION 'raw provider response artifacts are immutable';
                END IF;
                RETURN OLD;
            END;
            $siraloom$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_raw_provider_artifact_immutable
            BEFORE UPDATE OR DELETE ON artifacts
            FOR EACH ROW EXECUTE FUNCTION siraloom_reject_raw_provider_artifact_mutation()
        """)
    elif connection.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_raw_provider_artifact_immutable_update
            BEFORE UPDATE ON artifacts
            WHEN OLD.artifact_type = 'PROVIDER_RESPONSE_RAW'
            BEGIN
                SELECT RAISE(ABORT, 'raw provider response artifacts are immutable');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_raw_provider_artifact_immutable_delete
            BEFORE DELETE ON artifacts
            WHEN OLD.artifact_type = 'PROVIDER_RESPONSE_RAW'
            BEGIN
                SELECT RAISE(ABORT, 'raw provider response artifacts are immutable');
            END
        """)


def downgrade():
    connection = op.get_bind()
    retained = connection.execute(sa.text(
        "SELECT COUNT(*) FROM artifacts WHERE artifact_type = 'PROVIDER_RESPONSE_RAW'"
    )).scalar_one()
    if retained:
        raise RuntimeError("Refusing to downgrade: immutable provider response artifacts exist.")
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_raw_provider_artifact_immutable ON artifacts")
        op.execute("DROP FUNCTION IF EXISTS siraloom_reject_raw_provider_artifact_mutation()")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_raw_provider_artifact_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS trg_raw_provider_artifact_immutable_delete")
    for table, name in (
        ("population_observations", "ck_population_response_retention_status"),
        ("annotations", "ck_annotations_response_retention_status"),
        ("evidence", "ck_evidence_response_retention_status"),
    ):
        op.drop_constraint(name, table, type_="check")
    for table in ("annotations", "population_observations", "evidence"):
        for name, _type, _fk in reversed(_RESPONSE_COLUMNS):
            op.drop_column(table, name)
