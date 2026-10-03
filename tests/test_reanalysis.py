import pytest
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.resources import register_resource_version
from backend.app.domain.reanalysis import (
    affected_step_for_trigger,
    create_change_event,
    detect_change,
    scan_active_resources_for_reanalysis,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    AnalysisResourceSnapshot,
    Case,
    Notification,
    Organization,
    OrganizationMembership,
    ReanalysisCandidate,
    ReanalysisChangeEvent,
    Resource,
    User,
)


def test_manual_reanalysis_is_idempotent_and_consumes_one_quota_unit():
    from backend.app.application.entitlements import TRIAL_MAX_ANALYSES
    from backend.app.domain.reanalysis import create_reanalysis
    from backend.app.infrastructure.db.models import AuditEvent, OrganizationEntitlement

    engine = _engine()
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, Case.__table__, Analysis.__table__,
            OrganizationEntitlement.__table__, AuditEvent.__table__,
        ],
    )

    organization_id, case_id, parent_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Reanalysis Safety Lab", external_identifier=None))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="SAFETY-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        ))
        db.add(OrganizationEntitlement(
            id=uuid4(), organization_id=organization_id, plan="TRIAL", status="ACTIVE",
            max_analyses=TRIAL_MAX_ANALYSES, analyses_used=0,
        ))
        db.add(Analysis(
            id=parent_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=None, created_by=user_id, analysis_version=1,
        ))
        db.commit()

        parent = db.get(Analysis, parent_id)
        first, first_candidate = create_reanalysis(
            db, parent=parent, trigger_type="MANUAL", requested_by=user_id,
            reason="Laboratory-requested repeat analysis.",
        )
        entitlement = db.scalar(select(OrganizationEntitlement).where(OrganizationEntitlement.organization_id == organization_id))
        assert first.analysis_version == 2
        assert first.parent_analysis_id == parent_id
        assert first_candidate is None
        assert entitlement.analyses_used == 1
        assert db.query(AuditEvent).filter(AuditEvent.event_type == "REANALYSIS_REQUESTED").count() == 1

        second, second_candidate = create_reanalysis(
            db, parent=parent, trigger_type="MANUAL", requested_by=user_id,
            reason="Duplicate laboratory request.",
        )
        entitlement = db.scalar(select(OrganizationEntitlement).where(OrganizationEntitlement.organization_id == organization_id))
        assert second.id == first.id
        assert second_candidate is None
        assert entitlement.analyses_used == 1
        assert db.query(AuditEvent).filter(AuditEvent.event_type == "REANALYSIS_REQUESTED").count() == 1
        assert db.get(Analysis, parent_id).status == "SUCCEEDED"

        # A terminal child failure is retryable without creating a new lineage
        # version or consuming another analysis entitlement.
        first.status = "FAILED"
        db.add(first)
        db.commit()

        retry, retry_candidate = create_reanalysis(
            db, parent=parent, trigger_type="MANUAL", requested_by=user_id,
            reason="Retry the failed laboratory reanalysis.",
        )
        entitlement = db.scalar(select(OrganizationEntitlement).where(
            OrganizationEntitlement.organization_id == organization_id
        ))
        assert retry.id == first.id
        assert retry.analysis_version == first.analysis_version
        assert retry.status == "FAILED"
        assert retry_candidate is None
        assert entitlement.analyses_used == 1
        assert db.query(AuditEvent).filter(AuditEvent.event_type == "REANALYSIS_REQUESTED").count() == 1


def test_reanalysis_trigger_dependency_contract():
    assert affected_step_for_trigger("ANNOTATION_UPDATE") == "annotate"
    assert affected_step_for_trigger("POPULATION_UPDATE") == "population"
    assert affected_step_for_trigger("EVIDENCE_UPDATE") == "build_evidence"
    assert affected_step_for_trigger("ACMG_RULE_UPDATE") == "acmg_assessment"
    assert affected_step_for_trigger("REFERENCE_UPDATE") == "normalize"
    assert affected_step_for_trigger("MANUAL") == "normalize"


def _engine():
    return create_engine("sqlite+pysqlite:///:memory:")


def test_change_detector_creates_durable_candidate_and_notifications_idempotently():
    engine = _engine()
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, User.__table__, OrganizationMembership.__table__,
            Case.__table__, Analysis.__table__, AnalysisResourceSnapshot.__table__,
            ReanalysisChangeEvent.__table__, ReanalysisCandidate.__table__, Notification.__table__, AuditEvent.__table__,
        ],
    )

    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Reanalysis Test Lab", external_identifier=None))
        db.add(User(
            id=user_id, organization_id=organization_id, external_subject=None,
            email="analyst@test.local", display_name="Analyst", role="ANALYST", status="ACTIVE",
        ))
        db.add(OrganizationMembership(
            id=uuid4(), organization_id=organization_id, user_id=user_id,
            role="ANALYST", status="ACTIVE",
        ))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="REAN-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        ))
        db.add(Analysis(
            id=analysis_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=None, created_by=user_id, analysis_version=1,
        ))
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis_id, resource_id=None,
            resource_kind="POPULATION", resource_name="gnomAD",
            provider="gnomAD", version="v3.1.2", checksum="old",
            genome_build="GRCh38", metadata_json={},
        ))
        db.commit()

        candidates = detect_change(
            db, organization_id=organization_id, trigger_type="POPULATION_UPDATE",
            resource_kind="POPULATION", resource_name="gnomAD",
            new_version="v4.1", new_checksum="new",
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.earliest_affected_step == "population"
        assert candidate.status == "PENDING"

        notifications = db.query(Notification).filter(
            Notification.candidate_id == candidate.id
        ).all()
        assert len(notifications) == 1
        assert notifications[0].status == "UNREAD"

        # Re-registering the identical change must not create another candidate
        # or another notification.
        again = detect_change(
            db, organization_id=organization_id, trigger_type="POPULATION_UPDATE",
            resource_kind="POPULATION", resource_name="gnomAD",
            new_version="v4.1", new_checksum="new",
        )
        assert again == []
        assert db.query(ReanalysisCandidate).count() == 1
        assert db.query(Notification).count() == 1
        assert db.query(ReanalysisChangeEvent).count() == 1


def test_active_resource_scanner_detects_registered_resource_changes():
    engine = _engine()
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, User.__table__, OrganizationMembership.__table__,
            Case.__table__, Analysis.__table__, AnalysisResourceSnapshot.__table__,
            ReanalysisChangeEvent.__table__, ReanalysisCandidate.__table__, Notification.__table__,
            Resource.__table__,
        ],
    )

    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Scanner Test Lab", external_identifier=None))
        db.add(User(
            id=user_id, organization_id=organization_id, external_subject=None,
            email="scanner@test.local", display_name="Scanner", role="ANALYST", status="ACTIVE",
        ))
        db.add(OrganizationMembership(
            id=uuid4(), organization_id=organization_id, user_id=user_id,
            role="ANALYST", status="ACTIVE",
        ))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="SCAN-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        ))
        db.add(Analysis(
            id=analysis_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=None, created_by=user_id, analysis_version=1,
        ))
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis_id, resource_id=None,
            resource_kind="POPULATION", resource_name="gnomAD",
            provider="gnomAD", version="v3.1.2", checksum="old",
            genome_build="GRCh38", metadata_json={},
        ))
        db.add(Resource(
            id=uuid4(), name="gnomAD", provider="gnomAD", resource_type="POPULATION",
            version="v4.1", genome_build="GRCh38", access_method="GRAPHQL",
            license_text=None, checksum="new", location=None, status="ACTIVE",
            population_definition={}, metadata_json={},
        ))
        db.commit()

        created = scan_active_resources_for_reanalysis(db)
        assert created == 1
        assert db.query(ReanalysisCandidate).count() == 1
        candidate = db.query(ReanalysisCandidate).one()
        assert candidate.trigger_type == "POPULATION_UPDATE"
        assert candidate.earliest_affected_step == "population"
        assert db.query(Notification).count() == 1

        assert scan_active_resources_for_reanalysis(db) == 0
        assert db.query(ReanalysisCandidate).count() == 1
        assert db.query(Notification).count() == 1


def test_celery_reanalysis_scan_is_registered_on_daily_utc_schedule():
    from backend.app.infrastructure.queue.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["scan-reanalysis-resources-daily"]
    assert entry["task"] == "siraloom.scan_reanalysis_resources"
    assert entry["schedule"] == 86400.0
    assert celery_app.conf.timezone == "UTC"


def test_reanalysis_child_reuses_only_upstream_outputs_and_preserves_parent():
    from unittest.mock import patch

    from backend.app.domain.reanalysis import create_reanalysis
    from backend.app.infrastructure.db.models import (
        AuditEvent,
        AnalysisPartition,
        Annotation,
        Artifact,
        AuditEvent,
        Variant,
        WorkflowStep,
    )
    from backend.app.workflows.variant import _apply_reanalysis_reuse, ensure_steps

    engine = _engine()
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, User.__table__, OrganizationMembership.__table__,
            Case.__table__, Analysis.__table__, WorkflowStep.__table__,
            Artifact.__table__, AnalysisPartition.__table__, Variant.__table__,
            Annotation.__table__, AnalysisResourceSnapshot.__table__,
            ReanalysisChangeEvent.__table__, ReanalysisCandidate.__table__, Notification.__table__, AuditEvent.__table__,
        ],
    )

    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    variant_id, normalized_artifact_id = uuid4(), uuid4()

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Lifecycle Test Lab", external_identifier=None))
        db.add(User(
            id=user_id, organization_id=organization_id, external_subject=None,
            email="lifecycle@test.local", display_name="Lifecycle", role="ANALYST", status="ACTIVE",
        ))
        db.add(OrganizationMembership(
            id=uuid4(), organization_id=organization_id, user_id=user_id,
            role="ANALYST", status="ACTIVE",
        ))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="LIFE-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        ))
        db.add(Analysis(
            id=analysis_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38",
            configuration={"input_artifact_id": str(uuid4()), "reference_resource_id": str(uuid4())},
            started_at=None, completed_at=None, created_by=user_id, analysis_version=1,
        ))

        for step_id, order in (
            ("validate_input", 1), ("normalize", 2), ("annotate", 3),
            ("population", 4), ("build_evidence", 5),
        ):
            db.add(WorkflowStep(
                id=uuid4(), analysis_id=analysis_id, step_id=step_id, step_order=order,
                status="SUCCEEDED" if order <= 3 else "PENDING",
                attempt=1 if order <= 3 else 0,
                input_artifacts=[], output_artifacts=[],
                metadata_json={},
            ))

        db.add(Variant(
            id=variant_id, genome_build="GRCh38", chromosome="1", position=100,
            reference="A", alternate="G", normalization_status="NORMALIZED",
            canonical_key="GRCh38:1-100-A-G", identifiers={},
        ))
        db.add(Annotation(
            id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
            provider_name="GeneBe", provider_version="api-public-v1",
            resource_name="GeneBe", resource_version="api-public-v1", payload={"gene": "TEST"},
        ))
        db.add(Artifact(
            id=normalized_artifact_id, analysis_id=analysis_id, case_id=case_id,
            artifact_type="NORMALIZED_VCF", filename="normalized.vcf.gz",
            media_type="application/gzip", size_bytes=10, sha256="normalized-sha",
            storage_uri="file:///immutable/normalized.vcf.gz", genome_build="GRCh38",
            validation_status="VALIDATED", metadata_json={},
        ))
        db.add(AnalysisPartition(
            id=uuid4(), analysis_id=analysis_id, step_id="normalize",
            partition_key="part-0001", ordinal=0, record_start=1, record_end=1,
            variant_count=1, status="SUCCEEDED", input_artifact_id=None,
            metadata_json={}, resource_class="LIGHT", cpu_request=0.1,
            memory_mb=128, attempt=1,
        ))
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis_id, resource_id=None,
            resource_kind="POPULATION", resource_name="gnomAD",
            provider="gnomAD", version="v3.1.2", checksum="old",
            genome_build="GRCh38", metadata_json={},
        ))
        db.commit()

        candidates = detect_change(
            db, organization_id=organization_id, trigger_type="POPULATION_UPDATE",
            resource_kind="POPULATION", resource_name="gnomAD",
            new_version="v4.1", new_checksum="new",
        )
        candidate = candidates[0]

        with patch(
            "backend.app.application.entitlements.require_analysis_quota",
            return_value=None,
        ), patch(
            "backend.app.application.entitlements.consume_analysis_quota",
            return_value=None,
        ):
            child, linked_candidate = create_reanalysis(
                db,
                parent=db.get(Analysis, analysis_id),
                trigger_type="POPULATION_UPDATE",
                requested_by=user_id,
                reason="Population resource update.",
                change_event_id=candidate.change_event_id,
                affected_step="population",
            )

        assert child.parent_analysis_id == analysis_id
        assert child.analysis_version == 2
        assert linked_candidate is not None
        assert linked_candidate.child_analysis_id == child.id
        assert linked_candidate.status == "STARTED"

        ensure_steps(db, child.id)
        _apply_reanalysis_reuse(db, child)

        child_validation = db.scalar(select(WorkflowStep).where(
            WorkflowStep.analysis_id == child.id, WorkflowStep.step_id == "validate_input",
        ))
        child_normalize = db.scalar(select(WorkflowStep).where(
            WorkflowStep.analysis_id == child.id, WorkflowStep.step_id == "normalize",
        ))
        child_annotation = db.scalars(select(Annotation).where(
            Annotation.analysis_id == child.id,
        )).all()

        assert child_validation.status == "SUCCEEDED"
        assert child_normalize.status == "SUCCEEDED"
        assert child_annotation and child_annotation[0].payload == {"gene": "TEST"}

        # Population is the first affected stage, so its output is not inherited.
        assert db.query(AnalysisPartition).filter(
            AnalysisPartition.analysis_id == child.id,
            AnalysisPartition.step_id == "normalize",
        ).count() == 1
        assert db.query(AnalysisResourceSnapshot).filter(
            AnalysisResourceSnapshot.analysis_id == analysis_id,
        ).count() == 1
        assert db.get(Analysis, analysis_id).status == "SUCCEEDED"

def test_change_event_identity_is_stable_across_old_versions_and_checksum_only_updates():
    engine = _engine()
    Base.metadata.create_all(
        engine,
        tables=[Organization.__table__, ReanalysisChangeEvent.__table__],
    )
    organization_id = uuid4()

    with Session(engine) as db:
        first = create_change_event(
            db,
            organization_id=organization_id,
            trigger_type="POPULATION_UPDATE",
            resource_kind="POPULATION",
            resource_name="gnomAD",
            previous_version="v3.1.2",
            previous_checksum="old-a",
            new_version="v4.1",
            new_checksum="new",
        )
        db.commit()

        same_release_from_older_snapshot = create_change_event(
            db,
            organization_id=organization_id,
            trigger_type="POPULATION_UPDATE",
            resource_kind="POPULATION",
            resource_name="gnomAD",
            previous_version="v3.0",
            previous_checksum="old-b",
            new_version="v4.1",
            new_checksum="new",
        )
        assert same_release_from_older_snapshot.id == first.id
        assert db.query(ReanalysisChangeEvent).count() == 1

        checksum_only = create_change_event(
            db,
            organization_id=organization_id,
            trigger_type="POPULATION_UPDATE",
            resource_kind="POPULATION",
            resource_name="gnomAD",
            previous_version="v4.1",
            previous_checksum="new",
            new_version="v4.1",
            new_checksum="newer",
        )
        assert checksum_only.id != first.id
        assert db.query(ReanalysisChangeEvent).count() == 2

def test_registered_resource_release_drives_change_aware_candidate():
    engine = _engine()
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, User.__table__, OrganizationMembership.__table__,
            Case.__table__, Analysis.__table__, AnalysisResourceSnapshot.__table__,
            ReanalysisChangeEvent.__table__, ReanalysisCandidate.__table__, Notification.__table__,
            Resource.__table__,
        ],
    )
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Release Test Lab", external_identifier=None))
        db.add(User(
            id=user_id, organization_id=organization_id, external_subject=None,
            email="release@test.local", display_name="Release", role="ANALYST", status="ACTIVE",
        ))
        db.add(OrganizationMembership(
            id=uuid4(), organization_id=organization_id, user_id=user_id,
            role="ANALYST", status="ACTIVE",
        ))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="REL-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        ))

        old_resource, created = register_resource_version(
            db,
            name="gnomAD",
            provider="gnomAD",
            resource_type="POPULATION",
            version="v3.1.2",
            genome_build="GRCh38",
            access_method="OBJECT_STORAGE",
            license_text=None,
            checksum="a" * 64,
            location="blob://gnomad/v3.1.2",
            population_definition={"scope": "global"},
        )
        assert created is True

        db.add(Analysis(
            id=analysis_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=None, created_by=user_id, analysis_version=1,
        ))
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis_id, resource_id=old_resource.id,
            resource_kind="POPULATION", resource_name="gnomAD", provider="gnomAD",
            version="v3.1.2", checksum="a" * 64, genome_build="GRCh38", metadata_json={},
        ))
        db.commit()

        new_resource, created = register_resource_version(
            db,
            name="gnomAD",
            provider="gnomAD",
            resource_type="POPULATION",
            version="v4.1",
            genome_build="GRCh38",
            access_method="OBJECT_STORAGE",
            license_text=None,
            checksum="b" * 64,
            location="blob://gnomad/v4.1",
            population_definition={"scope": "global"},
        )
        assert created is True
        db.commit()

        assert scan_active_resources_for_reanalysis(db) == 1
        candidate = db.query(ReanalysisCandidate).one()
        assert candidate.parent_analysis_id == analysis_id
        assert candidate.earliest_affected_step == "population"
        assert candidate.status == "PENDING"
        notification = db.query(Notification).one()
        assert notification.candidate_id == candidate.id
        assert notification.metadata_json["new_version"] == "v4.1"

