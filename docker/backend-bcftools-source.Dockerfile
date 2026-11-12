ARG BCFTOOLS_BUILD_LOCK_FILE
ARG BCFTOOLS_PROFILE_ID
ARG BCFTOOLS_VERSION
ARG HTSLIB_VERSION
ARG BCFTOOLS_WORKER_QUEUE
ARG BCFTOOLS_PLATFORM=linux-64
ARG BCFTOOLS_BUILDER_IMAGE=mambaorg/micromamba:2.3.1@sha256:6113627f42f39d065f116b8649e3f699ed2bbe076a58b64ae50fafb4acb8aaf3
ARG BCFTOOLS_BASE_IMAGE=python:3.12-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ARG DEBIAN_SNAPSHOT_TIMESTAMP=20261105T000000Z
ARG UV_VERSION=0.10.0
ARG UV_ARCHIVE_SHA256_X86_64=230e328948c92dd1ebad83949c4d56e83813dfe9c6362a4c519e6a227973f1ae
ARG UV_ARCHIVE_SHA256_AARCH64=c300afd5f2d31df039fe6a26a2d68a76b62832098c272a43e1e74ab9efd4fbd7

FROM ${BCFTOOLS_BUILDER_IMAGE} AS bcftools-source-build
ARG BCFTOOLS_BUILD_LOCK_FILE
ARG BCFTOOLS_PROFILE_ID
ARG BCFTOOLS_VERSION
ARG HTSLIB_VERSION
ARG BCFTOOLS_PLATFORM
ENV MAMBA_ROOT_PREFIX=/tmp/build-env
COPY --chown=$MAMBA_USER:$MAMBA_USER ${BCFTOOLS_BUILD_LOCK_FILE} /tmp/bcftools-build-explicit.lock
RUN case "$(uname -m):${BCFTOOLS_PLATFORM}" in x86_64:linux-64|aarch64:linux-aarch64) ;; *) echo "No BCFtools source-build lock for architecture $(uname -m) and platform ${BCFTOOLS_PLATFORM}." >&2; exit 1 ;; esac \
    && grep -Fqx "# platform: ${BCFTOOLS_PLATFORM}" /tmp/bcftools-build-explicit.lock \
    && micromamba create --yes --name bcftools-build --file /tmp/bcftools-build-explicit.lock \
    && micromamba clean --all --yes
COPY configs/bioinformatics/toolchain-profiles.v1.json /tmp/toolchain-profiles.v1.json
COPY scripts/build_bcftools_from_profile.sh /tmp/build_bcftools_from_profile.sh
RUN micromamba run --name bcftools-build env \
    BCFTOOLS_PROFILE_ID="${BCFTOOLS_PROFILE_ID}" \
    BCFTOOLS_VERSION="${BCFTOOLS_VERSION}" \
    HTSLIB_VERSION="${HTSLIB_VERSION}" \
    BCFTOOLS_PROFILE_REGISTRY=/tmp/toolchain-profiles.v1.json \
    BCFTOOLS_PREFIX=/opt/conda BCFTOOLS_DESTDIR=/tmp/bcftools-runtime \
    bash /tmp/build_bcftools_from_profile.sh

# Keep the runtime base explicit and stable. The selected compiler toolchain
# and its headers never enter the runtime image.
FROM ${BCFTOOLS_BASE_IMAGE}
ARG DEBIAN_SNAPSHOT_TIMESTAMP
ARG UV_VERSION
ARG UV_ARCHIVE_SHA256_X86_64
ARG UV_ARCHIVE_SHA256_AARCH64
ARG BCFTOOLS_PLATFORM
ARG BCFTOOLS_PROFILE_ID
ARG BCFTOOLS_VERSION
ARG HTSLIB_VERSION
ARG BCFTOOLS_WORKER_QUEUE
ENV BCFTOOLS_PROFILE_ID=${BCFTOOLS_PROFILE_ID} \
    BCFTOOLS_VERSION=${BCFTOOLS_VERSION} \
    HTSLIB_VERSION=${HTSLIB_VERSION} \
    BCFTOOLS_EXECUTABLE=/opt/conda/bin/bcftools \
    CELERY_QUEUES=${BCFTOOLS_WORKER_QUEUE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_PROGRESS=1
# The official Python image may use /usr/local/ssl/cert.pem by default;
# explicitly point Python/OpenSSL at Debian's managed trust store.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt SSL_CERT_DIR=/etc/ssl/certs
WORKDIR /app

RUN case "$(uname -m):${BCFTOOLS_PLATFORM}" in x86_64:linux-64|aarch64:linux-aarch64) ;; *) echo "No BCFtools runtime profile for architecture $(uname -m) and platform ${BCFTOOLS_PLATFORM}." >&2; exit 1 ;; esac \
    && groupadd --system --gid 10001 siraloom \
    && useradd --system --uid 10001 --gid siraloom --create-home \
        --home-dir /home/siraloom --shell /usr/sbin/nologin siraloom \
    && mkdir -p /data/siraloom/artifacts /data/siraloom/resource-cache \
        /data/siraloom/scratch /data/siraloom/beat /data/references \
    && chown -R 10001:10001 /data/siraloom
ENV HOME=/home/siraloom SIRALOOM_CONFIG_ROOT=/app

COPY --from=bcftools-source-build /tmp/bcftools-runtime/opt/conda /opt/conda
ENV PATH="/opt/venv/bin:/opt/conda/bin:${PATH}" LD_LIBRARY_PATH="/opt/conda/lib"

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
    && case "$(uname -m)" in x86_64) uv_target=x86_64-unknown-linux-gnu; uv_sha="${UV_ARCHIVE_SHA256_X86_64}" ;; aarch64) uv_target=aarch64-unknown-linux-gnu; uv_sha="${UV_ARCHIVE_SHA256_AARCH64}" ;; *) echo "Unsupported uv architecture: $(uname -m)" >&2; exit 1 ;; esac \
    && UV_TARGET="$uv_target" UV_ARCHIVE_SHA256="$uv_sha" python -c 'import hashlib, os, urllib.request; version=os.environ["UV_VERSION"]; target=os.environ["UV_TARGET"]; expected=os.environ["UV_ARCHIVE_SHA256"]; url=f"https://github.com/astral-sh/uv/releases/download/{version}/uv-{target}.tar.gz"; data=urllib.request.urlopen(url, timeout=60).read(); actual=hashlib.sha256(data).hexdigest(); print("uv archive SHA-256:", actual); assert actual == expected, f"uv archive SHA-256 mismatch: {actual}"; open("/tmp/uv.tar.gz","wb").write(data)' \
    && tar -xzf /tmp/uv.tar.gz -C /tmp \
    && install -m 0755 "/tmp/uv-${uv_target}/uv" /usr/local/bin/uv \
    && rm -rf /tmp/uv.tar.gz "/tmp/uv-${uv_target}" \
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
    && rm -f /usr/local/bin/uv

RUN chmod +x scripts/start_api_with_worker.sh
USER 10001:10001
CMD ["./scripts/start_api_with_worker.sh"]
