#!/usr/bin/env sh
set -eu

# Migrations are owned by the API/release step. Each worker pool consumes only
# the queue assigned to its immutable BCFtools/HTSlib image profile.
exec celery -A backend.app.infrastructure.queue.celery_app.celery_app worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency="${CELERY_CONCURRENCY:-2}" \
  --queues="${CELERY_QUEUES:-celery,bioinformatics.bcftools.1_25}"
