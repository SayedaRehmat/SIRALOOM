from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from backend.app.auth.authorization import case_read_recipient_user_ids
from backend.app.domain.evidence import evidence_fingerprint
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    AnalysisResourceSnapshot,
    Annotation,
    Case,
    Evidence,
    InheritanceAssessment,
    Notification,
    PopulationObservation,
    ReanalysisCandidate,
    ReanalysisChangeEvent,
    Resource,
    SegregationObservation,
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


def _effective_reanalysis_start_step(
    db: Session, parent: Analysis, earliest_affected_step: str, *, profile_bound: bool
) -> tuple[str, str | None]:
    """Avoid reusing evidence-derived outputs when their consumed inputs are unknown.

    Analyses created before clinical-input snapshots cannot safely reuse evidence
    or any downstream result. Recompute from evidence while retaining eligible
    validation, normalization, annotation and population outputs.
    """
    if profile_bound:
        return "normalize", None
    if STEP_ORDER[earliest_affected_step] <= STEP_ORDER["build_evidence"]:
        return earliest_affected_step, None

    from backend.app.domain.clinical_input_snapshot import (
        saved_case_clinical_input_snapshot,
    )

    try:
        snapshot = saved_case_clinical_input_snapshot(db, parent.id)
    except ValueError:
        snapshot = None
    if snapshot is None:
        return "build_evidence", "PARENT_CLINICAL_INPUT_SNAPSHOT_MISSING_OR_INVALID"
    return earliest_affected_step, None


def mark_reanalysis_completed(db: Session, analysis: Analysis) -> bool:
    """Close a linked candidate when its child reaches successful completion.

    A queue recovery path can return a candidate to PENDING while retaining its
    child analysis. If that child is nevertheless delivered and completes, the
    linked child is authoritative and the candidate must be reconciled too.
    """
    candidates = list(db.scalars(
        select(ReanalysisCandidate).where(
            ReanalysisCandidate.child_analysis_id == analysis.id,
            ReanalysisCandidate.status.in_(("PENDING", "STARTED")),
        )
    ))
    if not candidates:
        return False
    for candidate in candidates:
        previous_status = candidate.status
        candidate.status = "COMPLETED"
        candidate.acted_at = candidate.acted_at or _now()
        db.add(candidate)
        AuditService(db).record(
            event_type="REANALYSIS_COMPLETED",
            case_id=analysis.case_id,
            analysis_id=analysis.id,
            actor_type="SYSTEM",
            actor_id="reanalysis",
            subject_type="REANALYSIS_CANDIDATE",
            subject_id=str(candidate.id),
            operation="COMPLETE_REANALYSIS",
            payload={
                "candidate_id": str(candidate.id),
                "parent_analysis_id": str(candidate.parent_analysis_id),
                "child_analysis_id": str(analysis.id),
                "previous_status": previous_status,
            },
        )
    return True


def snapshot_analysis_resources(db: Session, analysis: Analysis, *, commit: bool = True) -> int:
    """Persist the exact external resource identities observed by a completed analysis."""
    case = db.get(Case, analysis.case_id)
    if case is None:
        raise ValueError("Analysis resource provenance references a missing case")

    def resolve_resource(resource_id, *, source: str) -> Resource | None:
        if resource_id is None:
            return None
        resource = db.get(Resource, resource_id)
        if resource is None:
            raise ValueError(f"{source} references a missing resource")
        if resource.organization_id not in {None, case.organization_id}:
            raise ValueError(f"{source} references a resource outside the analysis organization")
        return resource

    existing_rows = db.scalars(
        select(AnalysisResourceSnapshot).where(
            AnalysisResourceSnapshot.analysis_id == analysis.id
        )
    ).all()
    if existing_rows:
        for snapshot in existing_rows:
            resolve_resource(
                snapshot.resource_id,
                source="Existing analysis resource snapshot",
            )
        return len(existing_rows)

    count = 0

    def already_snapshotted(seen, *, key, identity, source: str) -> bool:
        previous_identity = seen.get(key)
        if previous_identity is None:
            seen[key] = identity
            return False
        if previous_identity != identity:
            raise ValueError(
                f"{source} rows resolve to conflicting resources for the same snapshot identity"
            )
        return True

    reference_resource_id = (analysis.configuration or {}).get("reference_resource_id")
    if reference_resource_id:
        try:
            parsed_reference_resource_id = UUID(str(reference_resource_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("Analysis reference resource ID is invalid") from exc
        resource = resolve_resource(
            parsed_reference_resource_id,
            source="Analysis reference configuration",
        )
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
        resource = resolve_resource(rid, source="Population observation")
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
    seen = {}
    for row in annotations:
        registered_resource = resolve_resource(
            row.resource_id,
            source="Annotation",
        )
        resource_name = registered_resource.name if registered_resource else (row.resource_name or row.provider_name)
        provider = registered_resource.provider if registered_resource else row.provider_name
        version = row.resource_version or (registered_resource.version if registered_resource else None) or row.provider_version
        checksum = registered_resource.checksum if registered_resource else None
        key = ("ANNOTATION", resource_name, version, checksum)
        identity = (registered_resource.id if registered_resource else None, provider)
        if already_snapshotted(seen, key=key, identity=identity, source="Annotation"):
            continue
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis.id,
            resource_id=registered_resource.id if registered_resource else None,
            resource_kind="ANNOTATION",
            resource_name=resource_name,
            provider=provider,
            version=version,
            checksum=checksum,
            genome_build=analysis.reference_build,
            metadata_json={
                "provider_version": row.provider_version,
                "observed_resource_version": row.resource_version,
                "registered_resource_version": registered_resource.version if registered_resource else None,
            },
        ))
        count += 1

    evidence = db.scalars(select(Evidence).where(Evidence.analysis_id == analysis.id)).all()
    seen = {}
    for row in evidence:
        if not row.source_name:
            continue
        registered_resource = resolve_resource(
            row.resource_id,
            source="Evidence",
        )
        resource_name = registered_resource.name if registered_resource else row.source_name
        provider = registered_resource.provider if registered_resource else None
        version = row.source_version or (registered_resource.version if registered_resource else None)
        checksum = registered_resource.checksum if registered_resource else None
        key = ("EVIDENCE", resource_name, version, checksum)
        identity = (registered_resource.id if registered_resource else None, provider)
        if already_snapshotted(seen, key=key, identity=identity, source="Evidence"):
            continue
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis.id,
            resource_id=registered_resource.id if registered_resource else None,
            resource_kind="EVIDENCE",
            resource_name=resource_name,
            provider=provider,
            version=version,
            checksum=checksum,
            genome_build=analysis.reference_build,
            metadata_json={
                "source_version": row.source_version,
                "registered_resource_version": registered_resource.version if registered_resource else None,
            },
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
        specification_version = row.specification_version or row.framework_version
        registered_resource = db.scalar(
            select(Resource).where(
                Resource.name == row.specification_id,
                Resource.version == specification_version,
                Resource.provider == row.specification_provider,
                or_(
                    Resource.organization_id.is_(None),
                    Resource.organization_id == case.organization_id,
                ),
            ).limit(1)
        )
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis.id,
            resource_id=registered_resource.id if registered_resource else None,
            resource_kind="ACMG_RULE",
            resource_name=registered_resource.name if registered_resource else row.specification_id,
            provider=registered_resource.provider if registered_resource else row.specification_provider,
            version=specification_version,
            checksum=registered_resource.checksum if registered_resource else None,
            genome_build=analysis.reference_build,
            metadata_json={
                "framework_name": row.framework_name,
                "framework_version": row.framework_version,
                "registered_resource_version": registered_resource.version if registered_resource else None,
            },
        ))
        count += 1

    if commit:
        db.commit()
    return count


def _change_fingerprint(*, organization_id: UUID, trigger_type: str, resource_kind: str, resource_name: str, new_version: str | None, new_checksum: str | None) -> str:
    material = "\x1f".join([str(organization_id), trigger_type, resource_kind, resource_name, new_version or "", new_checksum or ""])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def create_change_event(db: Session, *, organization_id: UUID, trigger_type: str, resource_kind: str, resource_name: str, new_version: str | None, new_checksum: str | None, previous_version: str | None = None, previous_checksum: str | None = None, resource_id: UUID | None = None) -> ReanalysisChangeEvent:
    fingerprint = _change_fingerprint(organization_id=organization_id, trigger_type=trigger_type, resource_kind=resource_kind, resource_name=resource_name, new_version=new_version, new_checksum=new_checksum)
    existing = db.scalar(select(ReanalysisChangeEvent).where(ReanalysisChangeEvent.change_fingerprint == fingerprint))
    if existing:
        return existing
    event = ReanalysisChangeEvent(id=uuid4(), change_fingerprint=fingerprint, organization_id=organization_id, resource_id=resource_id, trigger_type=trigger_type, resource_kind=resource_kind, resource_name=resource_name, previous_version=previous_version, new_version=new_version, previous_checksum=previous_checksum, new_checksum=new_checksum, metadata_json={})
    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
    except IntegrityError:
        existing = db.scalar(select(ReanalysisChangeEvent).where(ReanalysisChangeEvent.change_fingerprint == fingerprint))
        if existing is None:
            raise
        return existing
    return event


def detect_change(db: Session, *, organization_id: UUID, trigger_type: str, resource_kind: str, resource_name: str, new_version: str | None, new_checksum: str | None, resource_id: UUID | None = None, commit: bool = True) -> list[ReanalysisCandidate]:
    statement = (
        select(AnalysisResourceSnapshot)
        .join(Analysis, Analysis.id == AnalysisResourceSnapshot.analysis_id)
        .join(Case, Case.id == Analysis.case_id)
        .where(
            Case.organization_id == organization_id,
            Analysis.status == "SUCCEEDED",
            AnalysisResourceSnapshot.resource_kind == resource_kind,
            AnalysisResourceSnapshot.resource_name == resource_name,
        )
    )
    if resource_id is not None:
        snapshot_resource = aliased(Resource)
        statement = statement.outerjoin(
            snapshot_resource, snapshot_resource.id == AnalysisResourceSnapshot.resource_id
        )
        changed_resource = db.get(Resource, resource_id)
        if changed_resource is None:
            return []
        if changed_resource.organization_id is not None:
            if changed_resource.organization_id != organization_id:
                return []
            ownership_scope = or_(
                and_(
                    snapshot_resource.organization_id == organization_id,
                    snapshot_resource.provider == changed_resource.provider,
                ),
                and_(
                    AnalysisResourceSnapshot.resource_id.is_(None),
                    AnalysisResourceSnapshot.provider == changed_resource.provider,
                ),
            )
        else:
            ownership_scope = or_(
                and_(
                    snapshot_resource.organization_id.is_(None),
                    snapshot_resource.provider == changed_resource.provider,
                ),
                and_(
                    AnalysisResourceSnapshot.resource_id.is_(None),
                    AnalysisResourceSnapshot.provider == changed_resource.provider,
                ),
            )
        statement = statement.where(ownership_scope)
    snapshots = db.scalars(statement).all()
    candidates: list[ReanalysisCandidate] = []
    notification_recipients: dict[UUID, set[UUID]] = {}
    for snapshot in snapshots:
        if snapshot.version == new_version and snapshot.checksum == new_checksum:
            continue
        event = create_change_event(db, organization_id=organization_id, trigger_type=trigger_type, resource_kind=resource_kind, resource_name=resource_name, new_version=new_version, new_checksum=new_checksum, previous_version=snapshot.version, previous_checksum=snapshot.checksum, resource_id=resource_id)
        parent = db.get(Analysis, snapshot.analysis_id)
        if not parent:
            continue
        candidate = db.scalar(select(ReanalysisCandidate).where(ReanalysisCandidate.parent_analysis_id == parent.id, ReanalysisCandidate.change_event_id == event.id))
        if candidate:
            continue
        candidate = ReanalysisCandidate(id=uuid4(), organization_id=organization_id, case_id=parent.case_id, parent_analysis_id=parent.id, change_event_id=event.id, trigger_type=trigger_type, earliest_affected_step=affected_step_for_trigger(trigger_type), reason=f"{resource_kind} resource '{resource_name}' changed from {snapshot.version or 'unversioned'} to {new_version or 'unversioned'}.", status="PENDING")
        created_candidate = False
        try:
            with db.begin_nested():
                db.add(candidate)
                db.flush()
            created_candidate = True
        except IntegrityError:
            candidate = db.scalar(select(ReanalysisCandidate).where(ReanalysisCandidate.parent_analysis_id == parent.id, ReanalysisCandidate.change_event_id == event.id))
            if candidate is None:
                raise
        if created_candidate:
            if parent.case_id not in notification_recipients:
                notification_recipients[parent.case_id] = case_read_recipient_user_ids(
                    db,
                    case_id=parent.case_id,
                    organization_id=organization_id,
                )
            users = notification_recipients[parent.case_id]
            for user_id in users:
                db.add(Notification(id=uuid4(), organization_id=organization_id, user_id=user_id, notification_type="REANALYSIS_CANDIDATE", status="UNREAD", title="Case reanalysis may be required", body=candidate.reason, case_id=parent.case_id, analysis_id=parent.id, candidate_id=candidate.id, metadata_json={"trigger_type": trigger_type, "resource_kind": resource_kind, "resource_name": resource_name, "previous_version": snapshot.version, "new_version": new_version, "earliest_affected_step": candidate.earliest_affected_step}))
            candidates.append(candidate)
    if commit:
        db.commit()
    return candidates


def _copy_rows(db: Session, parent_id: UUID, child_id: UUID, earliest: str) -> None:
    start = STEP_ORDER[earliest]
    population_observation_ids: dict[str, str] = {}
    segregation_observation_ids: dict[str, str] = {}
    evidence_ids: dict[str, str] = {}
    if start > STEP_ORDER["annotate"]:
        for row in db.scalars(select(Annotation).where(Annotation.analysis_id == parent_id)).all():
            db.add(Annotation(id=uuid4(), variant_id=row.variant_id, analysis_id=child_id, provider_name=row.provider_name, provider_version=row.provider_version, resource_id=row.resource_id, resource_name=row.resource_name, resource_version=row.resource_version, request_fingerprint=row.request_fingerprint, response_sha256=row.response_sha256, request_metadata=dict(row.request_metadata or {}), observed_at=row.observed_at, retry_count=row.retry_count, payload=row.payload))
    if start > STEP_ORDER["population"]:
        for row in db.scalars(select(PopulationObservation).where(PopulationObservation.analysis_id == parent_id)).all():
            copied = PopulationObservation(id=uuid4(), analysis_id=child_id, variant_id=row.variant_id, resource_id=row.resource_id, population_level=row.population_level, population_code=row.population_code, population_label=row.population_label, allele_count=row.allele_count, allele_number=row.allele_number, allele_frequency=row.allele_frequency, homozygote_count=row.homozygote_count, availability=row.availability, quality_status=row.quality_status, source_record_id=row.source_record_id, request_fingerprint=row.request_fingerprint, response_sha256=row.response_sha256, request_metadata=dict(row.request_metadata or {}), observed_at=row.observed_at)
            population_observation_ids[str(row.id)] = str(copied.id)
            db.add(copied)
    if start > STEP_ORDER["build_evidence"]:
        from backend.app.acmg.source_assertions import persist_clingen_source_assertions

        for row in db.scalars(
            select(SegregationObservation).where(
                SegregationObservation.analysis_id == parent_id
            )
        ).all():
            copied = SegregationObservation(
                id=uuid4(), analysis_id=child_id, variant_id=row.variant_id,
                pedigree_member_id=row.pedigree_member_id, genotype=row.genotype,
                zygosity=row.zygosity, phase=row.phase,
                allele_observed=row.allele_observed,
                phenotype_status=row.phenotype_status, source=row.source,
                notes=row.notes, metadata_json=dict(row.metadata_json or {}),
                created_at=row.created_at,
            )
            segregation_observation_ids[str(row.id)] = str(copied.id)
            db.add(copied)

        for row in db.scalars(
            select(InheritanceAssessment).where(
                InheritanceAssessment.analysis_id == parent_id
            )
        ).all():
            db.add(InheritanceAssessment(
                id=uuid4(), analysis_id=child_id, variant_id=row.variant_id,
                model=row.model, status=row.status, score=row.score,
                rationale=row.rationale,
                observation_fingerprint=row.observation_fingerprint,
                reviewer_note=row.reviewer_note, created_by=row.created_by,
                created_at=row.created_at,
            ))

        for row in db.scalars(select(Evidence).where(Evidence.analysis_id == parent_id)).all():
            observation_ids = []
            for observation_id in row.observation_ids or []:
                observation_id = str(observation_id)
                copied_id = population_observation_ids.get(observation_id)
                if copied_id is None:
                    copied_id = segregation_observation_ids.get(observation_id)
                if copied_id is None:
                    raise ValueError(
                        "Reused evidence references an observation outside its parent analysis"
                    )
                observation_ids.append(copied_id)
            try:
                fingerprint_observation_ids = tuple(UUID(value) for value in observation_ids)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Reused evidence contains an invalid observation identifier"
                ) from exc
            copied = Evidence(
                id=uuid4(), variant_id=row.variant_id, analysis_id=child_id,
                evidence_type=row.evidence_type, statement=row.statement,
                direction=row.direction, source_name=row.source_name,
                source_version=row.source_version, resource_id=row.resource_id,
                source_record_id=row.source_record_id,
                request_fingerprint=row.request_fingerprint,
                response_sha256=row.response_sha256,
                request_metadata=dict(row.request_metadata or {}),
                observed_at=row.observed_at, observation_ids=observation_ids,
                payload=row.payload, created_by_type=row.created_by_type,
                created_by_id=row.created_by_id,
                evidence_fingerprint=evidence_fingerprint(
                    variant_id=row.variant_id,
                    analysis_id=child_id,
                    evidence_type=row.evidence_type,
                    statement=row.statement,
                    direction=row.direction,
                    source_name=row.source_name,
                    source_version=row.source_version,
                    observation_ids=fingerprint_observation_ids,
                    payload=row.payload,
                    resource_id=row.resource_id,
                    source_record_id=row.source_record_id,
                    request_fingerprint=row.request_fingerprint,
                    response_sha256=row.response_sha256,
                ),
            )
            evidence_ids[str(row.id)] = str(copied.id)
            db.add(copied)
            persist_clingen_source_assertions(db, evidence=copied)
    if start > STEP_ORDER["acmg_assessment"]:
        for row in db.scalars(select(ACMGAssessment).where(ACMGAssessment.analysis_id == parent_id)).all():
            automated_assessment = dict(row.automated_assessment or {})
            source_evidence_ids = automated_assessment.get("evidence_ids")
            if source_evidence_ids is not None:
                if not isinstance(source_evidence_ids, list):
                    raise ValueError(
                        "Reused ACMG assessment evidence_ids must be a list"
                    )
                try:
                    automated_assessment["evidence_ids"] = [
                        evidence_ids[str(evidence_id)]
                        for evidence_id in source_evidence_ids
                    ]
                except KeyError as exc:
                    raise ValueError(
                        "Reused ACMG assessment references evidence outside its parent analysis"
                    ) from exc
            db.add(ACMGAssessment(id=uuid4(), variant_id=row.variant_id, analysis_id=child_id, framework_name=row.framework_name, framework_version=row.framework_version, specification_provider=row.specification_provider, specification_id=row.specification_id, specification_version=row.specification_version, criterion=row.criterion, automated_assessment=automated_assessment, reviewed_assessment=None, final_assessment=None, state="DRAFT", review_version=0))
    db.flush()


def create_reanalysis(db: Session, *, parent: Analysis, trigger_type: str, requested_by: UUID, reason: str, change_event_id: UUID | None = None, affected_step: str | None = None) -> tuple[Analysis, ReanalysisCandidate | None]:
    if parent.status != "SUCCEEDED":
        raise ValueError("Only a successfully completed analysis can be reanalyzed.")
    earliest = affected_step or affected_step_for_trigger(trigger_type)
    profile_bound = bool((parent.configuration or {}).get("resource_profile_id"))
    execution_start_step, forced_replay_reason = _effective_reanalysis_start_step(
        db, parent, earliest, profile_bound=profile_bound
    )
    next_version = (parent.analysis_version or 1) + 1
    duplicate = db.scalar(select(Analysis).where(Analysis.case_id == parent.case_id, Analysis.parent_analysis_id == parent.id, Analysis.analysis_version == next_version))
    if duplicate:
        candidate = db.scalar(select(ReanalysisCandidate).where(ReanalysisCandidate.child_analysis_id == duplicate.id)) if change_event_id else None
        return duplicate, candidate
    case = db.get(Case, parent.case_id)
    child_configuration = dict(parent.configuration or {})
    child_configuration["reanalysis"] = {
        "parent_analysis_id": str(parent.id),
        "trigger_type": trigger_type,
        "reason": reason,
        "earliest_affected_step": earliest,
        "execution_start_step": execution_start_step,
        "reuse_through_step": _previous_step(execution_start_step),
        "resource_plan_policy": "FULL_REPLAY_FROM_NORMALIZATION" if profile_bound else "INCREMENTAL_REUSE",
        **({"forced_replay_reason": forced_replay_reason} if forced_replay_reason else {}),
    }
    child = Analysis(id=uuid4(), case_id=parent.case_id, parent_analysis_id=parent.id, assay_id=parent.assay_id, analysis_type=parent.analysis_type, workflow_id=parent.workflow_id, workflow_version=parent.workflow_version, status="CREATED", queue_task_id=None, reference_build=parent.reference_build, configuration=child_configuration, started_at=None, completed_at=None, created_by=requested_by, analysis_version=next_version)
    try:
        with db.begin_nested():
            db.add(child)
            db.flush()
            _copy_rows(db, parent.id, child.id, execution_start_step)
            candidate = None
            if change_event_id:
                candidate = db.scalar(select(ReanalysisCandidate).where(ReanalysisCandidate.parent_analysis_id == parent.id, ReanalysisCandidate.change_event_id == change_event_id))
                if candidate:
                    candidate.child_analysis_id = child.id
                    candidate.status = "STARTED"
                    candidate.acted_at = _now()
            from backend.app.application.entitlements import consume_analysis_quota
            consume_analysis_quota(db, case.organization_id, commit=False)
            AuditService(db).record(event_type="REANALYSIS_REQUESTED", case_id=parent.case_id, analysis_id=child.id, actor_type="USER", actor_id=str(requested_by), subject_type="ANALYSIS", subject_id=str(child.id), operation="CREATE_REANALYSIS", before_state={"parent_analysis_id": str(parent.id), "parent_status": str(parent.status), "parent_analysis_version": parent.analysis_version}, after_state={"child_analysis_id": str(child.id), "child_status": str(child.status), "child_analysis_version": child.analysis_version, "trigger_type": trigger_type, "earliest_affected_step": earliest, "execution_start_step": execution_start_step, "forced_replay_reason": forced_replay_reason}, reason=reason, workflow={"workflow_id": child.workflow_id, "workflow_version": child.workflow_version, "reuse_through_step": _previous_step(execution_start_step)}, payload={"parent_analysis_id": str(parent.id), "child_analysis_id": str(child.id), "analysis_version": child.analysis_version, "trigger_type": trigger_type, "change_event_id": str(change_event_id) if change_event_id else None})
    except IntegrityError:
        duplicate = db.scalar(select(Analysis).where(Analysis.case_id == parent.case_id, Analysis.parent_analysis_id == parent.id, Analysis.analysis_version == next_version))
        if duplicate is None:
            raise
        candidate = db.scalar(select(ReanalysisCandidate).where(ReanalysisCandidate.parent_analysis_id == parent.id, ReanalysisCandidate.change_event_id == change_event_id)) if change_event_id else None
        return duplicate, candidate
    db.commit()
    return child, candidate


def _previous_step(step: str) -> str | None:
    order = STEP_ORDER[step]
    previous = [name for name, value in STEP_ORDER.items() if value < order]
    return max(previous, key=lambda name: STEP_ORDER[name], default=None)


RESOURCE_TRIGGER_TYPE = {"REFERENCE": "REFERENCE_UPDATE", "POPULATION": "POPULATION_UPDATE", "ANNOTATION": "ANNOTATION_UPDATE", "EVIDENCE": "EVIDENCE_UPDATE", "ACMG_RULE": "ACMG_RULE_UPDATE"}


def scan_active_resources_for_reanalysis(
    db: Session, *, organization_id: UUID | None = None
) -> int:
    """Create candidates for active resource changes.

    The daily system scan is global. A scan requested by a laboratory resource
    activation is scoped to that organization, including shared resources used
    by its analyses, so a tenant action cannot create another lab's candidates.
    """
    requested_organization_id = organization_id
    resource_query = select(Resource).where(Resource.status == "ACTIVE")
    if requested_organization_id is not None:
        resource_query = resource_query.where(
            or_(
                Resource.organization_id.is_(None),
                Resource.organization_id == requested_organization_id,
            )
        )
    resources = db.scalars(
        resource_query.order_by(Resource.name, Resource.version)
    ).all()
    total_candidates = 0
    for resource in resources:
        trigger_type = RESOURCE_TRIGGER_TYPE.get(str(resource.resource_type).upper())
        if trigger_type is None:
            continue
        if resource.organization_id is not None:
            organization_ids = [resource.organization_id]
        elif requested_organization_id is not None:
            organization_ids = [requested_organization_id]
        else:
            snapshot_resource = aliased(Resource)
            organization_ids = db.scalars(
                select(Case.organization_id)
                .join(Analysis, Analysis.case_id == Case.id)
                .join(AnalysisResourceSnapshot, AnalysisResourceSnapshot.analysis_id == Analysis.id)
                .outerjoin(snapshot_resource, snapshot_resource.id == AnalysisResourceSnapshot.resource_id)
                .where(
                    Analysis.status == "SUCCEEDED",
                    AnalysisResourceSnapshot.resource_kind == str(resource.resource_type).upper(),
                    AnalysisResourceSnapshot.resource_name == resource.name,
                    or_(
                        and_(
                            snapshot_resource.organization_id.is_(None),
                            snapshot_resource.provider == resource.provider,
                        ),
                        and_(
                            AnalysisResourceSnapshot.resource_id.is_(None),
                            AnalysisResourceSnapshot.provider == resource.provider,
                        ),
                    ),
                )
                .distinct()
                .order_by(Case.organization_id)
            ).all()
        for candidate_organization_id in organization_ids:
            candidates = detect_change(db, organization_id=candidate_organization_id, trigger_type=trigger_type, resource_kind=str(resource.resource_type).upper(), resource_name=resource.name, new_version=resource.version, new_checksum=resource.checksum, resource_id=resource.id)
            total_candidates += len(candidates)
    return total_candidates
