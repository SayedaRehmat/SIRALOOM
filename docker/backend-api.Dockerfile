ARG API_BASE_IMAGE=python:3.12-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ARG DEBIAN_SNAPSHOT_TIMESTAMP=20261105T000000Z
ARG UV_VERSION=0.10.0
ARG UV_ARCHIVE_SHA256=230e328948c92dd1ebad83949c4d56e83813dfe9c6362a4c519e6a227973f1ae

FROM ${API_BASE_IMAGE}

ARG DEBIAN_SNAPSHOT_TIMESTAMP
ARG UV_VERSION
ARG UV_ARCHIVE_SHA256

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_PROGRESS=1
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt SSL_CERT_DIR=/etc/ssl/certs
ENV PATH="/opt/venv/bin:${PATH}"
WORKDIR /app

# The API and scheduler are deliberately tool-neutral. Scientific executables
# belong only in separately qualified worker images.
RUN test "$(uname -m)" = "x86_64" || { echo "This API image is currently qualified only for Linux AMD64 (x86_64)." >&2; exit 1; } \
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
    && ! command -v bcftools \
    && rm -f /usr/local/bin/uv

USER 10001:10001
CMD ["./scripts/start_api.sh"]
