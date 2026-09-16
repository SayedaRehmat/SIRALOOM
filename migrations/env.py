from logging.config import fileConfig
from pathlib import Path
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db import models  # noqa: F401

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

```
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
```

def run_migrations_offline() -> None:
context.configure(
url=get_url(),
target_metadata=target_metadata,
literal_binds=True,
dialect_opts={"paramstyle": "named"},
)

```
with context.begin_transaction():
    context.run_migrations()
```

def run_migrations_online() -> None:
configuration = config.get_section(
config.config_ini_section,
{},
)

```
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
        context.run_migrations()
```

if context.is_offline_mode():
run_migrations_offline()
else:
run_migrations_online()
