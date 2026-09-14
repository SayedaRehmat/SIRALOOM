from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.acmg.engine import ACMGEngine, CriterionAssessment
from backend.app.acmg.rules import CriterionDirection
from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.db.models import ACMGAssessment, Analysis, Classification, Variant
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.auth.authorization import REVIEW_ROLES, get_accessible_analysis, require_role
from backend.app.infrastructure.audit.service import AuditService

router = APIRouter(tags=["acmg"])

class ACMGCriterionInput(BaseModel):
    criterion: str = Field(pattern=r"^(PVS1|PS1|PS2|PS3|PS4|PM1|PM2|PM3|PM4|PM5|PM6|PP1|PP2|PP3|PP4|PP5|BA1|BS1|BS2|BS3|BS4|BP1|BP2|BP3|BP4|BP5|BP6|BP7)$")
    strength: str
    direction: Literal["PATHOGENIC", "BENIGN"]
    evidence_ids: list[UUID] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    metadata: dict = Field(default_factory=dict)

class ACMGAssessRequest(BaseModel):
    variant_id: UUID
    criteria: list[ACMGCriterionInput]

@router.post("/analyses/{analysis_id}/variants/{variant_id}/acmg/assess")
def assess(analysis_id: UUID, variant_id: UUID, payload: ACMGAssessRequest, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    if payload.variant_id != variant_id:
        raise HTTPException(status_code=400, detail="Payload variant_id does not match path variant_id")
    analysis = get_accessible_analysis(analysis_id, db, principal); require_role(principal, REVIEW_ROLES)
    variant = db.get(Variant, variant_id)
    if not analysis or not variant:
        raise HTTPException(status_code=404, detail="Analysis or variant not found")
    engine = ACMGEngine()
    try:
        assessments = [
            engine.build_assessment_from_explicit_evidence(
                criterion=x.criterion,
                strength=x.strength,
                direction=x.direction,
                evidence_ids=[str(e) for e in x.evidence_ids],
                reason=x.reason,
                metadata=x.metadata,
            )
            for x in payload.criteria
        ]
        result = engine.classify(assessments)
        # Persist a complete, versioned assessment snapshot for every supplied criterion.
        for a in result.criteria:
            existing = db.scalar(select(ACMGAssessment).where(ACMGAssessment.variant_id == variant_id, ACMGAssessment.analysis_id == analysis_id, ACMGAssessment.criterion == a.criterion))
            row = existing or ACMGAssessment(id=__import__("uuid").uuid4(), variant_id=variant_id, analysis_id=analysis_id, framework_name=result.framework, framework_version=result.framework_version, specification_provider="SIRALOOM", specification_id=result.profile_id, specification_version=result.profile_version, criterion=a.criterion, state=a.status)
            row.automated_assessment = {"strength": a.strength, "direction": a.direction, "status": a.status, "evidence_ids": list(a.evidence_ids), "reason": a.reason, "metadata": a.metadata}
            row.state = a.status
            db.add(row)

        db.add(Classification(id=__import__("uuid").uuid4(), variant_id=variant_id, analysis_id=analysis_id, framework_name=result.framework, framework_version=result.framework_version, result=result.classification, criterion_ids=[], state=result.state, review_status="PENDING"))
        AuditService(db).record(event_type="ACMG_ASSESSMENT_CREATED", case_id=analysis.case_id, analysis_id=analysis_id, actor_type="SYSTEM", actor_id="siraloom-acmg-engine", subject_type="VARIANT", subject_id=str(variant_id), operation="CREATE", after_state={"classification": result.classification, "state": result.state, "profile_id": result.profile_id, "profile_version": result.profile_version}, reason="Versioned ACMG/AMP 2015 baseline combination assessment")
        db.commit()
        return {
            "analysis_id": str(analysis_id),
            "variant_id": str(payload.variant_id),
            "framework": result.framework,
            "framework_version": result.framework_version,
            "rule_profile": {"id": result.profile_id, "version": result.profile_version},
            "state": result.state,
            "classification": result.classification,
            "rationale": list(result.rationale),
            "criteria": [
                {
                    "criterion": a.criterion,
                    "strength": a.strength,
                    "direction": a.direction,
                    "status": a.status,
                    "evidence_ids": list(a.evidence_ids),
                    "reason": a.reason,
                    "metadata": a.metadata,
                }
                for a in result.criteria
            ],
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

class ACMGAutoAssessRequest(BaseModel):
    gene: str = Field(min_length=1)
    disease: str | None = None


@router.post("/analyses/{analysis_id}/variants/{variant_id}/acmg/auto-assess")
def auto_assess(
    analysis_id: UUID,
    variant_id: UUID,
    payload: ACMGAutoAssessRequest,
    db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal),
):
    """Run specification-aware ACMG criterion evaluators.

    This endpoint never fabricates a ClinGen specification or promotes automated
    output to a final clinical interpretation. It returns REQUIRES_REVIEW when a
    validated, applicable specification cannot be selected or when the selected
    specification requires an unsupported combination method.
    """
    from backend.app.acmg.assessment_service import ACMGSpecificationAssessmentService
    from backend.app.infrastructure.db.models import Annotation, PopulationObservation, Resource

    analysis = get_accessible_analysis(analysis_id, db, principal); require_role(principal, REVIEW_ROLES)
    variant = db.get(Variant, variant_id)
    if not analysis or analysis.id != analysis_id or not variant:
        raise HTTPException(status_code=404, detail="Analysis or variant not found")

    annotation = db.scalar(
        select(Annotation).where(
            Annotation.analysis_id == analysis_id,
            Annotation.variant_id == variant_id,
        ).order_by(Annotation.created_at.desc())
    )
    if annotation is None:
        raise HTTPException(status_code=409, detail="No annotation is available for this variant in this analysis")

    population_rows = db.scalars(
        select(PopulationObservation).where(
            PopulationObservation.analysis_id == analysis_id,
            PopulationObservation.variant_id == variant_id,
        )
    ).all()
    resource_rows = {
        r.id: r for r in db.scalars(select(Resource)).all()
    }

    service = ACMGSpecificationAssessmentService()
    result = service.assess_variant(
        db,
        analysis=analysis,
        variant=variant,
        annotation=annotation,
        population_rows=population_rows,
        resource_rows=resource_rows,
        gene=payload.gene,
        disease=payload.disease,
    )

    if result.binding.status != "SELECTED":
        return {
            "status": result.status,
            "binding": {
                "status": result.binding.status,
                "specification_id": result.binding.specification_id,
                "specification_version": result.binding.specification_version,
                "reason": result.binding.reason,
            },
            "criteria": [],
            "classification": None,
        }

    service.persist(db, analysis=analysis, variant=variant, result=result)
    db.commit()

    AuditService(db).record(
        event_type="ACMG_SPECIFICATION_ASSESSMENT_COMPLETED",
        case_id=analysis.case_id,
        analysis_id=analysis.id,
        actor_type="SERVICE",
        actor_id="siraloom-acmg-specification-engine",
        subject_type="VARIANT",
        subject_id=str(variant_id),
        operation="ASSESS",
        after_state={
            "specification_id": result.binding.specification_id,
            "specification_version": result.binding.specification_version,
            "status": result.status,
            "classification": result.classification.classification if result.classification else None,
        },
        reason=result.binding.reason,
    )
    db.commit()

    return {
        "status": result.status,
        "binding": {
            "status": result.binding.status,
            "specification_id": result.binding.specification_id,
            "specification_version": result.binding.specification_version,
            "reason": result.binding.reason,
        },
        "criteria": [
            {
                "criterion": x.criterion,
                "applicable": x.applicable,
                "strength": x.strength,
                "direction": x.direction,
                "status": x.status,
                "reason": x.reason,
                "evidence_ids": list(x.evidence_ids),
                "metadata": x.metadata or {},
            }
            for x in result.evaluator_results
        ],
        "classification": (
            {
                "result": result.classification.classification,
                "state": result.classification.state,
                "framework": result.classification.framework,
                "framework_version": result.classification.framework_version,
                "profile_id": result.classification.profile_id,
                "profile_version": result.classification.profile_version,
                "rationale": list(result.classification.rationale),
            }
            if result.classification
            else None
        ),
    }
