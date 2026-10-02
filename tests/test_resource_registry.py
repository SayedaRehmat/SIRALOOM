from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.resources import (
    ResourceRegistryError,
    activate_resource_version,
    decide_resource_approval,
    get_active_resource_for_organization,
    qualify_resource_version,
    register_resource_version,
    request_resource_approval,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis, Case, Organization, OrganizationResourceBinding, Resource, ResourceApproval,
    ResourceApprovalAction, ResourceQualification, ResourceExecutionRecord, User, AuditEvent,
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
            ResourceApproval.__table__,
            ResourceApprovalAction.__table__,
            OrganizationResourceBinding.__table__,
            AuditEvent.__table__,
            ResourceExecutionRecord.__table__,
        ],
    )
    return engine


def test_resource_registry_is_idempotent_and_supersedes_prior_active_version():
    engine = _engine()
    with Session(engine) as db:
        first, created = register_resource_version(
            db,
            name="gnomAD",
            provider="gnomAD",
            resource_type="POPULATION",
            version="v3.1.2",
            genome_build="GRCh38",
            access_method="OBJECT_STORAGE",
            license_text=None,
            checksum="a" * 64,
            location="blob://resources/gnomad/v3.1.2",
            population_definition={"scope": "global"},
        )
        assert created is True
        db.commit()

        same, created = register_resource_version(
            db,
            name="gnomAD",
            provider="gnomAD",
            resource_type="POPULATION",
            version="v3.1.2",
            genome_build="GRCh38",
            access_method="OBJECT_STORAGE",
            license_text=None,
            checksum="a" * 64,
            location="blob://resources/gnomad/v3.1.2",
            population_definition={"scope": "global"},
        )
        assert created is False
        assert same.id == first.id

        second, created = register_resource_version(
            db,
            name="gnomAD",
            provider="gnomAD",
            resource_type="POPULATION",
            version="v4.1",
            genome_build="GRCh38",
            access_method="OBJECT_STORAGE",
            license_text=None,
            checksum="b" * 64,
            location="blob://resources/gnomad/v4.1",
            population_definition={"scope": "global"},
        )
        assert created is True
        db.commit()

        db.refresh(first)
        assert first.status == "SUPERSEDED"
        assert second.status == "ACTIVE"


def test_discovered_resource_stays_candidate_until_qualified_and_activated():
    engine = _engine()
    with Session(engine) as db:
        resource, created = register_resource_version(
            db,
            name="FutureDB",
            provider="FutureProvider",
            resource_type="EVIDENCE",
            version="2026.10",
            genome_build="GRCh38",
            access_method="OBJECT_STORAGE",
            license_text=None,
            checksum="c" * 64,
            location="blob://future/2026.10",
            population_definition=None,
            initial_status="CANDIDATE",
        )
        assert created is True
        assert resource.status == "CANDIDATE"

        qualification = qualify_resource_version(
            db,
            resource_id=resource.id,
            qualification_version="resource-qualification-v1",
            checks={"passed": True, "golden_dataset": "golden-001"},
            qualified_by=None,
        )
        assert qualification.status == "QUALIFIED"
        assert resource.status == "QUALIFIED"

        activate_resource_version(
            db,
            resource_id=resource.id,
            qualification_version="resource-qualification-v1",
        )
        assert resource.status == "ACTIVE"


def test_unqualified_resource_cannot_be_activated():
    engine = _engine()
    with Session(engine) as db:
        resource, _ = register_resource_version(
            db,
            name="FutureTool",
            provider="FutureProvider",
            resource_type="ANNOTATION",
            version="1.0",
            genome_build="GRCh38",
            access_method="LOCAL",
            license_text=None,
            checksum="d" * 64,
            location="/opt/future-tool",
            population_definition=None,
            initial_status="CANDIDATE",
        )
        try:
            activate_resource_version(
                db,
                resource_id=resource.id,
                qualification_version="missing",
            )
        except ResourceRegistryError as exc:
            assert "QUALIFIED" in str(exc)
        else:
            raise AssertionError("unqualified resource must not activate")


def test_resource_registry_rejects_invalid_checksum_and_type():
    engine = _engine()
    with Session(engine) as db:
        kwargs = dict(
            name="x",
            provider="x",
            version="1",
            genome_build="GRCh38",
            access_method="OBJECT_STORAGE",
            license_text=None,
            checksum="bad",
            location=None,
            population_definition=None,
        )
        try:
            register_resource_version(db, resource_type="POPULATION", **kwargs)
        except ResourceRegistryError:
            pass
        else:
            raise AssertionError("invalid checksum must be rejected")

        kwargs["checksum"] = "a" * 64
        try:
            register_resource_version(db, resource_type="UNKNOWN", **kwargs)
        except ResourceRegistryError:
            pass
        else:
            raise AssertionError("unsupported resource type must be rejected")


def test_tenant_scoped_active_resources_are_isolated():
    engine = _engine()
    with Session(engine) as db:
        org_a = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        org_b = Organization(id=uuid4(), name="Lab B", external_identifier=None)
        db.add_all([org_a, org_b])
        db.flush()

        first, _ = register_resource_version(
            db,
            organization_id=org_a.id,
            name="LabDB",
            provider="Lab",
            resource_type="EVIDENCE",
            version="1",
            genome_build="GRCh38",
            access_method="LOCAL",
            license_text=None,
            checksum="e" * 64,
            location="/lab-a/db",
            population_definition=None,
        )
        second, _ = register_resource_version(
            db,
            organization_id=org_b.id,
            name="LabDB",
            provider="Lab",
            resource_type="EVIDENCE",
            version="1",
            genome_build="GRCh38",
            access_method="LOCAL",
            license_text=None,
            checksum="f" * 64,
            location="/lab-b/db",
            population_definition=None,
        )
        assert first.organization_id == org_a.id
        assert second.organization_id == org_b.id
        assert first.status == "ACTIVE"
        assert second.status == "ACTIVE"



def _candidate(db, *, name, version, checksum, org=None):
    resource, _ = register_resource_version(
        db,
        organization_id=org,
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
        checks={"passed": True, "integrity": "sha256", "golden_dataset": "golden-001"},
        qualified_by=None,
    )
    return resource


def test_organization_approval_is_distinct_from_technical_qualification():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        db.add(org)
        db.flush()
        resource = _candidate(db, name="FutureDB", version="2", checksum="a" * 64)
        approval = request_resource_approval(
            db,
            resource_id=resource.id,
            organization_id=org.id,
            qualification_version="qualification-v1",
        )
        assert resource.status == "QUALIFIED"
        assert approval.status == "PENDING"
        assert approval.version == 1
        assert db.scalar(select(OrganizationResourceBinding).where(
            OrganizationResourceBinding.organization_id == org.id
        )) is None


def test_reject_and_defer_leave_existing_active_binding_unchanged():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        user = User(id=uuid4(), organization_id=org.id, display_name="Director", role="lab_director", status="ACTIVE")
        db.add_all([org, user])
        db.flush()

        old = _candidate(db, name="FutureDB", version="1", checksum="b" * 64)
        old_approval = request_resource_approval(db, resource_id=old.id, organization_id=org.id, qualification_version="qualification-v1")
        decide_resource_approval(
            db, approval_id=old_approval.id, organization_id=org.id, actor_id=user.id,
            decision="APPROVED", expected_version=1, reason="Initial qualification approved",
        )

        new = _candidate(db, name="FutureDB", version="2", checksum="c" * 64)
        reject = request_resource_approval(db, resource_id=new.id, organization_id=org.id, qualification_version="qualification-v1")
        decide_resource_approval(
            db, approval_id=reject.id, organization_id=org.id, actor_id=user.id,
            decision="REJECTED", expected_version=1, reason="Lab deferred rollout pending review",
        )
        active = get_active_resource_for_organization(
            db, organization_id=org.id, name="FutureDB", provider="FutureProvider",
            resource_type="EVIDENCE", genome_build="GRCh38",
        )
        assert active.id == old.id

        newer = _candidate(db, name="FutureDB", version="3", checksum="d" * 64)
        deferred = request_resource_approval(db, resource_id=newer.id, organization_id=org.id, qualification_version="qualification-v1")
        decide_resource_approval(
            db, approval_id=deferred.id, organization_id=org.id, actor_id=user.id,
            decision="DEFERRED", expected_version=1, reason="Review at next governance meeting",
        )
        active = get_active_resource_for_organization(
            db, organization_id=org.id, name="FutureDB", provider="FutureProvider",
            resource_type="EVIDENCE", genome_build="GRCh38",
        )
        assert active.id == old.id


def test_one_lab_can_approve_new_version_without_changing_another_lab():
    engine = _engine()
    with Session(engine) as db:
        org_a = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        org_b = Organization(id=uuid4(), name="Lab B", external_identifier=None)
        user_a = User(id=uuid4(), organization_id=org_a.id, display_name="Director A", role="lab_director", status="ACTIVE")
        user_b = User(id=uuid4(), organization_id=org_b.id, display_name="Director B", role="lab_director", status="ACTIVE")
        db.add_all([org_a, org_b, user_a, user_b])
        db.flush()

        v1 = _candidate(db, name="FutureDB", version="1", checksum="e" * 64)
        a1 = request_resource_approval(db, resource_id=v1.id, organization_id=org_a.id, qualification_version="qualification-v1")
        decide_resource_approval(db, approval_id=a1.id, organization_id=org_a.id, actor_id=user_a.id, decision="APPROVED", expected_version=1, reason="Lab A baseline")
        b1 = request_resource_approval(db, resource_id=v1.id, organization_id=org_b.id, qualification_version="qualification-v1")
        decide_resource_approval(db, approval_id=b1.id, organization_id=org_b.id, actor_id=user_b.id, decision="APPROVED", expected_version=1, reason="Lab B baseline")

        v2 = _candidate(db, name="FutureDB", version="2", checksum="f" * 64)
        a2 = request_resource_approval(db, resource_id=v2.id, organization_id=org_a.id, qualification_version="qualification-v1")
        decide_resource_approval(db, approval_id=a2.id, organization_id=org_a.id, actor_id=user_a.id, decision="APPROVED", expected_version=1, reason="Lab A adopts v2")

        active_a = get_active_resource_for_organization(db, organization_id=org_a.id, name="FutureDB", provider="FutureProvider", resource_type="EVIDENCE", genome_build="GRCh38")
        active_b = get_active_resource_for_organization(db, organization_id=org_b.id, name="FutureDB", provider="FutureProvider", resource_type="EVIDENCE", genome_build="GRCh38")
        assert active_a.id == v2.id
        assert active_b.id == v1.id
        assert v1.status == "QUALIFIED"
        assert v2.status == "QUALIFIED"


def test_approval_requires_qualification_and_rejects_stale_version():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        user = User(id=uuid4(), organization_id=org.id, display_name="Director", role="lab_director", status="ACTIVE")
        db.add_all([org, user])
        db.flush()
        resource, _ = register_resource_version(
            db, organization_id=None, name="Unqualified", provider="FutureProvider",
            resource_type="EVIDENCE", version="1", genome_build="GRCh38",
            access_method="OBJECT_STORAGE", license_text=None, checksum="1" * 64,
            location="blob://unqualified", population_definition=None, initial_status="CANDIDATE",
        )
        try:
            request_resource_approval(db, resource_id=resource.id, organization_id=org.id, qualification_version="missing")
        except ResourceRegistryError as exc:
            assert "qualification" in str(exc).lower()
        else:
            raise AssertionError("approval must require technical qualification")

        qualified = _candidate(db, name="RaceDB", version="1", checksum="2" * 64)
        approval = request_resource_approval(db, resource_id=qualified.id, organization_id=org.id, qualification_version="qualification-v1")
        decide_resource_approval(db, approval_id=approval.id, organization_id=org.id, actor_id=user.id, decision="DEFERRED", expected_version=1, reason="defer")
        try:
            decide_resource_approval(db, approval_id=approval.id, organization_id=org.id, actor_id=user.id, decision="APPROVED", expected_version=1, reason="stale")
        except ResourceRegistryError as exc:
            assert "already" in str(exc).lower() or "changed" in str(exc).lower()
        else:
            raise AssertionError("stale approval decision must be rejected")
