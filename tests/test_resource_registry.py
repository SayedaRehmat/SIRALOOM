from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.resources import ResourceRegistryError, register_resource_version
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Resource


def test_resource_registry_is_idempotent_and_supersedes_prior_active_version():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Resource.__table__])

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
        assert db.query(Resource).count() == 1

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
        assert db.query(Resource).filter(Resource.status == "ACTIVE").count() == 1


def test_resource_registry_rejects_invalid_checksum_and_type():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Resource.__table__])
    with Session(engine) as db:
        kwargs = dict(
            name="x", provider="x", version="1", genome_build="GRCh38",
            access_method="OBJECT_STORAGE", license_text=None, checksum="bad",
            location=None, population_definition=None,
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
