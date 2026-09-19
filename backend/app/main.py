from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import settings
from backend.app.auth.principal import get_current_principal
from backend.app.api.v1 import (
    cases_router, artifacts_router, analyses_router, variants_router,
    populations_router, review_router, reports_router, audit_router,
    health_router, evidence_router, acmg_router,
    auth_router,
)
from backend.app.api.v1.phenotypes import router as phenotypes_router
from backend.app.api.v1.evidence_context import router as evidence_context_router
from backend.app.api.v1.clingen import router as clingen_router
from backend.app.api.v1.variant_reports import router as variant_reports_router
from backend.app.api.v1.pedigree import router as pedigree_router
from backend.app.api.v1.quality import router as quality_router
from backend.app.api.v1.clinical_followup import router as clinical_followup_router

app = FastAPI(title=f"{settings.app_name} Variant API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_origin,
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
app.include_router(clingen_router, prefix="/api/v1", dependencies=secured)


@app.get("/")
def root():
    return {
        "platform": "SIRALOOM",
        "service": "SIRALOOM Variant",
        "phase": "1",
        "status": "development",
    }


app.include_router(variant_reports_router, prefix="/api/v1", dependencies=secured)
app.include_router(phenotypes_router, prefix="/api/v1", dependencies=secured)
app.include_router(evidence_context_router, prefix="/api/v1", dependencies=secured)

app.include_router(pedigree_router, prefix="/api/v1", dependencies=secured)

app.include_router(quality_router, prefix="/api/v1", dependencies=secured)
app.include_router(clinical_followup_router, prefix="/api/v1", dependencies=secured)
