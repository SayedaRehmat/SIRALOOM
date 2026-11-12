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
    op.add_column(
        "cases",
        sa.Column("execution_environment_registration_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_cases_execution_environment_registration",
        "cases",
        "execution_environment_registrations",
        ["execution_environment_registration_id"],
        ["id"],
    )
    op.create_index(
        "ix_cases_execution_environment_registration",
        "cases",
        ["execution_environment_registration_id"],
    )


def downgrade():
    op.drop_index("ix_cases_execution_environment_registration", table_name="cases")
    op.drop_constraint(
        "fk_cases_execution_environment_registration",
        "cases",
        type_="foreignkey",
    )
    op.drop_column("cases", "execution_environment_registration_id")
