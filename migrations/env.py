from logging.config import fileConfig
from pathlib import Path
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool, inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db import models  # noqa: F401
from backend.app.infrastructure.db import organization_invitations  # noqa: F401


config = context.config


if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = Base.metadata


def get_url() -> str:
    """Return the configured database URL using psycopg 3 for PostgreSQL."""
    url = os.getenv(
        "DATABASE_URL",
        config.get_main_option("sqlalchemy.url"),
    )

    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured and sqlalchemy.url is empty."
        )

    if url.startswith("postgresql://"):
        return url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    if url.startswith("postgres://"):
        return url.replace(
            "postgres://",
            "postgresql+psycopg://",
            1,
        )

    return url


def ensure_postgresql_alembic_version_capacity(connection) -> None:
    """Allow PostgreSQL to store the repository's full Alembic revision IDs.

    Alembic's default version table uses VARCHAR(32). SIRALOOM has historical
    revision IDs longer than 32 characters, so PostgreSQL must widen the
    version column before Alembic advances to those revisions.
    """
    if connection.dialect.name != "postgresql":
        return

    inspector = inspect(connection)
    if inspector.has_table("alembic_version"):
        connection.execute(
            text(
                "ALTER TABLE alembic_version "
                "ALTER COLUMN version_num TYPE VARCHAR(255)"
            )
        )
        return

    connection.execute(
        text(
            "CREATE TABLE alembic_version ("
            "version_num VARCHAR(255) NOT NULL PRIMARY KEY"
            ")"
        )
    )


def run_migrations_offline() -> None:
    """Run Alembic migrations without creating a database connection."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run Alembic migrations using a live database connection."""
    configuration = config.get_section(
        config.config_ini_section,
        {},
    )

    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            ensure_postgresql_alembic_version_capacity(connection)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
