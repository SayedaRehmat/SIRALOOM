from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.resource_fallback import resolve_resource_with_fallback
from backend.app.domain.workflow_decision import OutcomeKind, WorkflowAction
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Organization,
    OrganizationResourceBinding,
    ResourceDeploymentProfile,
    OrganizationEntitlement,
    Resource,
    ResourceQualification,
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            ResourceDeploymentProfile.__table__,
            OrganizationEntitlement.__table__,
            Resource.__table__,
            ResourceQualification.__table__,
            OrganizationResourceBinding.__table__,
        ],
    )
    return engine, Session(engine)


def _resource(
    db,
    *,
    organization_id,
    name,
    provider,
    resource_type,
    version,
    status,
    metadata_json=None,
):
    row = Resource(
        id=uuid4(),
        organization_id=organization_id,
        name=name,
        provider=provider,
        resource_type=resource_type,
        version=version,
        genome_build="GRCh38",
        access_method="LOCAL",
        license_text=None,
        checksum="a" * 64,
        location=f"/resources/{version}",
        status=status,
        population_definition=None,
        metadata_json=metadata_json or {},
    )
    db.add(row)
    db.flush()
    return row


def _qualify(db, resource):
    db.add(
        ResourceQualification(
            id=uuid4(),
            resource_id=resource.id,
            qualification_version="qualification-1",
            status="QUALIFIED",
            checks_json={
                "passed": True,
                "execution_contract": {
                    "provider_id": resource.provider,
                    "provider_version": (
                        (resource.metadata_json or {}).get("execution", {}).get("provider_version")
                        or "v1"
                    ),
                    "access_method": resource.access_method,
                    "endpoint": None,
                    "location": resource.location,
                    "dataset": None,
                },
            },
            qualified_by=None,
            qualified_at=None,
        )
    )
    db.flush()


def _bind(db, *, organization_id, resource):
    db.add(
        OrganizationResourceBinding(
            id=uuid4(),
            organization_id=organization_id,
            resource_id=resource.id,
            resource_name=resource.name,
            provider=resource.provider,
            resource_type=resource.resource_type,
            genome_build=resource.genome_build,
            identity_key="|".join(
                [
                    resource.name,
                    resource.provider,
                    resource.resource_type,
                    resource.genome_build,
                ]
            ),
            bound_by=None,
            reason="approved for laboratory use",
            version=1,
        )
    )
    db.flush()


def test_rejected_requested_resource_falls_back_to_org_approved_binding_without_mutating_binding():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Lab A", external_identifier=None))
        requested = _resource(
            db,
            organization_id=None,
            name="GeneBe",
            provider="GENEBE",
            resource_type="ANNOTATION",
            version="rejected-v2",
            status="REJECTED",
        )
        fallback = _resource(
            db,
            organization_id=None,
            name="GeneBe",
            provider="GENEBE",
            resource_type="ANNOTATION",
            version="approved-v1",
            status="QUALIFIED",
            metadata_json={"execution": {"provider_version": "api-public-v1"}},
        )
        _qualify(db, fallback)
        _bind(db, organization_id=org_id, resource=fallback)
        db.commit()

        result = resolve_resource_with_fallback(
            db,
            organization_id=org_id,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="GENEBE",
            expected_provider_version="api-public-v1",
        )

        assert result.used_fallback is True
        assert result.resource is not None
        assert result.resource.id == fallback.id
        assert result.requested_resource_id == requested.id
        assert result.fallback_resource_id == fallback.id
        assert result.decision.action is WorkflowAction.FALLBACK_TO_ACTIVE_RESOURCE
        assert result.decision.fallback_allowed is True

        binding = db.scalar(
            select(OrganizationResourceBinding).where(
                OrganizationResourceBinding.organization_id == org_id
            )
        )
        assert binding is not None
        assert binding.resource_id == fallback.id
    finally:
        db.close()
        engine.dispose()


def test_laboratories_keep_independent_active_bindings():
    engine, db = _db()
    try:
        lab_a, lab_b = uuid4(), uuid4()
        db.add_all(
            [
                Organization(id=lab_a, name="Lab A", external_identifier=None),
                Organization(id=lab_b, name="Lab B", external_identifier=None),
            ]
        )
        requested = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER",
            resource_type="ANNOTATION",
            version="rejected-v3",
            status="REJECTED",
        )
        a_v1 = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER",
            resource_type="ANNOTATION",
            version="v1",
            status="QUALIFIED",
            metadata_json={"execution": {"provider_version": "v1"}},
        )
        b_v2 = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER",
            resource_type="ANNOTATION",
            version="v2",
            status="QUALIFIED",
            metadata_json={"execution": {"provider_version": "v2"}},
        )
        _qualify(db, a_v1)
        _qualify(db, b_v2)
        _bind(db, organization_id=lab_a, resource=a_v1)
        _bind(db, organization_id=lab_b, resource=b_v2)
        db.commit()

        a_result = resolve_resource_with_fallback(
            db,
            organization_id=lab_a,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="PROVIDER",
            expected_provider_version="v1",
        )
        b_result = resolve_resource_with_fallback(
            db,
            organization_id=lab_b,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="PROVIDER",
        )

        assert a_result.resource is not None and a_result.resource.id == a_v1.id
        assert b_result.resource is not None and b_result.resource.id == b_v2.id
    finally:
        db.close()
        engine.dispose()


def test_no_approved_fallback_waits_for_resource():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Lab", external_identifier=None))
        requested = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER",
            resource_type="ANNOTATION",
            version="missing-v4",
            status="REJECTED",
        )
        db.commit()

        result = resolve_resource_with_fallback(
            db,
            organization_id=org_id,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="PROVIDER",
        )

        assert result.resource is None
        assert result.used_fallback is False
        assert result.decision.action is WorkflowAction.WAIT_FOR_RESOURCE
    finally:
        db.close()
        engine.dispose()


def test_explicitly_pinned_superseded_resource_is_consumed_without_fallback():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Lab", external_identifier=None))
        requested = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER",
            resource_type="ANNOTATION",
            version="historical-v1",
            status="SUPERSEDED",
        )
        db.commit()

        result = resolve_resource_with_fallback(
            db,
            organization_id=org_id,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="PROVIDER",
        )

        assert result.resource is not None
        assert result.resource.id == requested.id
        assert result.used_fallback is False
        assert result.decision.action is WorkflowAction.CONTINUE
    finally:
        db.close()
        engine.dispose()


def test_requested_identity_mismatch_fails_closed_without_using_other_binding():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Lab", external_identifier=None))
        requested = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER-A",
            resource_type="ANNOTATION",
            version="rejected-v1",
            status="REJECTED",
        )
        other = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER-B",
            resource_type="ANNOTATION",
            version="approved-v1",
            status="QUALIFIED",
        )
        _qualify(db, other)
        _bind(db, organization_id=org_id, resource=other)
        db.commit()

        result = resolve_resource_with_fallback(
            db,
            organization_id=org_id,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="PROVIDER-B",
        )

        assert result.resource is None
        assert result.used_fallback is False
        assert result.decision.action is WorkflowAction.REQUEST_LAB_ACTION
        assert result.decision.code == "RESOURCE_IDENTITY_MISMATCH"
    finally:
        db.close()
        engine.dispose()


def test_fallback_requires_qualification_even_when_binding_exists():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Lab", external_identifier=None))
        requested = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER",
            resource_type="ANNOTATION",
            version="rejected-v1",
            status="REJECTED",
        )
        fallback = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER",
            resource_type="ANNOTATION",
            version="approved-v2",
            status="QUALIFIED",
        )
        _bind(db, organization_id=org_id, resource=fallback)
        db.commit()

        result = resolve_resource_with_fallback(
            db,
            organization_id=org_id,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="PROVIDER",
        )

        assert result.resource is None
        assert result.used_fallback is False
        assert result.decision.action is WorkflowAction.WAIT_FOR_RESOURCE
    finally:
        db.close()
        engine.dispose()


def test_fallback_rejects_binding_to_wrong_build():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Lab", external_identifier=None))
        requested = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER",
            resource_type="ANNOTATION",
            version="rejected-v1",
            status="REJECTED",
        )
        fallback = _resource(
            db,
            organization_id=None,
            name="AnnotationDB",
            provider="PROVIDER",
            resource_type="ANNOTATION",
            version="approved-grch37",
            status="QUALIFIED",
        )
        fallback.genome_build = "GRCh37"
        _qualify(db, fallback)
        _bind(db, organization_id=org_id, resource=fallback)
        db.commit()

        result = resolve_resource_with_fallback(
            db,
            organization_id=org_id,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="PROVIDER",
        )

        assert result.resource is None
        assert result.used_fallback is False
        assert result.decision.action is WorkflowAction.WAIT_FOR_RESOURCE
    finally:
        db.close()
        engine.dispose()


def test_fallback_is_rejected_when_runtime_provider_version_is_not_proven():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Lab", external_identifier=None))
        requested = _resource(db, organization_id=None, name="GeneBe", provider="GENEBE", resource_type="ANNOTATION", version="rejected-v2", status="REJECTED")
        fallback = _resource(db, organization_id=None, name="GeneBe", provider="GENEBE", resource_type="ANNOTATION", version="approved-v1", status="QUALIFIED")
        _qualify(db, fallback)
        _bind(db, organization_id=org_id, resource=fallback)
        db.commit()
        result = resolve_resource_with_fallback(db, organization_id=org_id, requested_resource_id=requested.id, expected_type="ANNOTATION", expected_build="GRCh38", expected_provider="GENEBE", expected_provider_version="api-public-v1")
        assert result.resource is None
        assert result.used_fallback is False
        assert result.decision.action is WorkflowAction.WAIT_FOR_RESOURCE
    finally:
        db.close(); engine.dispose()
