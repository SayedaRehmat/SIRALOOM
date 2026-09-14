from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.auth.principal import Principal, get_current_principal
from backend.app.auth.authorization import REVIEW_ROLES, get_accessible_analysis, require_role
from sqlalchemy import func, select

from backend.app.infrastructure.db.models import ACMGAssessment, Annotation, Classification, Evidence, PopulationObservation, User, Variant, ReportabilityDecision
from backend.app.domain.review import ClassificationReviewRequest, CriterionReviewRequest, ReviewResponse
from backend.app.infrastructure.db.session import get_db
from backend.app.review.service import (
    ReviewAuthorizationError,
    ReviewConflictError,
    ReviewError,
    ReviewMutation,
    approve_classification,
    get_review_bundle,
    request_more_evidence,
    start_review,
    review_criterion,
)

router = APIRouter(tags=["review"])


def _reviewer(db: Session, principal: Principal):
    require_role(principal, REVIEW_ROLES)
    user = db.get(User, principal.user_id)
    if not user: raise HTTPException(status_code=403, detail="Authenticated SIRALOOM user is not provisioned")
    return user




@router.get("/analyses/{analysis_id}/review-queue")
def review_queue(
    analysis_id: UUID,
    status: str | None = Query(default=None),
    classification: str | None = Query(default=None),
    chromosome: str | None = Query(default=None),
    reportability: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Tenant-scoped, read-only interpretation queue for an analysis."""
    # Direct Python callers/tests do not receive FastAPI's resolved defaults.
    if not isinstance(status, str): status = None
    if not isinstance(classification, str): classification = None
    if not isinstance(chromosome, str): chromosome = None
    if not isinstance(reportability, str): reportability = None
    if not isinstance(limit, int): limit = 100
    if not isinstance(offset, int): offset = 0
    analysis = get_accessible_analysis(analysis_id, db, principal)
    latest_version = (
        select(Classification.variant_id, func.max(Classification.version).label("max_version"))
        .where(Classification.analysis_id == analysis_id)
        .group_by(Classification.variant_id)
        .subquery()
    )
    stmt = (
        select(Variant, Classification)
        .join(Annotation, Annotation.variant_id == Variant.id)
        .join(latest_version, latest_version.c.variant_id == Variant.id)
        .join(
            Classification,
            (Classification.variant_id == latest_version.c.variant_id)
            & (Classification.analysis_id == analysis_id)
            & (Classification.version == latest_version.c.max_version),
        )
        .where(Annotation.analysis_id == analysis_id)
        .distinct()
    )
    if status:
        stmt = stmt.where(Classification.review_status == status.upper())
    if classification:
        stmt = stmt.where(Classification.result == classification.upper())
    if chromosome:
        stmt = stmt.where(Variant.chromosome == chromosome.strip())

    query = stmt.order_by(Variant.chromosome.asc(), Variant.position.asc())
    # Reportability is a separate versioned domain object. Apply the filter
    # after selecting the latest classification to keep the queue portable.
    if reportability:
        rows = list(db.execute(query).all())
        filtered = []
        for variant, cls in rows:
            decision = db.scalar(select(ReportabilityDecision).where(ReportabilityDecision.analysis_id == analysis_id, ReportabilityDecision.variant_id == variant.id).order_by(ReportabilityDecision.version.desc()))
            value = decision.disposition if decision else "NOT_DETERMINED"
            if value.upper() == reportability.upper():
                filtered.append((variant, cls))
        total = len(filtered)
        rows = filtered[offset:offset + limit]
    else:
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int(db.scalar(count_stmt) or 0)
        rows = list(db.execute(query.offset(offset).limit(limit)).all())

    items = []
    for variant, cls in rows:
        criteria_count = int(db.scalar(select(func.count(ACMGAssessment.id)).where(ACMGAssessment.analysis_id == analysis_id, ACMGAssessment.variant_id == variant.id)) or 0)
        evidence_count = int(db.scalar(select(func.count(Evidence.id)).where(Evidence.analysis_id == analysis_id, Evidence.variant_id == variant.id)) or 0)
        population_count = int(db.scalar(select(func.count(PopulationObservation.id)).where(PopulationObservation.analysis_id == analysis_id, PopulationObservation.variant_id == variant.id)) or 0)
        annotation = db.scalar(
            select(Annotation)
            .where(Annotation.analysis_id == analysis_id, Annotation.variant_id == variant.id)
            .order_by(Annotation.created_at.desc())
        )
        normalized = ((annotation.payload or {}).get("normalized") or {}) if annotation else {}
        gene = normalized.get("gene") or normalized.get("gene_symbol") or normalized.get("symbol")
        consequence = normalized.get("consequence") or normalized.get("most_severe_consequence")
        clinvar = normalized.get("clinvar") if isinstance(normalized.get("clinvar"), dict) else None
        clinvar_significance = normalized.get("clinvar_significance") or (clinvar or {}).get("significance")
        decision = db.scalar(select(ReportabilityDecision).where(ReportabilityDecision.analysis_id == analysis_id, ReportabilityDecision.variant_id == variant.id).order_by(ReportabilityDecision.version.desc()))
        reportability_value = decision.disposition if decision else "NOT_DETERMINED"
        items.append({
            "variant_id": str(variant.id),
            "analysis_id": str(analysis.id),
            "genome_build": variant.genome_build,
            "chromosome": variant.chromosome,
            "position": variant.position,
            "reference": variant.reference,
            "alternate": variant.alternate,
            "canonical_key": variant.canonical_key,
            "identifiers": variant.identifiers or {},
            "gene": str(gene) if gene is not None else None,
            "consequence": str(consequence) if consequence is not None else None,
            "clinvar_significance": str(clinvar_significance) if clinvar_significance is not None else None,
            "classification": cls.result,
            "classification_state": cls.state,
            "review_status": cls.review_status,
            "review_version": cls.review_version,
            "classification_version": cls.version,
            "reportability": reportability_value,
            "criteria_count": criteria_count,
            "evidence_count": evidence_count,
            "population_count": population_count,
            "priority": decision.priority_score if decision else None,
            "priority_band": decision.priority_band if decision else None,
            "reportability_status": decision.status if decision else "NOT_DETERMINED",
            "reportability_version": decision.version if decision else None,
        })
    return {"analysis_id": str(analysis.id), "case_id": str(analysis.case_id), "count": len(items), "total": total, "offset": offset, "limit": limit, "items": items}


@router.get("/analyses/{analysis_id}/variants/{variant_id}/review", response_model=ReviewResponse)
def get_review(analysis_id: UUID, variant_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    get_accessible_analysis(analysis_id, db, principal)
    try:
        return get_review_bundle(db, analysis_id=analysis_id, variant_id=variant_id)
    except ReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/analyses/{analysis_id}/variants/{variant_id}/review/start")
def start(analysis_id: UUID, variant_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    get_accessible_analysis(analysis_id, db, principal); reviewer = _reviewer(db, principal)
    try:
        classification = start_review(db, analysis_id=analysis_id, variant_id=variant_id, reviewer=reviewer)
        db.commit()
        return {
            "classification_id": str(classification.id),
            "review_status": classification.review_status,
            "review_version": classification.review_version,
        }
    except ReviewAuthorizationError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ReviewError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/analyses/{analysis_id}/variants/{variant_id}/acmg/{criterion}/review")
def review(
    analysis_id: UUID,
    variant_id: UUID,
    criterion: str,
    payload: CriterionReviewRequest,
    db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal),
):
    get_accessible_analysis(analysis_id, db, principal); reviewer = _reviewer(db, principal)
    try:
        assessment = review_criterion(
            db,
            analysis_id=analysis_id,
            variant_id=variant_id,
            criterion=criterion,
            mutation=ReviewMutation(
                decision=payload.decision,
                strength=payload.strength,
                reason=payload.reason,
                evidence_ids=tuple(UUID(x) for x in payload.evidence_ids),
                expected_version=payload.expected_version,
            ),
            reviewer=reviewer,
        )
        db.commit()
        return {
            "assessment_id": str(assessment.id),
            "criterion": assessment.criterion,
            "state": assessment.state,
            "review_version": assessment.review_version,
            "reviewed_assessment": assessment.reviewed_assessment,
        }
    except ReviewConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewAuthorizationError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ReviewError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/analyses/{analysis_id}/variants/{variant_id}/review/approve")
def approve(
    analysis_id: UUID,
    variant_id: UUID,
    payload: ClassificationReviewRequest,
    db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal),
):
    get_accessible_analysis(analysis_id, db, principal); reviewer = _reviewer(db, principal)
    try:
        classification = approve_classification(
            db,
            analysis_id=analysis_id,
            variant_id=variant_id,
            reviewer=reviewer,
            expected_version=payload.expected_version,
            reason=payload.reason,
        )
        db.commit()
        return {
            "classification_id": str(classification.id),
            "version": classification.version,
            "result": classification.result,
            "state": classification.state,
            "review_status": classification.review_status,
            "review_version": classification.review_version,
            "supersedes_classification_id": str(classification.supersedes_classification_id) if classification.supersedes_classification_id else None,
        }
    except ReviewConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewAuthorizationError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ReviewError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/analyses/{analysis_id}/variants/{variant_id}/review/more-evidence")
def more_evidence(
    analysis_id: UUID,
    variant_id: UUID,
    payload: ClassificationReviewRequest,
    db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal),
):
    get_accessible_analysis(analysis_id, db, principal); reviewer = _reviewer(db, principal)
    try:
        classification = request_more_evidence(
            db,
            analysis_id=analysis_id,
            variant_id=variant_id,
            reviewer=reviewer,
            expected_version=payload.expected_version,
            reason=payload.reason,
        )
        db.commit()
        return {
            "classification_id": str(classification.id),
            "version": classification.version,
            "state": classification.state,
            "review_status": classification.review_status,
            "review_version": classification.review_version,
        }
    except ReviewConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewAuthorizationError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ReviewError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
