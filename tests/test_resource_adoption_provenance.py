from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.resources import (
    decide_resource_approval,
    qualify_resource_version,
    register_resource_version,
    request_resource_approval,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisResourceSnapshot,
    AuditEvent,
    Case,
    Notification,
    Organization,
    OrganizationMembership,
    OrganizationResourceBinding,
    ReanalysisCandidate,
    ReanalysisChangeEvent,
    Resource,
    ResourceApproval,
    ResourceApprovalAction,
    ResourceQualification,
    User,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            User.__table__,
            Resource.__table__,
            ResourceQualification.__table__,
            ResourceApproval.__table__,
            ResourceApprovalAction.__table__,
            OrganizationResourceBinding.__table__,
            Case.__table__,
            Analysis.__table__,
            AnalysisResourceSnapshot.__table__,
            OrganizationMembership.__table__,
            Notification.__table__,
            ReanalysisChangeEvent.__table__,
            ReanalysisCandidate.__table__,
            AuditEvent.__table__,
        ],
    )
    return engine


def _qualified(db, *, name: str, version: str, checksum: str):
    resource, _ = register_resource_version(
        db,
        name=name,
        provider="FutureProvider",
        resource_type="EVIDENCE",
        version=version,
        genome_build="GRCh38",
        access_method="OBJECT_STORAGE",
        license_text=None,
        checksum=checksum,
        location=f"blob://{name}/{version}",
        population_definition=None,
        initial_status="CANDIDATE",
    )
    qualify_resource_version(
        db,
        resource_id=resource.id,
        qualification_version="qualification-v1",
        checks={"passed": True, "integrity": "sha256"},
        qualified_by=None,
    )
    return resource


def test_approval_records_exact_release_transition_and_binding_provenance():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        user = User(
            id=uuid4(), organization_id=org.id, display_name="Director",
            role="lab_director", status="ACTIVE",
        )
        db.add_all([org, user])
        db.flush()

        old = _qualified(db, name="FutureDB", version="1", checksum="a" * 64)
        old_approval = request_resource_approval(
            db, resource_id=old.id, organization_id=org.id,
            qualification_version="qualification-v1",
        )
        decide_resource_approval(
            db, approval_id=old_approval.id, organization_id=org.id,
            actor_id=user.id, decision="APPROVED", expected_version=1,
            reason="Initial approved release",
        )

        new = _qualified(db, name="FutureDB", version="2", checksum="b" * 64)
        approval = request_resource_approval(
            db, resource_id=new.id, organization_id=org.id,
            qualification_version="qualification-v1",
        )
        decide_resource_approval(
            db, approval_id=approval.id, organization_id=org.id,
            actor_id=user.id, decision="APPROVED", expected_version=1,
            reason="Adopt validated release",
        )

        binding = db.scalar(select(OrganizationResourceBinding).where(
            OrganizationResourceBinding.organization_id == org.id,
            OrganizationResourceBinding.identity_key == "FutureDB|FutureProvider|EVIDENCE|GRCh38",
        ))
        assert binding is not None
        assert binding.resource_id == new.id
        assert binding.previous_resource_id == old.id
        assert binding.version == 2

        event = db.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "RESOURCE_ADOPTION_DECISION",
            AuditEvent.subject_id == str(new.id),
            AuditEvent.operation == "APPROVED",
        ))
        assert event is not None
        assert event.actor_id == str(user.id)
        assert event.reason == "Adopt validated release"
        assert event.resource_versions["requested"]["version"] == "2"
        assert event.resource_versions["previous"]["resource_id"] == str(old.id)
        assert event.resource_versions["previous"]["version"] == "1"
        assert event.resource_versions["resulting"]["resource_id"] == str(new.id)
        assert event.resource_versions["resulting"]["binding_version"] == 2
        assert event.payload["approval_id"] == str(approval.id)
        assert event.payload["qualification_id"] == str(approval.qualification_id)
        assert event.event_hash


def test_rejection_records_release_decision_without_changing_existing_binding():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        user = User(
            id=uuid4(), organization_id=org.id, display_name="Director",
            role="lab_director", status="ACTIVE",
        )
        db.add_all([org, user])
        db.flush()

        old = _qualified(db, name="FutureDB", version="1", checksum="c" * 64)
        old_approval = request_resource_approval(
            db, resource_id=old.id, organization_id=org.id,
            qualification_version="qualification-v1",
        )
        decide_resource_approval(
            db, approval_id=old_approval.id, organization_id=org.id,
            actor_id=user.id, decision="APPROVED", expected_version=1,
            reason="Baseline",
        )

        new = _qualified(db, name="FutureDB", version="2", checksum="d" * 64)
        approval = request_resource_approval(
            db, resource_id=new.id, organization_id=org.id,
            qualification_version="qualification-v1",
        )
        decide_resource_approval(
            db, approval_id=approval.id, organization_id=org.id,
            actor_id=user.id, decision="REJECTED", expected_version=1,
            reason="Release not adopted by laboratory",
        )

        binding = db.scalar(select(OrganizationResourceBinding).where(
            OrganizationResourceBinding.organization_id == org.id,
            OrganizationResourceBinding.identity_key == "FutureDB|FutureProvider|EVIDENCE|GRCh38",
        ))
        assert binding is not None
        assert binding.resource_id == old.id
        assert new.status == "REJECTED"

        event = db.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "RESOURCE_ADOPTION_DECISION",
            AuditEvent.subject_id == str(new.id),
            AuditEvent.operation == "REJECTED",
        ))
        assert event is not None
        assert event.resource_versions["requested"]["version"] == "2"
        assert event.resource_versions["previous"]["resource_id"] == str(old.id)
        assert event.resource_versions["previous"]["version"] == "1"
        assert event.resource_versions["resulting"] is None
        assert event.after_state["resource_status"] == "REJECTED"


def test_approved_release_creates_reanalysis_candidate_for_historical_analysis():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab Reanalysis", external_identifier=None)
        user = User(
            id=uuid4(), organization_id=org.id, display_name="Director",
            role="lab_director", status="ACTIVE",
        )
        case = Case(
            id=uuid4(), organization_id=org.id, case_identifier="REAN-ADOPT-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user.id,
        )
        db.add_all([org, user])
        db.flush()
        db.add(case)
        db.flush()

        old = _qualified(db, name="FutureDB", version="1", checksum="e" * 64)
        old_approval = request_resource_approval(
            db, resource_id=old.id, organization_id=org.id,
            qualification_version="qualification-v1",
        )
        decide_resource_approval(
            db, approval_id=old_approval.id, organization_id=org.id,
            actor_id=user.id, decision="APPROVED", expected_version=1,
            reason="Baseline",
        )

        analysis = Analysis(
            id=uuid4(), case_id=case.id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=None, created_by=user.id, analysis_version=1,
        )
        db.add(analysis)
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis.id, resource_id=old.id,
            resource_kind="EVIDENCE", resource_name="FutureDB", provider="FutureProvider",
            version="1", checksum="e" * 64, genome_build="GRCh38", metadata_json={},
        ))
        db.commit()

        new = _qualified(db, name="FutureDB", version="2", checksum="f" * 64)
        approval = request_resource_approval(
            db, resource_id=new.id, organization_id=org.id,
            qualification_version="qualification-v1",
        )
        decide_resource_approval(
            db, approval_id=approval.id, organization_id=org.id,
            actor_id=user.id, decision="APPROVED", expected_version=1,
            reason="Adopt validated release",
        )

        candidate = db.scalar(select(ReanalysisCandidate).where(
            ReanalysisCandidate.parent_analysis_id == analysis.id,
        ))
        assert candidate is not None
        assert candidate.trigger_type == "EVIDENCE_UPDATE"
        assert candidate.earliest_affected_step == "build_evidence"
        assert candidate.status == "PENDING"


def test_approved_release_after_rejections_reanalyzes_from_bound_release():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab Approval After Rejection", external_identifier=None)
        user = User(id=uuid4(), organization_id=org.id, display_name="Director", role="lab_director", status="ACTIVE")
        case = Case(id=uuid4(), organization_id=org.id, case_identifier="ADOPT-REJECT-001", status="ACTIVE", clinical_context={}, language="en", created_by=user.id)
        db.add_all([org, user, case])
        db.flush()
        baseline = _qualified(db, name="FutureDB", version="1", checksum="a" * 64)
        old_approval = request_resource_approval(db, resource_id=baseline.id, organization_id=org.id, qualification_version="qualification-v1")
        decide_resource_approval(db, approval_id=old_approval.id, organization_id=org.id, actor_id=user.id, decision="APPROVED", expected_version=1, reason="Baseline")
        analysis = Analysis(id=uuid4(), case_id=case.id, parent_analysis_id=None, assay_id=None, analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="2.1", status="SUCCEEDED", queue_task_id=None, reference_build="GRCh38", configuration={}, started_at=None, completed_at=None, created_by=user.id, analysis_version=1)
        db.add(analysis)
        db.add(AnalysisResourceSnapshot(id=uuid4(), analysis_id=analysis.id, resource_id=baseline.id, resource_kind="EVIDENCE", resource_name="FutureDB", provider="FutureProvider", version="1", checksum="a" * 64, genome_build="GRCh38", metadata_json={}))
        db.commit()
        for version, checksum in (("2", "b" * 64), ("3", "c" * 64)):
            candidate = _qualified(db, name="FutureDB", version=version, checksum=checksum)
            approval = request_resource_approval(db, resource_id=candidate.id, organization_id=org.id, qualification_version="qualification-v1")
            decide_resource_approval(db, approval_id=approval.id, organization_id=org.id, actor_id=user.id, decision="REJECTED", expected_version=1, reason=f"Reject release {version}")
        adopted = _qualified(db, name="FutureDB", version="4", checksum="d" * 64)
        approval = request_resource_approval(db, resource_id=adopted.id, organization_id=org.id, qualification_version="qualification-v1")
        decide_resource_approval(db, approval_id=approval.id, organization_id=org.id, actor_id=user.id, decision="APPROVED", expected_version=1, reason="Adopt release after rejected candidates")
        binding = db.scalar(select(OrganizationResourceBinding).where(OrganizationResourceBinding.organization_id == org.id, OrganizationResourceBinding.identity_key == "FutureDB|FutureProvider|EVIDENCE|GRCh38"))
        assert binding is not None
        assert binding.resource_id == adopted.id
        assert binding.previous_resource_id == baseline.id
        assert binding.version == 2
        candidates = db.scalars(select(ReanalysisCandidate).where(ReanalysisCandidate.parent_analysis_id == analysis.id)).all()
        assert len(candidates) == 1
        assert candidates[0].trigger_type == "EVIDENCE_UPDATE"
        assert candidates[0].earliest_affected_step == "build_evidence"
        assert candidates[0].status == "PENDING"
        events = db.scalars(select(ReanalysisChangeEvent)).all()
        assert len(events) == 1
        assert events[0].resource_id == adopted.id
        assert events[0].new_version == "4"
        assert events[0].new_checksum == "d" * 64


def test_multiple_rejected_releases_leave_bound_release_and_reanalysis_history_unchanged():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab Rejection", external_identifier=None)
        user = User(
            id=uuid4(), organization_id=org.id, display_name="Director",
            role="lab_director", status="ACTIVE",
        )
        case = Case(
            id=uuid4(), organization_id=org.id, case_identifier="REJECT-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user.id,
        )
        db.add_all([org, user, case])
        db.flush()

        baseline = _qualified(db, name="FutureDB", version="1", checksum="1" * 64)
        baseline_approval = request_resource_approval(
            db, resource_id=baseline.id, organization_id=org.id,
            qualification_version="qualification-v1",
        )
        decide_resource_approval(
            db, approval_id=baseline_approval.id, organization_id=org.id,
            actor_id=user.id, decision="APPROVED", expected_version=1,
            reason="Baseline",
        )

        analysis = Analysis(
            id=uuid4(), case_id=case.id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=None, created_by=user.id, analysis_version=1,
        )
        db.add(analysis)
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis.id, resource_id=baseline.id,
            resource_kind="EVIDENCE", resource_name="FutureDB", provider="FutureProvider",
            version="1", checksum="1" * 64, genome_build="GRCh38", metadata_json={},
        ))
        db.commit()

        for version, checksum in (("2", "2" * 64), ("3", "3" * 64)):
            candidate = _qualified(db, name="FutureDB", version=version, checksum=checksum)
            approval = request_resource_approval(
                db, resource_id=candidate.id, organization_id=org.id,
                qualification_version="qualification-v1",
            )
            decide_resource_approval(
                db, approval_id=approval.id, organization_id=org.id,
                actor_id=user.id, decision="REJECTED", expected_version=1,
                reason=f"Reject release {version}",
            )

        binding = db.scalar(select(OrganizationResourceBinding).where(
            OrganizationResourceBinding.organization_id == org.id,
            OrganizationResourceBinding.identity_key == "FutureDB|FutureProvider|EVIDENCE|GRCh38",
        ))
        assert binding is not None
        assert binding.resource_id == baseline.id
        assert db.query(ReanalysisCandidate).count() == 0
        assert db.query(ReanalysisChangeEvent).count() == 0
