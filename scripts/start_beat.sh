#!/usr/bin/env sh
set -eu

# Celery Beat is a singleton scheduler. Run it separately from API/worker
# processes so multiple API/worker replicas cannot create duplicate schedules.
exec celery -A backend.app.infrastructure.queue.celery_app.celery_app beat \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}"
