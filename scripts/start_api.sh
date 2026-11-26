#!/usr/bin/env sh
set -eu

echo "[SIRALOOM] applying database migrations..."
alembic upgrade head

echo "[SIRALOOM] starting API..."
exec uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
