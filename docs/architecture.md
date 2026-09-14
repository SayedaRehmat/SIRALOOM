# SIRALOOM Phase 1 architecture

SIRALOOM separates a public Next.js site, an authenticated Next.js application, FastAPI business/scientific APIs, Firebase control-plane services, and durable scientific workers. The browser never runs long-running genomic analysis.

The existing FastAPI domain model and Alembic schema remain authoritative for Case, Analysis, Artifact, workflow, evidence, ACMG, review, reports, and audit history. Firebase Auth supplies the verified user identity. FastAPI verifies each ID token and resolves an active organization membership on the server before tenant-scoped API access.

Firebase client configuration is public web configuration only. Firebase Admin credentials remain server-only via Application Default Credentials or `FIREBASE_CREDENTIALS_PATH`.

Artifact storage paths use `organizations/{organizationId}/cases/{caseId}/artifacts/{artifactId}/...`; reports use the analogous reports path. Local file-backed storage remains the development adapter pending the Cloud Storage adapter milestone.
