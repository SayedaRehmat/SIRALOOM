from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    AnalysisPartition,
    AnalysisResourceSnapshot,
    Annotation,
    Case,
    Classification,
    Evidence,
    Notification,
    OrganizationMembership,
    PopulationObservation,
    ReanalysisCandidate,
    ReanalysisChangeEvent,
    Resource,
    WorkflowStep,
)

CHANGE_STEP = {
    "ANNOTATION_UPDATE": "annotate",
    "POPULATION_UPDATE": "population",
    "EVIDENCE_UPDATE": "build_evidence",
    "ACMG_RULE_UPDATE": "acmg_assessment",
    "PHENOTYPE_UPDATE": "build_evidence",
    "BIOINFORMATICS_UPDATE": "annotate",
    "REFERENCE_UPDATE": "normalize",
    "PERIODIC": "build_evidence",
    "MANUAL": "normalize",
}

STEP_ORDER = {
    "validate_input": 1,
    "normalize": 2,
    "annotate": 3,
    "population": 4,
    "build_evidence": 5,
    "acmg_assessment": 6,
    "review": 7,
    "reportability": 8,
    "report": 9,
    "export_provenance": 10,
}


def _now():
    return datetime.now(timezone.utc)


def affected_step_for_trigger(trigger_type: str) -> str:
    try:
        return CHANGE_STEP[trigger_type]
    except KeyError:
        raise ValueError(f"Unsupported reanalysis trigger: {trigger_type}")


def snapshot_analysis_resources(db: Session, analysis: Analysis) -> int:
    """Persist the exact external resource identities observed by a completed analysis."""
    existing = db.scalar(
        select(AnalysisResourceSnapshot.id)
        .where(AnalysisResourceSnapshot.analysis_id == analysis.id)
        .limit(1)
    )
    if existing:
        return int(db.query(AnalysisResourceSnapshot).filter(
            AnalysisResourceSnapshot.analysis_id == analysis.id
        ).count())

    from backend.app.infrastructure.db.models import Artifact

    count = 0

    reference_resource_id = (analysis.configuration or {}).get("reference_resource_id")
    if reference_resource_id:
        resource = db.get(Resource, UUID(str(reference_resource_id)))
        if resource:
            db.add(AnalysisResourceSnapshot(
                id=uuid4(), analysis_id=analysis.id, resource_id=resource.id,
                resource_kind="REFERENCE", resource_name=resource.name,
                provider=resource.provider, version=resource.version,
                checksum=resource.checksum, genome_build=resource.genome_build,
                metadata_json={"resource_type": resource.resource_type},
            ))
            count += 1

    resource_ids = db.scalars(
        select(PopulationObservation.resource_id)
        .where(PopulationObservation.analysis_id == analysis.id)
        .distinct()
    ).all()
    for rid in resource_ids:
        resource = db.get(Resource, rid)
        if resource:
            db.add(AnalysisResourceSnapshot(
                id=uuid4(), analysis_id=analysis.id, resource_id=resource.id,
                resource_kind="POPULATION", resource_name=resource.name,
                provider=resource.provider, version=resource.version,
                checksum=resource.checksum, genome_build=resource.genome_build,
                metadata_json={"resource_type": resource.resource_type},
            ))
            count += 1

    annotations = db.scalars(
        select(Annotation).where(Annotation.analysis_id == analysis.id)
    ).all()
    seen = set()
    for row in annotations:
        key = ("ANNOTATION", row.resource_name or row.provider_name, row.provider_version, row.resource_version)
        if key in seen:
            continue
        seen.add(key)
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis.id, resource_id=None,
            resource_kind="ANNOTATION", resource_name=row.resource_name or row.provider_name,
            provider=row.provider_name, version=row.resource_version or row.provider_version,
            checksum=None, genome_build=analysis.reference_build,
            metadata_json={"provider_version": row.provider_version},
        ))
        count += 1

    evidence = db.scalars(select(Evidence).where(Evidence.analysis_id == analysis.id)).all()
    seen = set()
    for row in evidence:
        if not row.source_name:
            continue
        key = ("EVIDENCE", row.source_name, row.source_version)
        if key in seen:
            continue
        seen.add(key)
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis.id, resource_id=None,
            resource_kind="EVIDENCE", resource_name=row.source_name,
            provider=None, version=row.source_version,
            checksum=None, genome_build=analysis.reference_build,
            metadata_json={},
        ))
        count += 1

    assessments = db.scalars(select(ACMGAssessment).where(ACMGAssessment.analysis_id == analysis.id)).all()
    seen = set()
    for row in assessments:
        if not row.specification_id:
            continue
        key = ("ACMG_RULE", row.specification_id, row.specification_version)
        if key in seen:
            continue
        seen.add(key)
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis.id, resource_id=None,
            resource_kind="ACMG_RULE", resource_name=row.specification_id,
            provider=row.specification_provider, version=row.specification_version or row.framework_version,
            checksum=None, genome_build=analysis.reference_build,
            metadata_json={"framework_name": row.framework_name, "framework_version": row.framework_version},
        ))
        count += 1

    db.commit()
    return count


def _change_fingerprint(
    *,
    organization_id: UUID,
    trigger_type: str,
    resource_kind: str,
    resource_name: str,
    new_version: str | None,
    new_checksum: str | None,
) -> str:
    """Return a stable identity for one organization/resource release event.

    The fingerprint intentionally excludes the previous snapshot version:
    one newly registered resource release is one change event, even when
    different historical analyses used different older releases.
    """
    material = "\\x1f".join([
        str(organization_id),
        trigger_type,
        resource_kind,
        resource_name,
        new_version or "",
        new_checksum or "",
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def create_change_event(
    db: Session,
    *,
    organization_id: UUID,
    trigger_type: str,
    resource_kind: str,
    resource_name: str,
    new_version: str | None,
    new_checksum: str | None,
    previous_version: str | None = None,
    previous_checksum: str | None = None,
    resource_id: UUID | None = None,
) -> ReanalysisChangeEvent:
    fingerprint = _change_fingerprint(
        organization_id=organization_id,
        trigger_type=trigger_type,
        resource_kind=resource_kind,
        resource_name=resource_name,
        new_version=new_version,
        new_checksum=new_checksum,
    )
    existing = db.scalar(
        select(ReanalysisChangeEvent).where(
            ReanalysisChangeEvent.change_fingerprint == fingerprint,
        )
    )
    if existing:
        return existing

    event = ReanalysisChangeEvent(
        id=uuid4(),
        change_fingerprint=fingerprint,
        organization_id=organization_id,
        resource_id=resource_id,
        trigger_type=trigger_type,
        resource_kind=resource_kind,
        resource_name=resource_name,
        previous_version=previous_version,
        new_version=new_version,
        previous_checksum=previous_checksum,
        new_checksum=new_checksum,
        metadata_json={},
    )
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(ReanalysisChangeEvent).where(
                ReanalysisChangeEvent.change_fingerprint == fingerprint,
            )
        )
        if existing is None:
            raise
        return existing
    return event


def detect_change(
    db: Session,
    *,
    organization_id: UUID,
    trigger_type: str,
    resource_kind: str,
    resource_name: str,
    new_version: str | None,
    new_checksum: str | None,
    resource_id: UUID | None = None,
) -> list[ReanalysisCandidate]:
    """Compare a newly registered resource identity with immutable analysis snapshots."""
    snapshots = db.scalars(
        select(AnalysisResourceSnapshot)
        .join(Analysis, Analysis.id == AnalysisResourceSnapshot.analysis_id)
        .join(Case, Case.id == Analysis.case_id)
        .where(
            Case.organization_id == organization_id,
            Analysis.status == "SUCCEEDED",
            AnalysisResourceSnapshot.resource_kind == resource_kind,
            AnalysisResourceSnapshot.resource_name == resource_name,
        )
    ).all()

    candidates: list[ReanalysisCandidate] = []
    for snapshot in snapshots:
        same_identity = (
            snapshot.version == new_version
            and snapshot.checksum == new_checksum
        )
        if same_identity:
            continue

        event = create_change_event(
            db,
            organization_id=organization_id,
            trigger_type=trigger_type,
            resource_kind=resource_kind,
            resource_name=resource_name,
            new_version=new_version,
            new_checksum=new_checksum,
            previous_version=snapshot.version,
            previous_checksum=snapshot.checksum,
            resource_id=resource_id,
        )
        parent = db.get(Analysis, snapshot.analysis_id)
        if not parent:
            continue

        candidate = db.scalar(
            select(ReanalysisCandidate).where(
                ReanalysisCandidate.parent_analysis_id == parent.id,
                ReanalysisCandidate.change_event_id == event.id,
            )
        )
        if candidate:
            continue

        candidate = ReanalysisCandidate(
            id=uuid4(),
            organization_id=organization_id,
            case_id=parent.case_id,
            parent_analysis_id=parent.id,
            change_event_id=event.id,
            trigger_type=trigger_type,
            earliest_affected_step=affected_step_for_trigger(trigger_type),
            reason=(
                f"{resource_kind} resource '{resource_name}' changed from "
                f"{snapshot.version or 'unversioned'} to {new_version or 'unversioned'}."
            ),
            status="PENDING",
        )
        created_candidate = False
        try:
            with db.begin_nested():
                db.add(candidate)
                db.flush()
            created_candidate = True
        except IntegrityError:
            candidate = db.scalar(
                select(ReanalysisCandidate).where(
                    ReanalysisCandidate.parent_analysis_id == parent.id,
                    ReanalysisCandidate.change_event_id == event.id,
                )
            )
            if candidate is None:
                raise

        if created_candidate:
            users = db.scalars(
                select(OrganizationMembership.user_id).where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.status == "ACTIVE",
                )
            ).all()
            for user_id in users:
                db.add(Notification(
                    id=uuid4(), organization_id=organization_id, user_id=user_id,
                    notification_type="REANALYSIS_CANDIDATE",
                    status="UNREAD",
                    title="Case reanalysis may be required",
                    body=candidate.reason,
                    case_id=parent.case_id,
                    analysis_id=parent.id,
                    candidate_id=candidate.id,
                    metadata_json={
                        "trigger_type": trigger_type,
                        "resource_kind": resource_kind,
                        "resource_name": resource_name,
                        "previous_version": snapshot.version,
                        "new_version": new_version,
                        "earliest_affected_step": candidate.earliest_affected_step,
                    },
                ))
            candidates.append(candidate)

    db.commit()
    return candidates


def _copy_rows(db: Session, parent_id: UUID, child_id: UUID, earliest: str) -> None:
    start = STEP_ORDER[earliest]

    if start > STEP_ORDER["annotate"]:
        for row in db.scalars(select(Annotation).where(Annotation.analysis_id == parent_id)).all():
            db.add(Annotation(
                id=uuid4(), variant_id=row.variant_id, analysis_id=child_id,
                provider_name=row.provider_name, provider_version=row.provider_version,
                resource_name=row.resource_name, resource_version=row.resource_version,
                payload=row.payload,
            ))

    if start > STEP_ORDER["population"]:
        for row in db.scalars(select(PopulationObservation).where(PopulationObservation.analysis_id == parent_id)).all():
            db.add(PopulationObservation(
                id=uuid4(), analysis_id=child_id, variant_id=row.variant_id,
                resource_id=row.resource_id, population_level=row.population_level,
                population_code=row.population_code, population_label=row.population_label,
                allele_count=row.allele_count, allele_number=row.allele_number,
                allele_frequency=row.allele_frequency, homozygote_count=row.homozygote_count,
                availability=row.availability, quality_status=row.quality_status,
            ))

    if start > STEP_ORDER["build_evidence"]:
        for row in db.scalars(select(Evidence).where(Evidence.analysis_id == parent_id)).all():
            db.add(Evidence(
                id=uuid4(), variant_id=row.variant_id, analysis_id=child_id,
                evidence_type=row.evidence_type, statement=row.statement,
                direction=row.direction, source_name=row.source_name,
                source_version=row.source_version, source_record_id=row.source_record_id,
                observation_ids=row.observation_ids, payload=row.payload,
                created_by_type=row.created_by_type, created_by_id=row.created_by_id,
                evidence_fingerprint=row.evidence_fingerprint,
            ))

    if start > STEP_ORDER["acmg_assessment"]:
        for row in db.scalars(select(ACMGAssessment).where(ACMGAssessment.analysis_id == parent_id)).all():
            db.add(ACMGAssessment(
                id=uuid4(), variant_id=row.variant_id, analysis_id=child_id,
                framework_name=row.framework_name, framework_version=row.framework_version,
                specification_provider=row.specification_provider,
                specification_id=row.specification_id, specification_version=row.specification_version,
                criterion=row.criterion, automated_assessment=row.automated_assessment,
                reviewed_assessment=None, final_assessment=None, state="DRAFT",
                review_version=0,
            ))
    db.flush()


def create_reanalysis(
    db: Session,
    *,
    parent: Analysis,
    trigger_type: str,
    requested_by: UUID,
    reason: str,
    change_event_id: UUID | None = None,
    affected_step: str | None = None,
) -> tuple[Analysis, ReanalysisCandidate | None]:
    """Create one immutable child analysis with concurrency-safe lineage."""
    if parent.status != "SUCCEEDED":
        raise ValueError("Only a successfully completed analysis can be reanalyzed.")

    earliest = affected_step or affected_step_for_trigger(trigger_type)
    next_version = (parent.analysis_version or 1) + 1

    duplicate = db.scalar(
        select(Analysis).where(
            Analysis.case_id == parent.case_id,
            Analysis.parent_analysis_id == parent.id,
            Analysis.analysis_version == next_version,
        )
    )
    if duplicate:
        candidate = None
        if change_event_id:
            candidate = db.scalar(select(ReanalysisCandidate).where(
                ReanalysisCandidate.parent_analysis_id == parent.id,
                ReanalysisCandidate.change_event_id == change_event_id,
            ))
        return duplicate, candidate

    from backend.app.application.entitlements import require_analysis_quota, consume_analysis_quota

    case = db.get(Case, parent.case_id)
    if case is None:
        raise ValueError("Parent analysis case not found.")
    require_analysis_quota(db, case.organization_id)

    child = Analysis(
        id=uuid4(), case_id=parent.case_id, parent_analysis_id=parent.id,
        assay_id=parent.assay_id, analysis_type=parent.analysis_type,
        workflow_id=parent.workflow_id, workflow_version=parent.workflow_version,
        status="CREATED", queue_task_id=None, reference_build=parent.reference_build,
        configuration={
            **(parent.configuration or {}),
            "reanalysis": {
                "parent_analysis_id": str(parent.id),
                "trigger_type": trigger_type,
                "reason": reason,
                "earliest_affected_step": earliest,
                "reuse_through_step": _previous_step(earliest),
            },
        },
        started_at=None, completed_at=None, created_by=requested_by,
        analysis_version=next_version,
    )

    try:
        with db.begin_nested():
            db.add(child)
            db.flush()
            _copy_rows(db, parent.id, child.id, earliest)

            candidate = None
            if change_event_id:
                candidate = db.scalar(select(ReanalysisCandidate).where(
                    ReanalysisCandidate.parent_analysis_id == parent.id,
                    ReanalysisCandidate.change_event_id == change_event_id,
                ))
                if candidate:
                    candidate.child_analysis_id = child.id
                    candidate.status = "STARTED"
                    candidate.acted_at = _now()

            # Reserve exactly one quota unit with the child transaction.
            consume_analysis_quota(db, case.organization_id, commit=False)

            AuditService(db).record(
                event_type="REANALYSIS_REQUESTED",
                case_id=parent.case_id,
                analysis_id=child.id,
                actor_type="USER",
                actor_id=str(requested_by),
                subject_type="ANALYSIS",
                subject_id=str(child.id),
                operation="CREATE_REANALYSIS",
                before_state={
                    "parent_analysis_id": str(parent.id),
                    "parent_status": str(parent.status),
                    "parent_analysis_version": parent.analysis_version,
                },
                after_state={
                    "child_analysis_id": str(child.id),
                    "child_status": str(child.status),
                    "child_analysis_version": child.analysis_version,
                    "trigger_type": trigger_type,
                    "earliest_affected_step": earliest,
                },
                reason=reason,
                workflow={
                    "workflow_id": child.workflow_id,
                    "workflow_version": child.workflow_version,
                    "reuse_through_step": _previous_step(earliest),
                },
                payload={
                    "parent_analysis_id": str(parent.id),
                    "child_analysis_id": str(child.id),
                    "analysis_version": child.analysis_version,
                    "trigger_type": trigger_type,
                    "change_event_id": str(change_event_id) if change_event_id else None,
                },
            )
    except IntegrityError:
        duplicate = db.scalar(
            select(Analysis).where(
                Analysis.case_id == parent.case_id,
                Analysis.parent_analysis_id == parent.id,
                Analysis.analysis_version == next_version,
            )
        )
        if duplicate is None:
            raise
        candidate = None
        if change_event_id:
            candidate = db.scalar(select(ReanalysisCandidate).where(
                ReanalysisCandidate.parent_analysis_id == parent.id,
                ReanalysisCandidate.change_event_id == change_event_id,
            ))
        return duplicate, candidate

    db.commit()
    return child, candidate


def _previous_step(step: str) -> str | None:
    order = STEP_ORDER[step]
    previous = [name for name, value in STEP_ORDER.items() if value < order]
    return max(previous, key=lambda name: STEP_ORDER[name], default=None)


RESOURCE_TRIGGER_TYPE = {
    "REFERENCE": "REFERENCE_UPDATE",
    "POPULATION": "POPULATION_UPDATE",
    "ANNOTATION": "ANNOTATION_UPDATE",
    "EVIDENCE": "EVIDENCE_UPDATE",
    "ACMG_RULE": "ACMG_RULE_UPDATE",
}


def scan_active_resources_for_reanalysis(db: Session) -> int:
    """Detect changes for every active globally registered resource.

    This creates durable candidates/notifications only; it never starts a
    reanalysis automatically. The scan is safe to repeat because change
    events and parent/change-event candidates are idempotent.
    """
    resources = db.scalars(
        select(Resource).where(Resource.status == "ACTIVE").order_by(Resource.name, Resource.version)
    ).all()

    total_candidates = 0
    for resource in resources:
        trigger_type = RESOURCE_TRIGGER_TYPE.get(str(resource.resource_type).upper())
        if trigger_type is None:
            continue

        organization_ids = db.scalars(
            select(Case.organization_id)
            .join(Analysis, Analysis.case_id == Case.id)
            .join(
                AnalysisResourceSnapshot,
                AnalysisResourceSnapshot.analysis_id == Analysis.id,
            )
            .where(
                Analysis.status == "SUCCEEDED",
                AnalysisResourceSnapshot.resource_kind == str(resource.resource_type).upper(),
                AnalysisResourceSnapshot.resource_name == resource.name,
            )
            .distinct()
        ).all()

        for organization_id in organization_ids:
            candidates = detect_change(
                db,
                organization_id=organization_id,
                trigger_type=trigger_type,
                resource_kind=str(resource.resource_type).upper(),
                resource_name=resource.name,
                new_version=resource.version,
                new_checksum=resource.checksum,
                resource_id=resource.id,
            )
            total_candidates += len(candidates)

    return total_candidates
