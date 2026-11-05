ARG BCFTOOLS_BUILD_STAGE=bcftools
ARG BCFTOOLS_BUILD_LOCK_FILE=configs/bioinformatics/profiles/bcftools-1.24.1-build-linux-64.lock
ARG BCFTOOLS_LOCK_FILE=configs/bioinformatics/profiles/bcftools-1.25-linux-64.lock
ARG BCFTOOLS_PLATFORM=linux-64
ARG BCFTOOLS_PROFILE_ID=bcftools-1.25-htslib-1.25-linux-64
ARG BCFTOOLS_VERSION=1.25
ARG HTSLIB_VERSION=1.25

FROM mambaorg/micromamba:2.3.1 AS bcftools

ARG BCFTOOLS_LOCK_FILE
ARG BCFTOOLS_PLATFORM
ENV MAMBA_ROOT_PREFIX=/opt/conda
COPY --chown=$MAMBA_USER:$MAMBA_USER ${BCFTOOLS_LOCK_FILE} /tmp/bcftools-explicit.lock
RUN case "$(uname -m):${BCFTOOLS_PLATFORM}" in \
        x86_64:linux-64|aarch64:linux-aarch64) ;; \
        *) echo "No locked BCFtools profile for build architecture $(uname -m) and platform ${BCFTOOLS_PLATFORM}" >&2; exit 1 ;; \
    esac \
    && micromamba install --yes --name base --file /tmp/bcftools-explicit.lock \
    && micromamba clean --all --yes

FROM mambaorg/micromamba:2.3.1 AS bcftools-1.24.1-source

ARG BCFTOOLS_BUILD_LOCK_FILE
ENV MAMBA_ROOT_PREFIX=/tmp/build-env
RUN mkdir -p /opt/conda && chown $MAMBA_USER:$MAMBA_USER /opt/conda
COPY --chown=$MAMBA_USER:$MAMBA_USER ${BCFTOOLS_BUILD_LOCK_FILE} /tmp/bcftools-build-explicit.lock
RUN micromamba create --yes --name bcftools-build --file /tmp/bcftools-build-explicit.lock \
    && micromamba clean --all --yes
COPY scripts/build_bcftools_1_24_1.sh /tmp/build_bcftools_1_24_1.sh
RUN micromamba run --name bcftools-build env BCFTOOLS_PREFIX=/opt/conda bash /tmp/build_bcftools_1_24_1.sh

FROM python:3.12-slim

ARG BCFTOOLS_BUILD_STAGE
ARG BCFTOOLS_PROFILE_ID
ARG BCFTOOLS_VERSION
ARG HTSLIB_VERSION
ENV BCFTOOLS_PROFILE_ID=${BCFTOOLS_PROFILE_ID} BCFTOOLS_VERSION=${BCFTOOLS_VERSION} HTSLIB_VERSION=${HTSLIB_VERSION} BCFTOOLS_EXECUTABLE=/opt/conda/bin/bcftools
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
ENV HOME=/home/siraloom SIRALOOM_CONFIG_ROOT=/app

COPY --from=${BCFTOOLS_BUILD_STAGE} /opt/conda /opt/conda
ENV PATH="/opt/venv/bin:/opt/conda/bin:${PATH}" LD_LIBRARY_PATH="/opt/conda/lib"

# Resolve the application dependency graph only from the committed uv lock.
# The lock manager itself is pinned and removed from the final runtime image.
COPY pyproject.toml uv.lock ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends libcairo2 libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info fonts-noto-core postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && /usr/local/bin/python -m pip install --no-cache-dir --disable-pip-version-check --no-deps "uv==0.10.0" \
    && test "$(uv --version)" = "uv 0.10.0" \
    && uv sync --python /usr/local/bin/python --locked --no-dev --no-install-project

COPY backend ./backend
COPY alembic.ini ./
COPY migrations ./migrations
COPY workflows ./workflows
COPY configs ./configs
COPY scripts ./scripts

RUN uv sync --python /usr/local/bin/python --locked --no-dev --no-editable \
    && python -c "import redis; import kombu.transport.redis; import backend.app" \
    && test "$(bcftools --version | head -n1)" = "bcftools ${BCFTOOLS_VERSION}" \
    && test "$(bcftools --version | sed -n '2s/.*htslib //p')" = "${HTSLIB_VERSION}" \
    && /usr/local/bin/python -m pip uninstall -y uv

RUN chmod +x scripts/start_api_with_worker.sh

USER 10001:10001

CMD ["./scripts/start_api_with_worker.sh"]
