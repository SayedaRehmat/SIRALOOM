from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.app.adapters.annotation.genebe import GeneBeProvider
from backend.app.adapters.population.gnomad import GnomADGraphQLProvider
from backend.app.domain.resource_execution import ResourceExecutionError, resolve_resource_execution
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, Resource, ResourceQualification


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Analysis.__table__,
            Resource.__table__,
            ResourceQualification.__table__,
        ],
    )
    return engine, Session(engine)


def _resource(db, *, provider="GeneBe", access_method="API", endpoint="https://qualified.example/api", dataset=None):
    resource = Resource(
        id=uuid4(),
        organization_id=None,
        name=provider,
        provider=provider,
        resource_type="ANNOTATION" if provider == "GeneBe" else "POPULATION",
        version="v1",
        genome_build="GRCh38",
        access_method=access_method,
        license_text=None,
        checksum="a" * 64,
        location=None,
        status="ACTIVE",
        population_definition=None,
        metadata_json={},
    )
    db.add(resource)
    db.flush()
    qualification = ResourceQualification(
        id=uuid4(),
        resource_id=resource.id,
        qualification_version="qualification-v1",
        status="QUALIFIED",
        checks_json={
            "passed": True,
            "execution_contract": {
                "provider_id": provider,
                "provider_version": "api-public-v1" if provider == "GeneBe" else "graphql",
                "access_method": access_method,
                "endpoint": endpoint,
                "location": None,
                "dataset": dataset,
            },
        },
        qualified_by=None,
    )
    db.add(qualification)
    db.commit()
    return resource


def test_resolver_returns_exact_qualified_contract_and_stable_hash():
    engine, db = _db()
    try:
        resource = _resource(db, endpoint="https://qualified.example/api")
        resolved = resolve_resource_execution(db, resource=resource)
        assert resolved.contract.endpoint == "https://qualified.example/api"
        assert resolved.contract.provider_version == "api-public-v1"
        assert len(resolved.contract_hash) == 64
        assert resolved.snapshot["resource_id"] == str(resource.id)
    finally:
        db.close()
        engine.dispose()


def test_resolver_fails_closed_when_qualified_contract_disagrees_with_registry():
    engine, db = _db()
    try:
        resource = _resource(db)
        qualification = db.query(ResourceQualification).filter_by(resource_id=resource.id).one()
        qualification.checks_json["execution_contract"]["provider_id"] = "OTHER"
        flag_modified(qualification, "checks_json")
        db.commit()
        with pytest.raises(ResourceExecutionError, match="invalid"):
            resolve_resource_execution(db, resource=resource)
    finally:
        db.close()
        engine.dispose()


def test_genebe_adapter_uses_only_contract_endpoint():
    contract = ResourceExecutionContract(
        provider_id="GeneBe",
        provider_version="api-public-v1",
        access_method="API",
        endpoint="https://qualified.example/gene-be",
        location=None,
        dataset=None,
    )
    provider = GeneBeProvider.from_execution_contract(contract)
    assert provider.endpoint == "https://qualified.example/gene-be"
    with pytest.raises(Exception):
        GeneBeProvider.from_execution_contract(
            ResourceExecutionContract(
                provider_id="GeneBe",
                provider_version="wrong",
                access_method="API",
                endpoint="https://qualified.example/gene-be",
                location=None,
                dataset=None,
            )
        )


def test_gnomad_adapter_uses_only_contract_endpoint_and_dataset():
    contract = ResourceExecutionContract(
        provider_id="gnomAD",
        provider_version="graphql",
        access_method="API",
        endpoint="https://qualified.example/gnomad",
        location=None,
        dataset="gnomad_r4",
    )
    provider = GnomADGraphQLProvider.from_execution_contract(contract)
    assert provider.endpoint == "https://qualified.example/gnomad"
    assert provider.dataset_id == "gnomad_r4"
