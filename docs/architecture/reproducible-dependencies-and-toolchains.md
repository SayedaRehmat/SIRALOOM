# Reproducible software dependencies and scientific toolchains

## Two independent version domains

SIRALOOM must not use one global dependency lock for both its application and its scientific tools.

1. **Platform/application environment** — Python, FastAPI, SQLAlchemy, Celery, Kombu, redis-py, database drivers and application libraries. These are resolved together in the repository-root `uv.lock`. CI and the production backend image must install from this exact lock with `uv sync --locked`.
2. **Scientific execution environments** — BCFtools/HTSlib, VEP, callers, reference assets and other bioinformatics tools. These are independently versioned execution profiles. A new tool version is added and qualified as a new profile; it must not upgrade or downgrade the platform environment.

The Python lock is cross-platform and records exact package versions, source locations and artifact hashes. `pyproject.toml` remains the human-maintained compatibility policy; `uv.lock` is the resolved deployment/test graph. The lock manager is pinned by `tool.uv.required-version` and must be upgraded deliberately.

## Required developer and CI commands

- Resolve/update intentionally: `uv lock`
- Reject stale lock metadata: `uv lock --check`
- Install exact project and test dependencies: `uv sync --locked --extra dev`
- Run commands without re-resolving: `uv run --locked ...`

Do not use `pip install -e .`, `pip install -r` with an unpinned file, or an unconstrained dependency install in CI or production Docker builds.

## Production image contract

The backend Docker build copies `pyproject.toml` and `uv.lock` before application source, installs production dependencies from the lock, then installs the application package non-editably from the same lock. The final image does not retain uv as a runtime dependency. API, worker and Beat roles built from this Dockerfile therefore share one Python dependency graph.

A deployed lab must use an immutable image digest, not a mutable tag, and should record that digest with every job. Rebuilding the image is required to apply a dependency-lock update; editing the repository does not update already-running lab containers.

## Redis/Kombu compatibility

The lock resolves Celery, Kombu and redis-py as one dependency graph. CI and the image import Kombu's actual Redis transport, which executes Kombu's own redis-py compatibility guard. This is stronger than checking only that Redis imports or that the Redis server is reachable. PostgreSQL integration tests additionally exercise real Celery/Redis processing and worker-loss recovery.

## Scientific toolchain versioning

Do not add BCFtools, HTSlib, VEP or caller packages to the Python lock. They have native libraries, ABI constraints, reference-resource dependencies and distinct validation requirements. Each qualified toolchain should have:

- a stable profile identifier (tool + version + platform);
- a dedicated environment/container build definition;
- a transitive, platform-specific lock (for example, an explicit Conda lock);
- an immutable image digest;
- tool and reference checksums;
- compatibility and regression evidence;
- provenance recorded per analysis.

The existing BCFtools 1.25/HTSlib 1.25 environment remains the current profile. Additional versions should be added as parallel profiles and qualified independently. The application must select a profile explicitly rather than silently taking whichever executable happens to be on `PATH`.

## Scope and remaining reproducibility work

This change locks the Python package graph and makes CI and the backend image consume it. It does **not** yet make the complete OCI image bit-for-bit reproducible: the Python base image tag, Debian APT repository state, micromamba base image and transitive Conda resolution still need digest/snapshot/explicit-lock treatment. Those belong to the next toolchain-and-image hardening milestone; they must not be represented as already solved by `uv.lock`.
