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
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # Alembic's add_column emits the FK as a separate ALTER CONSTRAINT on
        # SQLite, which SQLite cannot execute. A nullable column with an
        # inline REFERENCES clause is supported without rebuilding cases.
        op.execute(
            "ALTER TABLE cases ADD COLUMN "
            "execution_environment_registration_id CHAR(32) "
            "REFERENCES execution_environment_registrations (id)"
        )
    else:
        op.add_column(
            "cases",
            sa.Column(
                "execution_environment_registration_id",
                sa.Uuid(),
                nullable=True,
            ),
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
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("cases") as batch_op:
            batch_op.drop_column("execution_environment_registration_id")
    else:
        op.drop_constraint(
            "fk_cases_execution_environment_registration",
            "cases",
            type_="foreignkey",
        )
        op.drop_column("cases", "execution_environment_registration_id")
