#!/usr/bin/env sh
set -eu

# Migrations are owned by the API/release step. The worker only waits for the
# configured services and then starts the durable Celery consumer.
exec celery -A backend.app.infrastructure.queue.celery_app.celery_app worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency="${CELERY_CONCURRENCY:-2}"
