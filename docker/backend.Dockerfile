ARG BCFTOOLS_LOCK_FILE=configs/bioinformatics/profiles/bcftools-1.25-linux-64.lock
ARG EBI_VCF_VALIDATOR_LOCK_FILE=configs/bioinformatics/profiles/ebi-vcf-validator-0.10.2-linux-64.lock
ARG EBI_VCF_VALIDATOR_VERSION=0.10.2
ARG EBI_VCF_VALIDATOR_PROFILE_ID=ebi-vcf-validator-0.10.2-linux-64
ARG BCFTOOLS_PLATFORM=linux-64
ARG BCFTOOLS_PROFILE_ID=bcftools-1.25-htslib-1.25-linux-64
ARG BCFTOOLS_VERSION=1.25
ARG HTSLIB_VERSION=1.25
ARG BCFTOOLS_BASE_IMAGE=python:3.12-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ARG DEBIAN_SNAPSHOT_TIMESTAMP=20261105T000000Z
ARG UV_VERSION=0.10.0
ARG UV_ARCHIVE_SHA256=230e328948c92dd1ebad83949c4d56e83813dfe9c6362a4c519e6a227973f1ae

FROM mambaorg/micromamba:2.3.1@sha256:6113627f42f39d065f116b8649e3f699ed2bbe076a58b64ae50fafb4acb8aaf3 AS bcftools

ARG BCFTOOLS_LOCK_FILE
ARG BCFTOOLS_PLATFORM
ENV MAMBA_ROOT_PREFIX=/opt/conda
COPY --chown=$MAMBA_USER:$MAMBA_USER ${BCFTOOLS_LOCK_FILE} /tmp/bcftools-explicit.lock
RUN case "$(uname -m):${BCFTOOLS_PLATFORM}" in \
        x86_64:linux-64) ;; \
        *) echo "No locked BCFtools profile for build architecture $(uname -m) and platform ${BCFTOOLS_PLATFORM}" >&2; exit 1 ;; \
    esac \
    && micromamba install --yes --name base --file /tmp/bcftools-explicit.lock \
    && micromamba clean --all --yes

FROM mambaorg/micromamba:2.3.1@sha256:6113627f42f39d065f116b8649e3f699ed2bbe076a58b64ae50fafb4acb8aaf3 AS ebi-validator

ARG EBI_VCF_VALIDATOR_LOCK_FILE
ENV MAMBA_ROOT_PREFIX=/opt/ebi-root
COPY --chown=$MAMBA_USER:$MAMBA_USER ${EBI_VCF_VALIDATOR_LOCK_FILE} /tmp/ebi-vcf-validator-explicit.lock
RUN micromamba create --yes --name ebi-validator --file /tmp/ebi-vcf-validator-explicit.lock \
    && micromamba clean --all --yes

FROM ${BCFTOOLS_BASE_IMAGE}

ARG BCFTOOLS_PROFILE_ID
ARG BCFTOOLS_VERSION
ARG HTSLIB_VERSION
ARG EBI_VCF_VALIDATOR_VERSION
ARG EBI_VCF_VALIDATOR_PROFILE_ID
ARG DEBIAN_SNAPSHOT_TIMESTAMP
ARG UV_VERSION
ARG UV_ARCHIVE_SHA256
ENV BCFTOOLS_PROFILE_ID=${BCFTOOLS_PROFILE_ID} BCFTOOLS_VERSION=${BCFTOOLS_VERSION} HTSLIB_VERSION=${HTSLIB_VERSION} BCFTOOLS_EXECUTABLE=/opt/conda/bin/bcftools CELERY_QUEUES=celery,bioinformatics.bcftools.1_25
ENV EBI_VCF_VALIDATOR_VERSION=${EBI_VCF_VALIDATOR_VERSION} EBI_VCF_VALIDATOR_PROFILE_ID=${EBI_VCF_VALIDATOR_PROFILE_ID} EBI_VCF_VALIDATOR_EXECUTABLE=/opt/ebi/bin/vcf_validator EBI_VCF_ASSEMBLY_CHECKER_EXECUTABLE=/opt/ebi/bin/vcf_assembly_checker
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_PROGRESS=1
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt SSL_CERT_DIR=/etc/ssl/certs
WORKDIR /app

# The API, Celery worker, Beat scheduler, migrations, and scientific tools all
# run as this fixed unprivileged identity. Lab bind mounts and file-backed
# Compose secrets must grant this UID/GID only the access each service needs.
RUN test "$(uname -m)" = "x86_64" || { echo "This locked BCFtools runtime is qualified only for Linux AMD64 (x86_64)." >&2; exit 1; } \
    && groupadd --system --gid 10001 siraloom \
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

COPY --from=bcftools /opt/conda /opt/conda
COPY --from=ebi-validator /opt/ebi-root/envs/ebi-validator /opt/ebi
ENV PATH="/opt/venv/bin:/opt/conda/bin:${PATH}" LD_LIBRARY_PATH="/opt/conda/lib"

# Resolve the application dependency graph only from the committed uv lock.
# The lock manager itself is pinned and removed from the final runtime image.
COPY pyproject.toml uv.lock ./
RUN set -eux \
    && printf '%s\n' "deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian/${DEBIAN_SNAPSHOT_TIMESTAMP}/ trixie main" > /etc/apt/sources.list \
    && printf '%s\n' "deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian/${DEBIAN_SNAPSHOT_TIMESTAMP}/ trixie-updates main" >> /etc/apt/sources.list \
    && printf '%s\n' "deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT_TIMESTAMP}/ trixie-security main" >> /etc/apt/sources.list \
    && rm -f /etc/apt/sources.list.d/debian.sources \
    && apt_update_succeeded=0 \
    && for attempt in 1 2 3 4 5; do \
        if apt-get -o Acquire::Check-Valid-Until=false -o Acquire::http::Timeout=60 -o Acquire::https::Timeout=60 -o Acquire::Retries=2 -o APT::Update::Error-Mode=any update; then \
            apt_update_succeeded=1; \
            break; \
        fi; \
        sleep "$((attempt * 10))"; \
    done \
    && test "$apt_update_succeeded" = 1 \
    && apt-get install -y --no-install-recommends ca-certificates libcairo2 libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info fonts-noto-core postgresql-client \
    && test -s /etc/ssl/certs/ca-certificates.crt \
    && python -c 'import os, ssl; p=ssl.get_default_verify_paths(); expected=os.environ["SSL_CERT_FILE"]; assert p.cafile == expected, f"Python TLS CA file is {p.cafile}, expected {expected}"; assert os.path.isdir(os.environ["SSL_CERT_DIR"])' \
    && rm -rf /var/lib/apt/lists/* \
    && python -c 'import hashlib, os, urllib.request; version=os.environ["UV_VERSION"]; expected=os.environ["UV_ARCHIVE_SHA256"]; url=f"https://github.com/astral-sh/uv/releases/download/{version}/uv-x86_64-unknown-linux-gnu.tar.gz"; data=urllib.request.urlopen(url, timeout=60).read(); actual=hashlib.sha256(data).hexdigest(); print("uv archive SHA-256:", actual); assert actual == expected, f"uv archive SHA-256 mismatch: {actual}"; open("/tmp/uv.tar.gz","wb").write(data)' \
    && tar -xzf /tmp/uv.tar.gz -C /tmp \
    && install -m 0755 /tmp/uv-x86_64-unknown-linux-gnu/uv /usr/local/bin/uv \
    && rm -rf /tmp/uv.tar.gz /tmp/uv-x86_64-unknown-linux-gnu \
    && test "$(uv --version)" = "uv ${UV_VERSION}" \
    && lock_sha_before="$(sha256sum uv.lock | cut -d ' ' -f1)" \
    && uv lock --check \
    && uv sync --python /usr/local/bin/python --locked --no-dev --no-install-project \
    && test "$lock_sha_before" = "$(sha256sum uv.lock | cut -d ' ' -f1)"

COPY backend ./backend
COPY alembic.ini ./
COPY migrations ./migrations
COPY workflows ./workflows
COPY configs ./configs
COPY scripts ./scripts

RUN lock_sha_before="$(sha256sum uv.lock | cut -d ' ' -f1)" \
    && uv sync --python /usr/local/bin/python --locked --no-dev --no-editable \
    && test "$lock_sha_before" = "$(sha256sum uv.lock | cut -d ' ' -f1)" \
    && python -c "import redis; import kombu.transport.redis; import backend.app" \
    && test "$(bcftools --version | head -n1)" = "bcftools ${BCFTOOLS_VERSION}" \
    && test "$(bcftools --version | sed -n '2s/.*htslib //p')" = "${HTSLIB_VERSION}" \
    && test "$(LD_LIBRARY_PATH=/opt/ebi/lib /opt/ebi/bin/vcf_validator --version)" = "vcf_validator version ${EBI_VCF_VALIDATOR_VERSION}" \
    && test "$(LD_LIBRARY_PATH=/opt/ebi/lib /opt/ebi/bin/vcf_assembly_checker --version)" = "vcf-assembly-checker version ${EBI_VCF_VALIDATOR_VERSION}" \
    && rm -f /usr/local/bin/uv

RUN chmod +x scripts/start_api_with_worker.sh

USER 10001:10001

CMD ["./scripts/start_api_with_worker.sh"]
