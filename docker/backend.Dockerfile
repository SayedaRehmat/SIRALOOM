FROM mambaorg/micromamba:2.3.1 AS bcftools

ENV MAMBA_ROOT_PREFIX=/opt/conda
COPY --chown=$MAMBA_USER:$MAMBA_USER configs/bioinformatics/bcftools-environment.yml /tmp/bcftools-environment.yml
RUN micromamba install --yes --name base --file /tmp/bcftools-environment.yml \
    && micromamba clean --all --yes

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_PROGRESS=1
WORKDIR /app

# The API, Celery worker, Beat scheduler, migrations, and scientific tools all
# run as this fixed unprivileged identity. Lab bind mounts and file-backed
# Compose secrets must grant this UID/GID only the access each service needs.
RUN groupadd --system --gid 10001 siraloom \
    && useradd --system --uid 10001 --gid siraloom --create-home \
        --home-dir /home/siraloom --shell /usr/sbin/nologin siraloom \
    && mkdir -p \
        /data/siraloom/artifacts \
        /data/siraloom/resource-cache \
        /data/siraloom/scratch \
        /data/siraloom/beat \
        /data/references \
    && chown -R 10001:10001 /data/siraloom
ENV HOME=/home/siraloom

COPY --from=bcftools /opt/conda /opt/conda
ENV PATH="/opt/venv/bin:/opt/conda/bin:${PATH}"

# Resolve the application dependency graph only from the committed uv lock.
# The lock manager itself is pinned and removed from the final runtime image.
COPY pyproject.toml uv.lock ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends libcairo2 libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info fonts-noto-core postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --disable-pip-version-check --no-deps "uv==0.10.0" \
    && test "$(uv --version)" = "uv 0.10.0" \
    && uv sync --locked --no-dev --no-install-project

COPY backend ./backend
COPY alembic.ini ./
COPY migrations ./migrations
COPY workflows ./workflows
COPY configs ./configs
COPY scripts ./scripts

RUN uv sync --locked --no-dev --no-editable \
    && python -c "import redis; import kombu.transport.redis; import backend.app" \
    && test "$(bcftools --version | head -n1)" = "bcftools 1.25" \
    && /usr/local/bin/python -m pip uninstall -y uv

RUN chmod +x scripts/start_api_with_worker.sh

USER 10001:10001

CMD ["./scripts/start_api_with_worker.sh"]
