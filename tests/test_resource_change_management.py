from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.resource_change_management import identify_resource_change_impacts
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    Case,
    Organization,
    Resource,
    ResourceChangeImpact,
    ResourceExecutionRecord,
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
            Case.__table__,
            Analysis.__table__,
            Resource.__table__,
            ResourceQualification.__table__,
            ResourceExecutionRecord.__table__,
            AuditEvent.__table__,
            ResourceChangeImpact.__table__,
        ],
    )
    return engine


def _resource(db, *, version: str):
    row = Resource(
        id=uuid4(),
        organization_id=None,
        name="FutureDB",
        provider="FutureProvider",
        resource_type="EVIDENCE",
        version=version,
        genome_build="GRCh38",
        access_method="LOCAL",
        license_text=None,
        checksum=("a" if version == "1" else "b") * 64,
        location=f"/db/{version}",
        status="QUALIFIED",
        population_definition=None,
        metadata_json={},
    )
    db.add(row)
    db.flush()
    q = ResourceQualification(
        id=uuid4(),
        resource_id=row.id,
        qualification_version="qualification-v1",
        status="QUALIFIED",
        checks_json={"passed": True},
        qualified_by=None,
    )
    db.add(q)
    db.flush()
    return row, q


def test_resource_adoption_creates_pending_impacts_for_historical_executions():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        user = User(
            id=uuid4(), organization_id=org.id, display_name="Director",
            role="lab_director", status="ACTIVE",
        )
        case = Case(
            id=uuid4(), organization_id=org.id, case_identifier="CASE-1",
            status="COMPLETED", clinical_context={}, language="en",
            created_by=user.id,
        )
        db.add_all([org, user, case])
        db.flush()

        analysis = Analysis(
            id=uuid4(), case_id=case.id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT", workflow_id="variant-analysis",
            workflow_version="1", status="COMPLETED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, created_by=user.id,
            analysis_version=1,
        )
        db.add(analysis)
        old, old_q = _resource(db, version="1")
        new, _ = _resource(db, version="2")

        execution = ResourceExecutionRecord(
            id=uuid4(), analysis_id=analysis.id, step_id="annotate", attempt=1,
            batch_key=None, resource_id=old.id, requested_resource_id=old.id,
            fallback_resource_id=None, qualification_id=old_q.id,
            qualification_version=old_q.qualification_version, resource_version=old.version,
            provider_id="FutureProvider", provider_version="1", access_method="LOCAL",
            endpoint=None, location=old.location, dataset=None, contract_hash="h",
            contract_json={"provider_id": "FutureProvider"}, status="SUCCEEDED",
            request_fingerprint="r", response_sha256="s",
        )
        db.add(execution)

        event = AuditEvent(
            id=uuid4(), event_version="1", event_type="RESOURCE_ADOPTION_DECISION",
            actor_type="USER", actor_id=str(user.id), subject_type="RESOURCE",
            subject_id=str(new.id), operation="APPROVED",
            before_state={"binding": {"resource_id": str(old.id), "version": "1"}},
            after_state={"binding": {"resource_id": str(new.id), "version": "2"}},
            reason="Adopt v2", software={}, workflow={
                "domain": "resource_registry", "organization_id": str(org.id),
                "approval_id": str(uuid4()), "approval_version": 2,
            },
            resource_versions={
                "requested": {"resource_id": str(new.id), "version": "2"},
                "previous": {"resource_id": str(old.id), "version": "1"},
                "resulting": {"resource_id": str(new.id), "version": "2"},
            },
            payload={}, event_hash="event-hash",
        )
        db.add(event)
        db.flush()

        result = identify_resource_change_impacts(db, adoption_event_id=event.id)
        assert result.impacted_analysis_ids == (analysis.id,)
        assert len(result.created_impact_ids) == 1

        impact = db.get(ResourceChangeImpact, result.created_impact_ids[0])
        assert impact is not None
        assert impact.status == "PENDING_REANALYSIS"
        assert impact.previous_resource_id == old.id
        assert impact.previous_resource_version == "1"
        assert impact.adopted_resource_id == new.id
        assert impact.adopted_resource_version == "2"

        again = identify_resource_change_impacts(db, adoption_event_id=event.id)
        assert again.impacted_analysis_ids == (analysis.id,)
        assert again.created_impact_ids == ()


def test_resource_change_impacts_are_tenant_scoped():
    engine = _engine()
    with Session(engine) as db:
        org_a = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        org_b = Organization(id=uuid4(), name="Lab B", external_identifier=None)
        user_a = User(
            id=uuid4(), organization_id=org_a.id, display_name="A",
            role="lab_director", status="ACTIVE",
        )
        user_b = User(
            id=uuid4(), organization_id=org_b.id, display_name="B",
            role="lab_director", status="ACTIVE",
        )
        db.add_all([org_a, org_b, user_a, user_b])
        db.flush()

        case_a = Case(
            id=uuid4(), organization_id=org_a.id, case_identifier="A-1",
            status="COMPLETED", clinical_context={}, language="en", created_by=user_a.id,
        )
        case_b = Case(
            id=uuid4(), organization_id=org_b.id, case_identifier="B-1",
            status="COMPLETED", clinical_context={}, language="en", created_by=user_b.id,
        )
        db.add_all([case_a, case_b])
        db.flush()

        analysis_a = Analysis(
            id=uuid4(), case_id=case_a.id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT", workflow_id="w", workflow_version="1",
            status="COMPLETED", queue_task_id=None, reference_build="GRCh38",
            configuration={}, created_by=user_a.id, analysis_version=1,
        )
        analysis_b = Analysis(
            id=uuid4(), case_id=case_b.id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT", workflow_id="w", workflow_version="1",
            status="COMPLETED", queue_task_id=None, reference_build="GRCh38",
            configuration={}, created_by=user_b.id, analysis_version=1,
        )
        db.add_all([analysis_a, analysis_b])
        old, old_q = _resource(db, version="1")
        new, _ = _resource(db, version="2")

        for analysis in (analysis_a, analysis_b):
            db.add(ResourceExecutionRecord(
                id=uuid4(), analysis_id=analysis.id, step_id="annotate", attempt=1,
                batch_key=None, resource_id=old.id, requested_resource_id=old.id,
                fallback_resource_id=None, qualification_id=old_q.id,
                qualification_version=old_q.qualification_version, resource_version=old.version,
                provider_id="FutureProvider", provider_version="1", access_method="LOCAL",
                endpoint=None, location=old.location, dataset=None, contract_hash="h",
                contract_json={}, status="SUCCEEDED",
            ))

        event = AuditEvent(
            id=uuid4(), event_version="1", event_type="RESOURCE_ADOPTION_DECISION",
            actor_type="USER", actor_id=str(user_a.id), subject_type="RESOURCE",
            subject_id=str(new.id), operation="APPROVED", before_state={},
            after_state={}, reason="Adopt", software={},
            workflow={"organization_id": str(org_a.id)},
            resource_versions={
                "previous": {"resource_id": str(old.id), "version": "1"},
                "resulting": {"resource_id": str(new.id), "version": "2"},
            },
            payload={}, event_hash="hash",
        )
        db.add(event)
        db.flush()

        result = identify_resource_change_impacts(db, adoption_event_id=event.id)
        assert result.impacted_analysis_ids == (analysis_a.id,)
