from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import get_analysis_variant_ids
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Analysis, Classification, ReportabilityDecision

POLICY_NAME = "SIRALOOM_DEFAULT_GERMLINE_REPORTABILITY"
POLICY_VERSION = "2.0.0"
DISPOSITIONS = {"REPORT", "DO_NOT_REPORT", "REVIEW"}
STATUSES = {"PROPOSED", "FINAL"}


@dataclass(frozen=True)
class ReportabilityProposal:
    disposition: str
    reasons: list[str]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def propose_reportability(_classification: Classification) -> ReportabilityProposal:
    """Require laboratory review because classification alone cannot set reportability."""
    return ReportabilityProposal(
        "REVIEW",
        [
            "Apply the laboratory's approved reporting policy to the test scope and "
            "case context; variant classification alone does not determine reportability."
        ],
    )


def latest_decision(db: Session, analysis_id: UUID, variant_id: UUID) -> ReportabilityDecision | None:
    return db.scalar(
        select(ReportabilityDecision)
        .where(ReportabilityDecision.analysis_id == analysis_id, ReportabilityDecision.variant_id == variant_id)
        .order_by(ReportabilityDecision.version.desc())
    )


def is_current_approved_reportability_decision(
    db: Session,
    decision: ReportabilityDecision,
) -> bool:
    """Check that a decision is attached to the latest approved classification."""
    classification = db.execute(
        select(Classification.id, Classification.state, Classification.review_status)
        .where(
            Classification.analysis_id == decision.analysis_id,
            Classification.variant_id == decision.variant_id,
        )
        .order_by(Classification.version.desc())
        .limit(1)
    ).first()
    return bool(
        classification is not None
        and classification.id == decision.classification_id
        and classification.state == "FINAL"
        and classification.review_status == "APPROVED"
    )


def evaluate_analysis(db: Session, analysis: Analysis) -> list[ReportabilityDecision]:
    # Serialize proposal generation for the whole analysis. Locking the existing
    # classification rows alone does not protect the no-decision-yet case: two
    # evaluators could both observe no current decision and create version 1.
    locked_analysis = db.get(Analysis, analysis.id, with_for_update=True)
    if locked_analysis is None:
        raise ValueError("Analysis not found")
    db.refresh(locked_analysis, with_for_update=True)
    analysis = locked_analysis
    classifications = list(
        db.scalars(
            select(Classification)
            .where(Classification.analysis_id == analysis.id)
            .order_by(Classification.variant_id, Classification.version.desc())
            .with_for_update()
        )
    )
    latest_cls: dict[UUID, Classification] = {}
    for row in classifications:
        latest_cls.setdefault(row.variant_id, row)

    manifest_variant_ids = get_analysis_variant_ids(analysis, db)
    if manifest_variant_ids is not None:
        unlinked = set(latest_cls) - manifest_variant_ids
        if unlinked:
            raise ValueError(
                "Cannot evaluate reportability for classifications outside the normalized input: "
                + ", ".join(sorted(str(value) for value in unlinked))
            )

    created: list[ReportabilityDecision] = []
    for variant_id, cls in latest_cls.items():
        # Reportability is downstream of the human classification gate. Never
        # create or refresh a reportability decision from a proposed/unapproved
        # classification; the workflow must remain blocked at human review.
        if cls.state != "FINAL" or cls.review_status != "APPROVED":
            continue
        current = latest_decision(db, analysis.id, variant_id)
        if current and current.classification_id == cls.id and current.status == "FINAL":
            continue
        proposal = propose_reportability(cls)
        if current and current.classification_id == cls.id and current.status == "PROPOSED":
            continue
        version = (current.version + 1) if current else 1
        decision = ReportabilityDecision(
            id=uuid4(), analysis_id=analysis.id, variant_id=variant_id, classification_id=cls.id,
            version=version, supersedes_decision_id=current.id if current else None,
            policy_name=POLICY_NAME, policy_version=POLICY_VERSION,
            disposition=proposal.disposition, priority_score=None,
            priority_band=None, reasons=proposal.reasons,
            status="PROPOSED", review_version=0,
        )
        db.add(decision)
        created.append(decision)
        AuditService(db).record(
            event_type="REPORTABILITY_PROPOSED", case_id=analysis.case_id, analysis_id=analysis.id,
            actor_type="SYSTEM", actor_id="reportability", subject_type="REPORTABILITY_DECISION",
            subject_id=str(decision.id), operation="CREATE",
            before_state={"decision_id": str(current.id)} if current else None,
            after_state={"disposition": decision.disposition,
                          "policy": f"{POLICY_NAME}@{POLICY_VERSION}", "classification_id": str(cls.id)},
        )
    db.flush()
    return created


def finalize_reportability(
    db: Session, *, decision_id: UUID, reviewer_id: UUID, expected_version: int,
    disposition: str, reason: str,
) -> ReportabilityDecision:
    if disposition not in DISPOSITIONS:
        raise ValueError("Unsupported reportability disposition")
    if not reason.strip():
        raise ValueError("Reportability review reason is required")
    # Serialize concurrent reportability sign-off attempts for this decision.
    # The review-version check is optimistic concurrency protection, but the
    # row lock is required to prevent two workers from both observing PROPOSED
    # and creating conflicting FINAL mutations in the same transaction window.
    observed = db.get(ReportabilityDecision, decision_id)
    if observed is None:
        raise ValueError("Reportability decision not found")

    # Classification approval serializes on the analysis row. Acquire that
    # lock before the decision row to keep the same lock order as evaluation
    # and classification updates, then refresh both rows before checking state.
    analysis = db.get(Analysis, observed.analysis_id, with_for_update=True)
    if analysis is None:
        raise ValueError("Analysis not found")
    db.refresh(analysis, with_for_update=True)
    decision = db.get(ReportabilityDecision, decision_id)
    if decision is None:
        raise ValueError("Reportability decision not found")
    db.refresh(decision, with_for_update=True)
    if decision.analysis_id != analysis.id:
        raise ValueError("Reportability decision analysis changed during finalization")
    manifest_variant_ids = get_analysis_variant_ids(analysis, db)
    if manifest_variant_ids is not None and decision.variant_id not in manifest_variant_ids:
        raise ValueError("Reportability decision references a variant outside the normalized analysis input")

    current_latest = latest_decision(db, decision.analysis_id, decision.variant_id)
    if current_latest is None or current_latest.id != decision.id:
        raise ValueError(
            "Reportability decision is no longer the latest decision for this variant; "
            "finalize the current latest proposal instead"
        )
    if not is_current_approved_reportability_decision(db, decision):
        raise ValueError(
            "Reportability decision is stale because it is not linked to the latest "
            "approved classification"
        )
    if decision.status == "FINAL":
        return decision

    if decision.review_version != expected_version:
        raise ValueError(
            f"Reportability review version conflict: expected {expected_version}, current {decision.review_version}"
        )
    before = {"status": decision.status, "disposition": decision.disposition, "review_version": decision.review_version}
    decision.disposition = disposition
    decision.status = "FINAL"
    decision.review_version += 1
    decision.reviewed_by = reviewer_id
    decision.approved_at = _now()
    decision.reasons = list(decision.reasons or []) + [f"Reviewer: {reason.strip()}"]
    AuditService(db).record(
        event_type="REPORTABILITY_FINALIZED", case_id=db.get(Analysis, decision.analysis_id).case_id,
        analysis_id=decision.analysis_id, actor_type="HUMAN", actor_id=str(reviewer_id),
        subject_type="REPORTABILITY_DECISION", subject_id=str(decision.id), operation="APPROVE",
        before_state=before,
        after_state={"status": decision.status, "disposition": decision.disposition,
                     "review_version": decision.review_version, "reviewed_by": str(reviewer_id)},
        reason=reason.strip(),
    )
    db.flush()
    return decision


def final_reportability_state(db: Session, analysis_id: UUID) -> tuple[bool, list[str]]:
    analysis = db.get(Analysis, analysis_id)
    if not analysis:
        return False, ["Analysis not found"]
    classifications = list(db.scalars(select(Classification).where(Classification.analysis_id == analysis_id)))
    latest: dict[UUID, Classification] = {}
    for row in classifications:
        if row.variant_id not in latest or row.version > latest[row.variant_id].version:
            latest[row.variant_id] = row
    errors: list[str] = []
    manifest_variant_ids = get_analysis_variant_ids(analysis, db)
    if manifest_variant_ids is not None and set(latest) != manifest_variant_ids:
        errors.append(
            "Classifications do not exactly match the normalized input variant set"
        )
    decision_rows = list(
        db.scalars(
            select(ReportabilityDecision)
            .where(ReportabilityDecision.analysis_id == analysis_id)
            .order_by(ReportabilityDecision.variant_id, ReportabilityDecision.version.desc())
        )
    )
    latest_decisions: dict[UUID, ReportabilityDecision] = {}
    for row in decision_rows:
        latest_decisions.setdefault(row.variant_id, row)
    orphan_decision_variants = set(latest_decisions) - set(latest)
    if orphan_decision_variants:
        errors.append(
            "Reportability decisions reference variants without a classification: "
            + ", ".join(sorted(str(value) for value in orphan_decision_variants))
        )
    if manifest_variant_ids is not None:
        out_of_manifest_decisions = set(latest_decisions) - manifest_variant_ids
        if out_of_manifest_decisions:
            errors.append(
                "Reportability decisions reference variants outside the normalized input: "
                + ", ".join(sorted(str(value) for value in out_of_manifest_decisions))
            )
    for variant_id, cls in latest.items():
        if cls.state != "FINAL" or cls.review_status != "APPROVED":
            errors.append(f"Variant {variant_id} classification is not FINAL + APPROVED")
            continue
        decision = latest_decisions.get(variant_id)
        if decision is None:
            errors.append(f"Variant {variant_id} has no reportability decision")
        elif decision.status != "FINAL":
            errors.append(f"Variant {variant_id} reportability is not FINAL")
        elif decision.classification_id != cls.id:
            errors.append(
                f"Variant {variant_id} reportability is linked to a stale classification"
            )
    if not latest:
        errors.append("No variant classification is available")
    return not errors, errors
