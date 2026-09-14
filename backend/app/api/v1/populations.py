from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.db.models import PopulationObservation, Resource
from backend.app.domain.schemas import PopulationQueryRequest

router = APIRouter(tags=["population"])

@router.post("/populations/query")
def query(payload: PopulationQueryRequest, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PopulationObservation).where(
            PopulationObservation.analysis_id == payload.analysis_id,
            PopulationObservation.variant_id.in_(payload.variant_ids),
        )
    ).all()
    filtered = [r for r in rows if r.population_code in set(payload.requested_populations)]
    return {"status": "COMPLETED", "observations": [{"variant_id": str(r.variant_id), "population": r.population_code, "label": r.population_label, "availability": r.availability, "af": r.allele_frequency, "ac": r.allele_count, "an": r.allele_number} for r in filtered]}

@router.get("/population-resources")
def resources(db: Session = Depends(get_db)):
    rows = db.scalars(select(Resource)).all()
    return [{"resource_id": str(r.id), "name": r.name, "provider": r.provider, "version": r.version, "genome_build": r.genome_build, "access_method": r.access_method, "status": r.status, "population_definition": r.population_definition} for r in rows]
