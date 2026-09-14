# Local development

Copy `.env.example` to `.env` and populate local database, Redis, artifact, and Firebase web settings. Keep `FIREBASE_AUTH_REQUIRED=false` only for isolated development; production must set it to `true`.

Backend dependencies are declared in `pyproject.toml`; install them with a Python 3.11+ environment, then run:

```bash
PYTHONPATH=. DATABASE_URL=sqlite:///./siraloom.db REDIS_URL=redis://localhost:6379/0 pytest -q
```

Install frontend dependencies and build from `frontend`:

```bash
npm install
npm run build
```

For runtime integration, start PostgreSQL and Redis, apply `alembic upgrade head`, run FastAPI and a worker, then run the Next.js app. A Firebase-enabled environment additionally needs a provisioned SIRALOOM user and active organization membership before the API will authorize it.

`GENEBE_ENABLED`, `GENEBE_EMAIL`, and `GENEBE_API_KEY` are server-only environment variables. Leave GeneBe disabled until an authorized deployment secret is configured.
