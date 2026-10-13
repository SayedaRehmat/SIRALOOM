from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import settings
from backend.app.auth.principal import get_current_principal
from backend.app.api.v1 import (
    cases_router, artifacts_router, analyses_router, variants_router,
    populations_router, review_router, reports_router, audit_router,
    health_router, evidence_router, acmg_router,
    auth_router, resources_router, storage_router, workflow_router,
)
from backend.app.api.v1.phenotypes import router as phenotypes_router
from backend.app.api.v1.evidence_context import router as evidence_context_router
from backend.app.api.v1.clingen import router as clingen_router
from backend.app.api.v1.variant_reports import router as variant_reports_router
from backend.app.api.v1.pedigree import router as pedigree_router
from backend.app.api.v1.quality import router as quality_router
from backend.app.api.v1.clinical_followup import router as clinical_followup_router
from backend.app.api.v1.reanalysis import router as reanalysis_router
from backend.app.api.v1.membership import router as membership_router

app = FastAPI(title=f"{settings.app_name} Variant API", version="0.1.0")


@app.on_event("startup")
def enforce_production_configuration() -> None:
    """Refuse to serve traffic when mandatory production controls are absent."""
    if settings.app_env.strip().lower() != "production":
        return

    problems: list[str] = []
    if not settings.firebase_auth_required:
        problems.append("FIREBASE_AUTH_REQUIRED must be true")
    if not settings.firebase_project_id:
        problems.append("FIREBASE_PROJECT_ID must be configured")
    if not settings.firebase_credentials_path:
        problems.append("FIREBASE_CREDENTIALS_PATH must be configured")
    elif not Path(settings.firebase_credentials_path).is_file():
        problems.append("Firebase Admin credentials file is not readable at the configured path")
    if not settings.public_base_url.lower().startswith("https://"):
        problems.append("PUBLIC_BASE_URL must use HTTPS")
    if not settings.frontend_origin.lower().startswith("https://"):
        problems.append("FRONTEND_ORIGIN must use HTTPS")
    if not settings.storage_capacity_preflight_enabled:
        problems.append("STORAGE_CAPACITY_PREFLIGHT_ENABLED must be true")

    if problems:
        raise RuntimeError(
            "SIRALOOM production startup blocked by incomplete security/deployment configuration: "
            + "; ".join(problems)
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_origin.rstrip("/"),
        "https://siraloom.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
secured = [Depends(get_current_principal)]
app.include_router(cases_router, prefix="/api/v1", dependencies=secured)
app.include_router(artifacts_router, prefix="/api/v1", dependencies=secured)
app.include_router(analyses_router, prefix="/api/v1", dependencies=secured)
app.include_router(variants_router, prefix="/api/v1", dependencies=secured)
app.include_router(populations_router, prefix="/api/v1", dependencies=secured)
app.include_router(review_router, prefix="/api/v1", dependencies=secured)
app.include_router(reports_router, prefix="/api/v1", dependencies=secured)
app.include_router(audit_router, prefix="/api/v1", dependencies=secured)
app.include_router(evidence_router, prefix="/api/v1", dependencies=secured)
app.include_router(acmg_router, prefix="/api/v1", dependencies=secured)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(membership_router, prefix="/api/v1")
app.include_router(clingen_router, prefix="/api/v1", dependencies=secured)


@app.get("/")
def root():
    return {
        "platform": "SIRALOOM",
        "service": "SIRALOOM Variant",
        "phase": "1",
        "status": settings.app_env,
    }


app.include_router(variant_reports_router, prefix="/api/v1", dependencies=secured)
app.include_router(phenotypes_router, prefix="/api/v1", dependencies=secured)
app.include_router(evidence_context_router, prefix="/api/v1", dependencies=secured)

app.include_router(pedigree_router, prefix="/api/v1", dependencies=secured)

app.include_router(quality_router, prefix="/api/v1", dependencies=secured)
app.include_router(clinical_followup_router, prefix="/api/v1", dependencies=secured)

app.include_router(reanalysis_router, prefix="/api/v1", dependencies=secured)
app.include_router(resources_router, prefix="/api/v1", dependencies=secured)

app.include_router(storage_router, prefix="/api/v1", dependencies=secured)
app.include_router(workflow_router, prefix="/api/v1", dependencies=secured)
