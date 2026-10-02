from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.resource_deployment import (
    LABORATORY,
    TRIAL_PUBLIC,
    create_resource_deployment_profile,
    resolve_resource_deployment_policy,
)
from backend.app.domain.resource_fallback import resolve_resource_with_fallback
from backend.app.domain.workflow_decision import WorkflowAction
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Organization,
    OrganizationEntitlement,
    OrganizationResourceBinding,
    Resource,
    ResourceDeploymentProfile,
    ResourceQualification,
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            OrganizationEntitlement.__table__,
            ResourceDeploymentProfile.__table__,
            Resource.__table__,
            ResourceQualification.__table__,
            OrganizationResourceBinding.__table__,
        ],
    )
    return engine, Session(engine)


def _global_resource(db, *, version="v1"):
    resource = Resource(
        id=uuid4(),
        organization_id=None,
        name="GeneBe",
        provider="GeneBe",
        resource_type="ANNOTATION",
        version=version,
        genome_build="GRCh38",
        access_method="API",
        license_text=None,
        checksum="a" * 64,
        location=None,
        status="ACTIVE",
        population_definition=None,
        metadata_json={},
    )
    db.add(resource)
    db.flush()
    db.add(
        ResourceQualification(
            id=uuid4(),
            resource_id=resource.id,
            qualification_version="qualification-v1",
            status="QUALIFIED",
            checks_json={
                "passed": True,
                "execution_contract": {
                    "provider_id": "GeneBe",
                    "provider_version": "api-public-v1",
                    "access_method": "API",
                    "endpoint": "https://trial.example/genebe",
                    "location": None,
                    "dataset": None,
                },
            },
        )
    )
    db.flush()
    return resource


def test_trial_profile_allows_siraloom_managed_global_fallback():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Trial", external_identifier=None))
        db.add(
            OrganizationEntitlement(
                id=uuid4(),
                organization_id=org_id,
                plan="TRIAL",
                status="ACTIVE",
                max_analyses=10,
                analyses_used=0,
                max_vcf_size_bytes=10_000,
            )
        )
        requested = _global_resource(db, version="v2")
        requested.status = "REJECTED"
        fallback = _global_resource(db, version="v1")
        db.commit()

        result = resolve_resource_with_fallback(
            db,
            organization_id=org_id,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="GeneBe",
            expected_provider_version="api-public-v1",
        )

        assert result.used_fallback is True
        assert result.resource is not None
        assert result.resource.id == fallback.id
        assert result.decision.action is WorkflowAction.FALLBACK_TO_ACTIVE_RESOURCE
    finally:
        db.close()
        engine.dispose()


def test_laboratory_profile_does_not_silently_use_global_siraloom_resource():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Lab", external_identifier=None))
        create_resource_deployment_profile(
            db,
            organization_id=org_id,
            profile_type=LABORATORY,
        )
        requested = _global_resource(db, version="v2")
        requested.status = "REJECTED"
        _global_resource(db, version="v1")
        db.commit()

        result = resolve_resource_with_fallback(
            db,
            organization_id=org_id,
            requested_resource_id=requested.id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="GeneBe",
            expected_provider_version="api-public-v1",
        )

        assert result.resource is None
        assert result.used_fallback is False
        assert result.decision.action is WorkflowAction.WAIT_FOR_RESOURCE
    finally:
        db.close()
        engine.dispose()


def test_explicit_profile_overrides_trial_entitlement_bootstrap():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Converted Lab", external_identifier=None))
        db.add(
            OrganizationEntitlement(
                id=uuid4(),
                organization_id=org_id,
                plan="TRIAL",
                status="ACTIVE",
                max_analyses=10,
                analyses_used=0,
            )
        )
        create_resource_deployment_profile(
            db,
            organization_id=org_id,
            profile_type=LABORATORY,
        )
        db.commit()

        policy = resolve_resource_deployment_policy(db, organization_id=org_id)
        assert policy.profile_type == LABORATORY
        assert policy.allow_siraloom_managed_global_resources is False
    finally:
        db.close()
        engine.dispose()


def test_trial_entitlement_bootstraps_public_profile_for_existing_orgs():
    engine, db = _db()
    try:
        org_id = uuid4()
        db.add(Organization(id=org_id, name="Existing Trial", external_identifier=None))
        db.add(
            OrganizationEntitlement(
                id=uuid4(),
                organization_id=org_id,
                plan="EVALUATION",
                status="ACTIVE",
                max_analyses=10,
                analyses_used=0,
            )
        )
        db.commit()

        policy = resolve_resource_deployment_policy(db, organization_id=org_id)
        assert policy.profile_type == TRIAL_PUBLIC
        assert policy.allow_siraloom_managed_global_resources is True
    finally:
        db.close()
        engine.dispose()
