#!/usr/bin/env bash

set -euo pipefail

echo "SIRALOOM: running database migrations..."
psql "$DATABASE_URL" -c "ALTER TABLE IF EXISTS alembic_version ALTER COLUMN version_num TYPE VARCHAR(255);" || true
alembic upgrade head

echo "SIRALOOM: starting Celery worker..."

celery \
  -A backend.app.infrastructure.queue.celery_app.celery_app \
  worker \
  --loglevel="${LOG_LEVEL:-INFO}" \
  --concurrency="${CELERY_CONCURRENCY:-1}" \
  --prefetch-multiplier="${CELERY_WORKER_PREFETCH_MULTIPLIER:-1}" \
  --max-tasks-per-child="${CELERY_WORKER_MAX_TASKS_PER_CHILD:-20}" &
  
WORKER_PID=$!

cleanup() {
    echo "SIRALOOM: stopping Celery worker..."
    kill "${WORKER_PID}" 2>/dev/null || true
    wait "${WORKER_PID}" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "SIRALOOM: starting FastAPI..."

exec uvicorn \
  backend.app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}"
