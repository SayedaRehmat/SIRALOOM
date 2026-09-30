from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.resources import (
    ResourceRegistryError,
    activate_resource_version,
    qualify_resource_version,
    register_resource_version,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, Resource, ResourceQualification, User


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            User.__table__,
            Resource.__table__,
            ResourceQualification.__table__,
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
