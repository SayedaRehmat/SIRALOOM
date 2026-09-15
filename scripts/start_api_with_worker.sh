#!/usr/bin/env bash
set -euo pipefail

echo "Running database migrations..."
alembic upgrade head

echo "Starting Celery worker..."
celery -A app.workers.celery_app worker \
  --loglevel=INFO \
  --concurrency="${CELERY_CONCURRENCY:-1}" &
WORKER_PID=$!

cleanup() {
    echo "Stopping Celery worker..."
    kill "$WORKER_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "Starting SIRALOOM API..."

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}"
