from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import get_accessible_analysis, get_analysis_variant
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    Annotation,
    Case,
    Classification,
    Evidence,
    PopulationObservation,
    Variant,
)
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["variants"])

@router.get("/variants/{variant_id}")
def get_variant(
    variant_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    analysis_id: UUID | None = None,
):
    analysis_query = (
        select(Annotation.analysis_id)
        .join(Analysis, Annotation.analysis_id == Analysis.id)
        .join(Case, Analysis.case_id == Case.id)
        .where(
            Annotation.variant_id == variant_id,
            Case.organization_id == principal.organization_id,
        )
        .group_by(Annotation.analysis_id)
        .order_by(func.max(Annotation.created_at).desc())
    )
    if analysis_id is not None:
        # The workspace knows its selected analysis; keep details bound to it.
        analysis_query = analysis_query.where(Annotation.analysis_id == analysis_id)
    analysis_ids = db.scalars(analysis_query).all()

    # Variant UUIDs can be shared across analyses. Resolve the newest analysis
    # the caller may actually read; organization membership alone is not enough
    # after case assignments are enabled.
    analysis = None
    v = None
    for candidate_id in analysis_ids:
        try:
            candidate = get_accessible_analysis(candidate_id, db, principal)
            candidate_variant = get_analysis_variant(candidate, variant_id, db)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        analysis = candidate
        v = candidate_variant
        break

    if analysis is None or v is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    aid = analysis.id
    anns = db.scalars(select(Annotation).where(Annotation.variant_id == v.id, Annotation.analysis_id == aid)).all()
    pops = db.scalars(select(PopulationObservation).where(PopulationObservation.variant_id == v.id, PopulationObservation.analysis_id == aid)).all()
    ev = db.scalars(select(Evidence).where(Evidence.variant_id == v.id, Evidence.analysis_id == aid)).all()
    acmg = db.scalars(select(ACMGAssessment).where(ACMGAssessment.variant_id == v.id, ACMGAssessment.analysis_id == aid)).all()
    cls = db.scalars(select(Classification).where(Classification.variant_id == v.id, Classification.analysis_id == aid)).all()
    return {
        "variant": {"id": str(v.id), "genome_build": v.genome_build, "chromosome": v.chromosome, "position": v.position, "reference": v.reference, "alternate": v.alternate, "normalization_status": v.normalization_status, "canonical_key": v.canonical_key, "identifiers": v.identifiers},
        "annotations": [{"id": str(a.id), "provider": a.provider_name, "provider_version": a.provider_version, "resource": a.resource_name, "resource_version": a.resource_version, "payload": a.payload} for a in anns],
        "population": [{"population": p.population_code, "label": p.population_label, "availability": p.availability, "af": p.allele_frequency, "ac": p.allele_count, "an": p.allele_number} for p in pops],
        "evidence": [{"id": str(e.id), "type": e.evidence_type, "statement": e.statement, "direction": e.direction, "source": e.source_name, "source_version": e.source_version, "payload": e.payload} for e in ev],
        "acmg": [{"id": str(a.id), "criterion": a.criterion, "automated": a.automated_assessment, "reviewed": a.reviewed_assessment, "final": a.final_assessment, "state": a.state} for a in acmg],
        "classifications": [{"id": str(c.id), "result": c.result, "state": c.state, "review_status": c.review_status} for c in cls],
    }
