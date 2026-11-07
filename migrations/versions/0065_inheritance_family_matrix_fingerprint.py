"""Persist the exact family genotype matrix fingerprint on inheritance assessments.

Revision ID: 0065_inheritance_family_matrix_fingerprint
Revises: 0064_pedigree_sample_identity_evidence
"""
import sqlalchemy as sa
from alembic import op

revision = "0065_inheritance_family_matrix_fingerprint"
down_revision = "0064_pedigree_sample_identity_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "inheritance_assessments",
        sa.Column("family_matrix_fingerprint", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_inheritance_assessment_family_matrix_fingerprint",
        "inheritance_assessments",
        ["family_matrix_fingerprint"],
    )


def downgrade():
    connection = op.get_bind()
    count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM inheritance_assessments "
            "WHERE family_matrix_fingerprint IS NOT NULL"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Refusing to downgrade: inheritance assessments reference immutable family genotype matrices."
        )
    op.drop_index(
        "ix_inheritance_assessment_family_matrix_fingerprint",
        table_name="inheritance_assessments",
    )
    op.drop_column("inheritance_assessments", "family_matrix_fingerprint")
