"""Add pedigree, inheritance and segregation review context."""
from alembic import op
import sqlalchemy as sa

revision = "0015_pedigree_inheritance_segregation"
down_revision = "0014_phenotype_evidence"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "pedigree_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("member_identifier", sa.Text(), nullable=False),
        sa.Column("relationship_to_proband", sa.Text(), nullable=True),
        sa.Column("sex", sa.Text(), nullable=True),
        sa.Column("affected_status", sa.Text(), nullable=False, server_default="UNKNOWN"),
        sa.Column("is_proband", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sampled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("specimen_id", sa.Uuid(), sa.ForeignKey("specimens.id"), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "member_identifier"),
    )
    op.create_index("ix_pedigree_members_case", "pedigree_members", ["case_id"])
    op.create_table(
        "pedigree_relationships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("parent_member_id", sa.Uuid(), sa.ForeignKey("pedigree_members.id"), nullable=False),
        sa.Column("child_member_id", sa.Uuid(), sa.ForeignKey("pedigree_members.id"), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False, server_default="PARENT_CHILD"),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "parent_member_id", "child_member_id"),
    )
    op.create_index("ix_pedigree_relationships_case", "pedigree_relationships", ["case_id"])
    op.create_table(
        "segregation_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("pedigree_member_id", sa.Uuid(), sa.ForeignKey("pedigree_members.id"), nullable=False),
        sa.Column("genotype", sa.Text(), nullable=True),
        sa.Column("zygosity", sa.Text(), nullable=True),
        sa.Column("phase", sa.Text(), nullable=True),
        sa.Column("allele_observed", sa.Text(), nullable=True),
        sa.Column("phenotype_status", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="HUMAN_REVIEW"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_id", "variant_id", "pedigree_member_id"),
    )
    op.create_index("ix_segregation_observations_variant", "segregation_observations", ["analysis_id", "variant_id"])
    op.create_table(
        "inheritance_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("observation_fingerprint", sa.Text(), nullable=False),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_id", "variant_id", "model", "observation_fingerprint"),
    )
    op.create_index("ix_inheritance_assessments_variant", "inheritance_assessments", ["analysis_id", "variant_id"])

def downgrade():
    op.drop_index("ix_inheritance_assessments_variant", table_name="inheritance_assessments")
    op.drop_table("inheritance_assessments")
    op.drop_index("ix_segregation_observations_variant", table_name="segregation_observations")
    op.drop_table("segregation_observations")
    op.drop_index("ix_pedigree_relationships_case", table_name="pedigree_relationships")
    op.drop_table("pedigree_relationships")
    op.drop_index("ix_pedigree_members_case", table_name="pedigree_members")
    op.drop_table("pedigree_members")
