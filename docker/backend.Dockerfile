FROM mambaorg/micromamba:2.3.1 AS bcftools

ENV MAMBA_ROOT_PREFIX=/opt/conda
COPY --chown=$MAMBA_USER:$MAMBA_USER configs/bioinformatics/bcftools-environment.yml /tmp/bcftools-environment.yml
RUN micromamba install --yes --name base --file /tmp/bcftools-environment.yml \
    && micromamba clean --all --yes

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY --from=bcftools /opt/conda /opt/conda
ENV PATH="/opt/conda/bin:${PATH}"

COPY pyproject.toml ./
COPY backend ./backend
COPY alembic.ini ./
COPY migrations ./migrations
COPY workflows ./workflows
COPY configs ./configs
COPY scripts ./scripts
RUN apt-get update \
    && apt-get install -y --no-install-recommends libcairo2 libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info fonts-noto-core postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -e . \
    && test "$(bcftools --version | head -n1)" = "bcftools 1.19"

RUN chmod +x scripts/start_api_with_worker.sh

CMD ["./scripts/start_api_with_worker.sh"]
