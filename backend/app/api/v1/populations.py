from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import READ_ROLES, get_accessible_analysis, require_role
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.schemas import PopulationQueryRequest
from backend.app.infrastructure.db.models import PopulationObservation, Resource
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["population"])


@router.post("/populations/query")
def query(
    payload: PopulationQueryRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    get_accessible_analysis(payload.analysis_id, db, principal)
    rows = db.scalars(
        select(PopulationObservation).where(
            PopulationObservation.analysis_id == payload.analysis_id,
            PopulationObservation.variant_id.in_(payload.variant_ids),
        )
    ).all()
    requested = set(payload.requested_populations)
    filtered = [row for row in rows if row.population_code in requested]
    return {
        "status": "COMPLETED",
        "observations": [
            {
                "variant_id": str(row.variant_id),
                "population": row.population_code,
                "label": row.population_label,
                "availability": row.availability,
                "af": row.allele_frequency,
                "ac": row.allele_count,
                "an": row.allele_number,
            }
            for row in filtered
        ],
    }


@router.get("/population-resources")
def resources(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, READ_ROLES)
    query = select(Resource).order_by(Resource.name, Resource.version)
    if principal.role != "platform_admin":
        query = query.where(
            (Resource.organization_id.is_(None))
            | (Resource.organization_id == principal.organization_id)
        )
    rows = db.scalars(query.limit(500)).all()
    return [
        {
            "resource_id": str(row.id),
            "name": row.name,
            "provider": row.provider,
            "version": row.version,
            "genome_build": row.genome_build,
            "access_method": row.access_method,
            "status": row.status,
            "population_definition": row.population_definition,
        }
        for row in rows
    ]
