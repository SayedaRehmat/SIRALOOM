FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml ./
COPY backend ./backend
COPY alembic.ini ./
COPY migrations ./migrations
COPY workflows ./workflows
COPY configs ./configs
COPY scripts ./scripts

# Ubuntu 24.04 supplies Python 3.12 and bcftools 1.19. The build must fail
# if the repository package changes the scientific runtime unexpectedly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3.12 python3.12-venv python3.12-dev build-essential \
       libcairo2 libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info fonts-noto-core \
       postgresql-client bcftools \
    && test "$(bcftools --version | awk 'NR == 1 {print $2}')" = "1.19" \
    && python3.12 -m venv /opt/venv \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e . \
    && rm -rf /var/lib/apt/lists/*

RUN chmod +x scripts/start_api_with_worker.sh scripts/start_api.sh scripts/start_worker.sh scripts/start_beat.sh

CMD ["./scripts/start_api_with_worker.sh"]
