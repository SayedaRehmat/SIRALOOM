"""Bind each case to an explicitly approved lab execution environment.

Revision ID: 0073_case_execution_environment
Revises: 0072_case_scoped_tool_executions
"""
from alembic import op
import sqlalchemy as sa


revision = "0073_case_execution_environment"
down_revision = "0072_case_scoped_tool_executions"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite supports ADD COLUMN with an inline REFERENCES clause when the
    # new nullable column has an implicit NULL default. Keeping this as a
    # single ALTER avoids rebuilding the cases table and disturbing the many
    # existing foreign keys that point to it.
    op.add_column(
        "cases",
        sa.Column(
            "execution_environment_registration_id",
            sa.Uuid(),
            sa.ForeignKey(
                "execution_environment_registrations.id",
                name="fk_cases_execution_environment_registration",
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_cases_execution_environment_registration",
        "cases",
        ["execution_environment_registration_id"],
    )


def downgrade():
    op.drop_index("ix_cases_execution_environment_registration", table_name="cases")
    op.drop_column("cases", "execution_environment_registration_id")
