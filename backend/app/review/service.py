from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.enums import ReviewStatus, UserRole
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import ACMGAssessment, Analysis, Classification, Evidence, ReviewAction, User, Variant, Case, PhenotypeObservation, PopulationObservation, ReportabilityDecision, Annotation, PedigreeMember, PedigreeRelationship, SegregationObservation, InheritanceAssessment, TechnicalQCObservation, QCAssessment, Assay


class ReviewError(ValueError):
    pass


class ReviewConflictError(ReviewError):
    pass


class ReviewAuthorizationError(ReviewError):
    pass


@dataclass(frozen=True)
class ReviewMutation:
    decision: str
    strength: str | None
    reason: str
    evidence_ids: tuple[UUID, ...]
    expected_version: int


# OrganizationMembership.role is persisted using the lowercase RBAC role
# vocabulary enforced by backend.app.auth.authorization.REVIEW_ROLES. Keep this
# service-level gate on that same vocabulary so an authorized organization_admin,
# reviewer, clinical_geneticist, or lab_director is not rejected a second time.
_ALLOWED_ROLES = {
    "platform_admin",
    "organization_admin",
    "lab_director",
    "clinical_geneticist",
    "reviewer",
}


def require_reviewer(user: User) -> None:
    if str(user.role) not in {str(x) for x in _ALLOWED_ROLES}:
        raise ReviewAuthorizationError("User role is not authorized to perform interpretation review")
    if str(user.status) != "ACTIVE":
        raise ReviewAuthorizationError("User is not active")


def _evidence_context_dict(evidence: Evidence) -> dict:
    return {
        "id": str(evidence.id),
        "type": evidence.evidence_type,
        "statement": evidence.statement,
        "direction": evidence.direction,
        "source": evidence.source_name,
        "source_version": evidence.source_version,
        "source_record_id": evidence.source_record_id,
        "observation_ids": evidence.observation_ids or [],
        "payload": evidence.payload or {},
        "created_at": evidence.created_at.isoformat(),
    }


def get_review_bundle(db: Session, *, analysis_id: UUID, variant_id: UUID) -> dict:
    analysis = db.get(Analysis, analysis_id)
    if not analysis:
        raise ReviewError("Analysis not found")
    variant = db.get(Variant, variant_id)
    if not variant:
        raise ReviewError("Variant not found")

    assessments = list(db.scalars(
        select(ACMGAssessment)
        .where(ACMGAssessment.analysis_id == analysis_id, ACMGAssessment.variant_id == variant_id)
        .order_by(ACMGAssessment.criterion)
    ))
    classification = db.scalar(
        select(Classification)
        .where(Classification.analysis_id == analysis_id, Classification.variant_id == variant_id)
        .order_by(Classification.version.desc())
    )
    actions = list(db.scalars(
        select(ReviewAction)
        .where(ReviewAction.analysis_id == analysis_id, ReviewAction.variant_id == variant_id)
        .order_by(ReviewAction.sequence_number)
    ))
    case = db.get(Case, analysis.case_id)
    phenotypes = list(db.scalars(
        select(PhenotypeObservation)
        .where(PhenotypeObservation.case_id == analysis.case_id, (PhenotypeObservation.analysis_id == analysis_id) | (PhenotypeObservation.analysis_id.is_(None)))
        .order_by(PhenotypeObservation.created_at, PhenotypeObservation.id)
    ))
    annotations = list(db.scalars(
        select(Annotation).where(Annotation.analysis_id == analysis_id, Annotation.variant_id == variant_id).order_by(Annotation.created_at.desc())
    ))
    population = list(db.scalars(
        select(PopulationObservation).where(PopulationObservation.analysis_id == analysis_id, PopulationObservation.variant_id == variant_id)
    ))
    evidence = list(db.scalars(
        select(Evidence).where(Evidence.analysis_id == analysis_id, Evidence.variant_id == variant_id).order_by(Evidence.created_at.asc(), Evidence.id.asc())
    ))
    qc_observations = list(db.scalars(
        select(TechnicalQCObservation).where(TechnicalQCObservation.analysis_id == analysis_id).order_by(TechnicalQCObservation.created_at)
    ))
    qc_assessments = list(db.scalars(
        select(QCAssessment).where(QCAssessment.analysis_id == analysis_id).order_by(QCAssessment.created_at.desc())
    ))
    assay = db.get(Assay, analysis.assay_id) if analysis.assay_id else None
    reportability = db.scalar(
        select(ReportabilityDecision).where(ReportabilityDecision.analysis_id == analysis_id, ReportabilityDecision.variant_id == variant_id).order_by(ReportabilityDecision.version.desc())
    )
    normalized = {}
    if annotations:
        payload = annotations[0].payload or {}
        normalized = payload.get("normalized") if isinstance(payload.get("normalized"), dict) else payload
    gene = normalized.get("gene") or normalized.get("gene_symbol") or normalized.get("symbol")
    gene_context = [e for e in evidence if e.evidence_type == "GENE_DISEASE"]
    literature = [e for e in evidence if e.evidence_type == "LITERATURE"]
    phenotype_evidence = [e for e in evidence if e.evidence_type == "PHENOTYPE"]
    functional = [e for e in evidence if e.evidence_type in {"SPLICING", "COMPUTATIONAL", "CONSEQUENCE"}]
    segregation = [e for e in evidence if "SEGREG" in (e.evidence_type or "").upper()]
    inheritance = {}
    clinical_context = (case.clinical_context or {}) if case else {}
    if isinstance(clinical_context.get("inheritance"), dict): inheritance = clinical_context.get("inheritance") or {}
    elif clinical_context.get("inheritance"): inheritance = {"summary": clinical_context.get("inheritance")}
    pedigree = clinical_context.get("pedigree") if isinstance(clinical_context.get("pedigree"), dict) else {}
    pedigree_members = list(db.scalars(select(PedigreeMember).where(PedigreeMember.case_id == analysis.case_id).order_by(PedigreeMember.created_at, PedigreeMember.member_identifier)))
    pedigree_relationships = list(db.scalars(select(PedigreeRelationship).where(PedigreeRelationship.case_id == analysis.case_id).order_by(PedigreeRelationship.created_at)))
    segregation_rows = list(db.scalars(select(SegregationObservation).where(SegregationObservation.analysis_id == analysis_id, SegregationObservation.variant_id == variant_id).order_by(SegregationObservation.created_at)))
    member_by_id = {m.id: m for m in pedigree_members}
    inheritance_assessments = list(db.scalars(select(InheritanceAssessment).where(InheritanceAssessment.analysis_id == analysis_id, InheritanceAssessment.variant_id == variant_id).order_by(InheritanceAssessment.created_at.desc())))
    pedigree = {**pedigree, "members": [{"id": str(m.id), "member_identifier": m.member_identifier, "relationship_to_proband": m.relationship_to_proband, "sex": m.sex, "affected_status": m.affected_status, "is_proband": m.is_proband, "sampled": m.sampled, "specimen_id": str(m.specimen_id) if m.specimen_id else None, "metadata": m.metadata_json or {}} for m in pedigree_members], "relationships": [{"id": str(r.id), "parent_member_id": str(r.parent_member_id), "child_member_id": str(r.child_member_id), "relationship_type": r.relationship_type, "metadata": r.metadata_json or {}} for r in pedigree_relationships]}
    inheritance = {**inheritance, "assessments": [{"id": str(a.id), "model": a.model, "status": a.status, "score": a.score, "rationale": a.rationale, "fingerprint": a.observation_fingerprint, "reviewer_note": a.reviewer_note, "created_at": a.created_at.isoformat()} for a in inheritance_assessments]}
    from backend.app.infrastructure.db.models import ConfirmationRecord, FollowUpPlan, SecondaryFindingDecision
    confirmations = list(db.scalars(select(ConfirmationRecord).where(ConfirmationRecord.analysis_id == analysis_id, ConfirmationRecord.variant_id == variant_id).order_by(ConfirmationRecord.version.desc())))
    followups = list(db.scalars(select(FollowUpPlan).where(FollowUpPlan.analysis_id == analysis_id, FollowUpPlan.variant_id == variant_id).order_by(FollowUpPlan.created_at.desc())))
    secondary = list(db.scalars(select(SecondaryFindingDecision).where(SecondaryFindingDecision.analysis_id == analysis_id, SecondaryFindingDecision.variant_id == variant_id).order_by(SecondaryFindingDecision.version.desc())))
    confirmation = {"latest": {"id": str(confirmations[0].id), "version": confirmations[0].version, "required": confirmations[0].required, "method": confirmations[0].method, "status": confirmations[0].status, "result": confirmations[0].result, "laboratory": confirmations[0].laboratory, "accession": confirmations[0].accession, "performed_at": confirmations[0].performed_at.isoformat() if confirmations[0].performed_at else None, "reviewed_by": str(confirmations[0].reviewed_by) if confirmations[0].reviewed_by else None, "reviewed_at": confirmations[0].reviewed_at.isoformat() if confirmations[0].reviewed_at else None, "notes": confirmations[0].notes} if confirmations else {}, "history_count": len(confirmations)}
    follow_up = {"items": [{"id": str(x.id), "action_type": x.action_type, "status": x.status, "due_date": x.due_date.isoformat() if x.due_date else None, "responsible_role": x.responsible_role, "outcome": x.outcome, "notes": x.notes, "completed_at": x.completed_at.isoformat() if x.completed_at else None} for x in followups], "open_count": sum(1 for x in followups if x.status not in {"COMPLETED", "CANCELLED"})}
    secondary_finding = {"latest": {"id": str(secondary[0].id), "version": secondary[0].version, "policy_name": secondary[0].policy_name, "policy_version": secondary[0].policy_version, "eligibility": secondary[0].eligibility, "consent_status": secondary[0].consent_status, "disposition": secondary[0].disposition, "status": secondary[0].status, "rationale": secondary[0].rationale, "gene_disease_context": secondary[0].gene_disease_context or {}} if secondary else {}, "history_count": len(secondary)}
    return {
        "analysis_id": str(analysis_id),
        "case_id": str(analysis.case_id),
        "case_identifier": case.case_identifier if case else None,
        "variant_id": str(variant_id),
        "review_status": classification.review_status if classification else ReviewStatus.NOT_STARTED,
        "classification": _classification_dict(classification),
        "criteria": [_assessment_dict(x) for x in assessments],
        "history": [_review_action_dict(x) for x in actions],
        "clinical_context": clinical_context,
        "clinical_indication": clinical_context.get("clinical_indication") or clinical_context.get("indication") or clinical_context.get("clinical_question"),
        "phenotypes": [{"hpo_id": p.hpo_id, "label": p.label, "present": p.present, "onset": p.onset, "severity": p.severity, "source": p.source, "evidence": p.evidence or {}} for p in phenotypes],
        "quality": {
            "assay": {"id": str(assay.id), "name": assay.name, "version": assay.version, "assay_type": assay.assay_type, "configuration": assay.configuration or {}} if assay else None,
            "observations": [{"id": str(q.id), "metric_name": q.metric_name, "metric_value": q.metric_value, "metric_unit": q.metric_unit, "status": q.status, "source": q.source, "source_version": q.source_version, "metadata": q.metadata_json or {}, "created_at": q.created_at.isoformat()} for q in qc_observations],
            "latest_assessment": {"id": str(qc_assessments[0].id), "status": qc_assessments[0].status, "gate_status": qc_assessments[0].gate_status, "profile_name": qc_assessments[0].profile_name, "profile_version": qc_assessments[0].profile_version, "metrics": qc_assessments[0].metrics_json or {}, "evaluated_rules": qc_assessments[0].evaluated_rules or [], "reviewer_note": qc_assessments[0].reviewer_note, "reviewed_by": qc_assessments[0].reviewed_by, "reviewed_at": qc_assessments[0].reviewed_at.isoformat() if qc_assessments[0].reviewed_at else None} if qc_assessments else None,
        },
        "variant_context": {
            "gene": gene,
            "annotations": [{"provider": a.provider_name, "provider_version": a.provider_version, "resource": a.resource_name, "resource_version": a.resource_version, "payload": a.payload or {}} for a in annotations],
            "population": [{"population": p.population_code, "level": p.population_level, "label": p.population_label, "availability": p.availability, "af": p.allele_frequency, "ac": p.allele_count, "an": p.allele_number, "resource_id": str(p.resource_id), "quality_status": p.quality_status} for p in population],
            "gene_disease": [_evidence_context_dict(e) for e in gene_context],
            "phenotype_evidence": [_evidence_context_dict(e) for e in phenotype_evidence],
            "literature": [_evidence_context_dict(e) for e in literature],
            "functional_computational": [_evidence_context_dict(e) for e in functional],
            "segregation": [_evidence_context_dict(e) for e in segregation],
            "segregation_observations": [{"id": str(o.id), "pedigree_member_id": str(o.pedigree_member_id), "member_identifier": member_by_id[o.pedigree_member_id].member_identifier if o.pedigree_member_id in member_by_id else None, "genotype": o.genotype, "zygosity": o.zygosity, "phase": o.phase, "allele_observed": o.allele_observed, "phenotype_status": o.phenotype_status, "source": o.source, "notes": o.notes, "metadata": o.metadata_json or {}} for o in segregation_rows],
            "technical_qc": normalized.get("qc") or normalized.get("quality") or {},
        },
        "inheritance": inheritance,
        "pedigree": pedigree,
        "reportability": {
            "disposition": reportability.disposition, "priority_score": reportability.priority_score, "priority_band": reportability.priority_band,
            "status": reportability.status, "version": reportability.version, "policy_name": reportability.policy_name, "policy_version": reportability.policy_version, "reasons": reportability.reasons or [],
        } if reportability else None,
        "confirmation": confirmation,
        "follow_up": follow_up,
        "secondary_finding": secondary_finding,
        "evidence_count": len(evidence),
    }


def start_review(
    db: Session,
    *,
    analysis_id: UUID,
    variant_id: UUID,
    reviewer: User,
) -> Classification:
    require_reviewer(reviewer)
    current = db.scalar(
        select(Classification)
        .where(Classification.analysis_id == analysis_id, Classification.variant_id == variant_id)
        .order_by(Classification.version.desc())
        .with_for_update()
    )
    if current is None:
        raise ReviewError("Classification not found")
    if current.review_status == ReviewStatus.APPROVED:
        raise ReviewError("Approved classification cannot be reopened by start-review")
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise ReviewError("Analysis not found")
    before = _classification_dict(current)
    current.review_status = ReviewStatus.IN_REVIEW
    current.review_version += 1
    after = _classification_dict(current)
    action = ReviewAction(
        id=uuid4(),
        case_id=analysis.case_id,
        analysis_id=analysis_id,
        variant_id=variant_id,
        reviewer_id=reviewer.id,
        action_type="REVIEW_STARTED",
        sequence_number=_next_review_sequence(db, analysis_id, variant_id),
        reason="Reviewer opened interpretation for review",
        before_state=before,
        after_state=after,
        expected_version=current.review_version - 1,
        resulting_version=current.review_version,
    )
    db.add(action)
    AuditService(db).record(
        event_type="REVIEW_STARTED",
        case_id=analysis.case_id,
        analysis_id=analysis_id,
        actor_type="HUMAN",
        actor_id=str(reviewer.id),
        subject_type="CLASSIFICATION",
        subject_id=str(current.id),
        operation="UPDATE",
        before_state=before,
        after_state=after,
        reason="Reviewer opened interpretation for review",
    )
    db.flush()
    return current


def review_criterion(
    db: Session,
    *,
    analysis_id: UUID,
    variant_id: UUID,
    criterion: str,
    mutation: ReviewMutation,
    reviewer: User,
) -> ACMGAssessment:
    require_reviewer(reviewer)
    criterion = criterion.strip().upper()
    if not criterion or not mutation.reason.strip():
        raise ReviewError("Criterion and review reason are required")

    assessment = db.scalar(
        select(ACMGAssessment)
        .where(
            ACMGAssessment.analysis_id == analysis_id,
            ACMGAssessment.variant_id == variant_id,
            ACMGAssessment.criterion == criterion,
        )
        .with_for_update()
    )
    if assessment is None:
        raise ReviewError("ACMG assessment not found")
    if assessment.review_version != mutation.expected_version:
        raise ReviewConflictError(
            f"Review version conflict: expected {mutation.expected_version}, current {assessment.review_version}"
        )

    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise ReviewError("Analysis not found")
    if db.get(Variant, variant_id) is None:
        raise ReviewError("Variant not found")
    if mutation.evidence_ids:
        evidence_rows = list(db.scalars(
            select(Evidence).where(
                Evidence.id.in_(mutation.evidence_ids),
                Evidence.analysis_id == analysis_id,
                Evidence.variant_id == variant_id,
            )
        ))
        if len(evidence_rows) != len(set(mutation.evidence_ids)):
            raise ReviewError("Every selected evidence record must belong to this variant and analysis")

    before = {
        "review_version": assessment.review_version,
        "reviewed_assessment": assessment.reviewed_assessment,
        "final_assessment": assessment.final_assessment,
        "state": assessment.state,
    }
    now = datetime.now(timezone.utc)
    after_review = {
        "decision": mutation.decision,
        "strength": mutation.strength,
        "reason": mutation.reason.strip(),
        "evidence_ids": [str(x) for x in mutation.evidence_ids],
        "reviewer_id": str(reviewer.id),
        "reviewed_at": now.isoformat(),
        "revision": assessment.review_version + 1,
    }
    assessment.reviewed_assessment = after_review
    assessment.final_assessment = after_review if mutation.decision in {"ACCEPT", "MODIFY"} else None
    assessment.state = {"ACCEPT": "ACCEPTED", "MODIFY": "MODIFIED", "REJECT": "REJECTED"}[mutation.decision]
    assessment.review_version += 1

    action = ReviewAction(
        id=uuid4(),
        case_id=analysis.case_id,
        analysis_id=analysis_id,
        variant_id=variant_id,
        reviewer_id=reviewer.id,
        action_type=f"ACMG_{mutation.decision}",
        sequence_number=_next_review_sequence(db, analysis_id, variant_id),
        reason=mutation.reason.strip(),
        before_state=before,
        after_state={
            "reviewed_assessment": assessment.reviewed_assessment,
            "final_assessment": assessment.final_assessment,
            "state": assessment.state,
            "review_version": assessment.review_version,
        },
        expected_version=mutation.expected_version,
        resulting_version=assessment.review_version,
    )
    db.add(action)
    AuditService(db).record(
        event_type="ACMG_CRITERION_MODIFIED" if mutation.decision == "MODIFY" else "REVIEW_DECISION_RECORDED",
        case_id=analysis.case_id,
        analysis_id=analysis_id,
        actor_type="HUMAN",
        actor_id=str(reviewer.id),
        subject_type="ACMG_CRITERION",
        subject_id=f"{variant_id}:{criterion}",
        operation="REVIEW",
        before_state=before,
        after_state=action.after_state,
        reason=mutation.reason.strip(),
        payload={"review_sequence": action.sequence_number},
    )
    db.flush()
    return assessment


def approve_classification(
    db: Session,
    *,
    analysis_id: UUID,
    variant_id: UUID,
    reviewer: User,
    expected_version: int,
    reason: str,
) -> Classification:
    require_reviewer(reviewer)
    if not reason.strip():
        raise ReviewError("Approval reason is required")

    current = db.scalar(
        select(Classification)
        .where(Classification.analysis_id == analysis_id, Classification.variant_id == variant_id)
        .order_by(Classification.version.desc())
        .with_for_update()
    )
    if current is None:
        raise ReviewError("Classification not found")
    if current.review_status == ReviewStatus.APPROVED:
        return current
    if current.review_status != ReviewStatus.IN_REVIEW:
        raise ReviewError("Classification must be in active review before approval")
    if current.review_version != expected_version:
        raise ReviewConflictError(
            f"Classification review version conflict: expected {expected_version}, current {current.review_version}"
        )

    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise ReviewError("Analysis not found")

    before = _classification_dict(current)
    approved_at = datetime.now(timezone.utc)
    new = Classification(
        id=uuid4(),
        variant_id=variant_id,
        analysis_id=analysis_id,
        version=current.version + 1,
        supersedes_classification_id=current.id,
        framework_name=current.framework_name,
        framework_version=current.framework_version,
        specification_provider=current.specification_provider,
        specification_id=current.specification_id,
        specification_version=current.specification_version,
        result=current.result,
        criterion_ids=list(current.criterion_ids or []),
        metadata_json=dict(current.metadata_json or {}),
        state="FINAL",
        review_status=ReviewStatus.APPROVED,
        review_version=current.review_version + 1,
        reviewed_by=reviewer.id,
        approved_at=approved_at,
    )
    db.add(new)

    after = _classification_dict(new)
    action = ReviewAction(
        id=uuid4(),
        case_id=analysis.case_id,
        analysis_id=analysis_id,
        variant_id=variant_id,
        reviewer_id=reviewer.id,
        action_type="CLASSIFICATION_APPROVED",
        sequence_number=_next_review_sequence(db, analysis_id, variant_id),
        reason=reason.strip(),
        before_state=before,
        after_state=after,
        expected_version=expected_version,
        resulting_version=new.review_version,
    )
    db.add(action)
    AuditService(db).record(
        event_type="CLASSIFICATION_APPROVED",
        case_id=analysis.case_id,
        analysis_id=analysis_id,
        actor_type="HUMAN",
        actor_id=str(reviewer.id),
        subject_type="CLASSIFICATION",
        subject_id=str(new.id),
        operation="APPROVE",
        before_state=before,
        after_state=after,
        reason=reason.strip(),
        payload={"supersedes_classification_id": str(current.id)},
    )
    db.flush()
    return new


def request_more_evidence(
    db: Session,
    *,
    analysis_id: UUID,
    variant_id: UUID,
    reviewer: User,
    expected_version: int,
    reason: str,
) -> Classification:
    require_reviewer(reviewer)
    if not reason.strip():
        raise ReviewError("Reason is required")

    current = db.scalar(
        select(Classification)
        .where(Classification.analysis_id == analysis_id, Classification.variant_id == variant_id)
        .order_by(Classification.version.desc())
        .with_for_update()
    )
    if current is None:
        raise ReviewError("Classification not found")
    if current.review_version != expected_version:
        raise ReviewConflictError(
            f"Classification review version conflict: expected {expected_version}, current {current.review_version}"
        )
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise ReviewError("Analysis not found")

    before = _classification_dict(current)
    current.review_status = ReviewStatus.MORE_EVIDENCE
    current.review_version += 1
    current.metadata_json = {**(current.metadata_json or {}), "more_evidence_reason": reason.strip()}
    after = _classification_dict(current)

    action = ReviewAction(
        id=uuid4(),
        case_id=analysis.case_id,
        analysis_id=analysis_id,
        variant_id=variant_id,
        reviewer_id=reviewer.id,
        action_type="REQUEST_MORE_EVIDENCE",
        sequence_number=_next_review_sequence(db, analysis_id, variant_id),
        reason=reason.strip(),
        before_state=before,
        after_state=after,
        expected_version=expected_version,
        resulting_version=current.review_version,
    )
    db.add(action)
    AuditService(db).record(
        event_type="REVIEW_MORE_EVIDENCE_REQUESTED",
        case_id=analysis.case_id,
        analysis_id=analysis_id,
        actor_type="HUMAN",
        actor_id=str(reviewer.id),
        subject_type="CLASSIFICATION",
        subject_id=str(current.id),
        operation="UPDATE",
        before_state=before,
        after_state=after,
        reason=reason.strip(),
    )
    db.flush()
    return current


def _next_review_sequence(db: Session, analysis_id: UUID, variant_id: UUID) -> int:
    latest = db.scalar(
        select(ReviewAction.sequence_number)
        .where(ReviewAction.analysis_id == analysis_id, ReviewAction.variant_id == variant_id)
        .order_by(ReviewAction.sequence_number.desc())
        .limit(1)
    )
    return int(latest or 0) + 1


def _assessment_dict(row: ACMGAssessment) -> dict:
    return {
        "assessment_id": str(row.id),
        "criterion": row.criterion,
        "state": row.state,
        "review_version": row.review_version,
        "automated_assessment": row.automated_assessment,
        "reviewed_assessment": row.reviewed_assessment,
        "final_assessment": row.final_assessment,
        "specification": {
            "provider": row.specification_provider,
            "id": row.specification_id,
            "version": row.specification_version,
        },
    }


def _classification_dict(row: Classification | None) -> dict | None:
    if row is None:
        return None
    return {
        "classification_id": str(row.id),
        "version": row.version,
        "supersedes_classification_id": str(row.supersedes_classification_id) if row.supersedes_classification_id else None,
        "result": row.result,
        "state": row.state,
        "review_status": row.review_status,
        "review_version": row.review_version,
        "framework_name": row.framework_name,
        "framework_version": row.framework_version,
        "specification_provider": row.specification_provider,
        "specification_id": row.specification_id,
        "specification_version": row.specification_version,
        "criterion_ids": list(row.criterion_ids or []),
        "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "metadata": row.metadata_json or {},
    }


def _review_action_dict(row: ReviewAction) -> dict:
    return {
        "action_id": str(row.id),
        "sequence_number": row.sequence_number,
        "action_type": row.action_type,
        "reviewer_id": str(row.reviewer_id),
        "reason": row.reason,
        "before_state": row.before_state,
        "after_state": row.after_state,
        "expected_version": row.expected_version,
        "resulting_version": row.resulting_version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
