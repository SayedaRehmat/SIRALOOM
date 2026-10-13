FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Debian Bookworm's bcftools package is pinned to the exact version the
# application requires. A package/version mismatch fails the image build.
ARG BCFTOOLS_DEBIAN_VERSION=1.16-1

COPY pyproject.toml ./
COPY backend ./backend
COPY alembic.ini ./
COPY migrations ./migrations
COPY workflows ./workflows
COPY configs ./configs
COPY scripts ./scripts
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libcairo2 libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info fonts-noto-core \
       postgresql-client "bcftools=${BCFTOOLS_DEBIAN_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -e . \
    && test "$(bcftools --version | awk 'NR == 1 {print $2}')" = "1.16"

RUN chmod +x scripts/start_api_with_worker.sh scripts/start_api.sh scripts/start_worker.sh scripts/start_beat.sh

CMD ["./scripts/start_api_with_worker.sh"]
