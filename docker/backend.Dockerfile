FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY backend ./backend
COPY alembic.ini ./
COPY migrations ./migrations
RUN echo "========== SIRALOOM MIGRATION DEBUG ==========" \
    && echo "PWD:" \
    && pwd \
    && echo "MIGRATIONS DIRECTORY:" \
    && find /app/migrations -maxdepth 3 -type f -print | sort \
    && echo "VERSIONS DIRECTORY:" \
    && ls -la /app/migrations/versions \
    && echo "0007 FILE:" \
    && cat /app/migrations/versions/0007_classification_specification_metadata.py \
    && echo "0008 FILE:" \
    && cat /app/migrations/versions/0008_review_workflow.py \
    && echo "REVISION DECLARATIONS:" \
    && grep -R "^revision =" /app/migrations/versions \
    && echo "0007 REFERENCES:" \
    && grep -R "0007_classification_specification_metadata" /app/migrations/versions \
    && echo "=============================================="
COPY workflows ./workflows
COPY configs ./configs
COPY scripts ./scripts
RUN echo "===== ALEMBIC MIGRATIONS IN IMAGE =====" \
    && find /app/migrations/versions -maxdepth 1 -type f -name "*.py" -print | sort \
    && echo "===== REVISION 0007 =====" \
    && grep -R "revision = \"0007_classification_specification_metadata\"" /app/migrations/versions \
    && echo "===== REFERENCES TO 0007 =====" \
    && grep -R "0007_classification_specification_metadata" /app/migrations/versions \
    && echo "======================================="
RUN apt-get update \
    && apt-get install -y --no-install-recommends libcairo2 libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -e .

RUN chmod +x scripts/start_api_with_worker.sh

CMD ["./scripts/start_api_with_worker.sh"]
