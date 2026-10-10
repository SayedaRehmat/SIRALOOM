"""Integration tests for real organization-bound resource profile resolution.

These tests use the SQLAlchemy registry, qualification records, deployment policy,
and organization bindings. The resolver is not mocked.
"""
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.resource_profile_resolver import resolve_analysis_resource_profile
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Organization,
    OrganizationResourceBinding,
    Resource,
    ResourceDeploymentProfile,
    ResourceQualification,
)


def _resource(
    db: Session,
    *,
    organization_id,
    name: str,
    provider: str,
    resource_type: str,
    version: str = "1",
    bind: bool = True,
) -> Resource:
    resource_id = uuid4()
    location = f"/lab-resources/{name}/{version}"
    resource = Resource(
        id=resource_id,
        organization_id=organization_id,
        name=name,
        provider=provider,
        resource_type=resource_type,
        version=version,
        genome_build="GRCh38",
        access_method="LOCAL",
        license_text=None,
        checksum="a" * 64,
        location=location,
        status="ACTIVE",
        population_definition=None,
        metadata_json={
            "execution": {
                "provider_version": version,
                "toolchain": (
                    {
                        "vep_binary": "/opt/vep/vep",
                        "cache_dir": location,
                        "cache_version": version,
                        "assembly": "GRCh38",
                        "fasta": "/lab-resources/GRCh38.fa",
                    }
                    if provider == "VEP"
                    else None
                ),
            }
        },
    )
    db.add(resource)
    db.flush()

    db.add(
        ResourceQualification(
            id=uuid4(),
            resource_id=resource.id,
            qualification_version="qualification-1",
            status="QUALIFIED",
            checks_json={
                "passed": True,
                "execution_contract": {
                    "provider_id": provider,
                    "provider_version": version,
                    "access_method": "LOCAL",
                    "endpoint": None,
                    "location": location,
                    "dataset": None,
                    "execution_scope": "ORGANIZATION_MANAGED",
                    "toolchain": resource.metadata_json["execution"]["toolchain"],
                },
            },
            qualified_by=None,
            qualified_at=None,
        )
    )
    db.flush()

    if bind:
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
                        resource.genome_build or "UNSPECIFIED",
                    ]
                ),
                bound_by=None,
                reason="integration test: approved for laboratory use",
                version=1,
            )
        )
        db.flush()

    return resource


def test_laboratory_profile_blocks_unbound_qualified_resource_then_recovers_from_bound_registry():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    try:
        organization_id = uuid4()
        with Session(engine) as db:
            db.add(
                Organization(
                    id=organization_id,
                    name="Resource Lifecycle Integration Lab",
                    external_identifier="resource-lifecycle-integration-lab",
                )
            )
            db.add(
                ResourceDeploymentProfile(
                    id=uuid4(),
                    organization_id=organization_id,
                    profile_type="LABORATORY",
                    profile_version="1",
                    status="ACTIVE",
                )
            )
            db.flush()

            reference = _resource(
                db,
                organization_id=organization_id,
                name="GRCh38 reference",
                provider="REFERENCE",
                resource_type="REFERENCE_PACKAGE",
            )
            population = _resource(
                db,
                organization_id=organization_id,
                name="gnomAD GRCh38",
                provider="GNOMAD",
                resource_type="POPULATION",
            )
            acmg = _resource(
                db,
                organization_id=organization_id,
                name="ClinGen ACMG specifications",
                provider="CLINGEN",
                resource_type="ACMG_RULE_SPECIFICATION",
                version="2024-01",
            )
            # Technically qualified is not enough: this VEP resource is not
            # organization-bound and therefore must not satisfy the profile.
            unbound_vep = _resource(
                db,
                organization_id=organization_id,
                name="VEP cache",
                provider="VEP",
                resource_type="ANNOTATION_ENGINE",
                version="115",
                bind=False,
            )
            db.commit()

            blocked = resolve_analysis_resource_profile(
                db,
                organization_id=organization_id,
                profile_id="WES_GRCh38_STANDARD",
                analysis_reference_build="GRCh38",
            )
            assert blocked.status == "BLOCKED"
            assert any(
                issue.required
                and issue.capability == "ANNOTATION_ENGINE"
                and issue.code == "RESOURCE_UNAVAILABLE"
                for issue in blocked.issues
            )
            assert {item.resource.id for item in blocked.selected} == {
                reference.id,
                population.id,
                acmg.id,
            }
            assert unbound_vep.id not in {item.resource.id for item in blocked.selected}

            bound_vep = _resource(
                db,
                organization_id=organization_id,
                name="VEP cache approved",
                provider="VEP",
                resource_type="ANNOTATION_ENGINE",
                version="115",
                bind=True,
            )
            db.commit()

            ready = resolve_analysis_resource_profile(
                db,
                organization_id=organization_id,
                profile_id="WES_GRCh38_STANDARD",
                analysis_reference_build="GRCh38",
            )
            assert ready.status == "READY"
            assert ready.is_ready
            assert not ready.required_issues
            selected_by_capability = {
                item.capability: item for item in ready.selected
            }
            assert set(selected_by_capability) >= {
                "REFERENCE_PACKAGE",
                "ANNOTATION_ENGINE",
                "POPULATION",
                "ACMG_RULE_SPECIFICATION",
            }
            assert selected_by_capability["REFERENCE_PACKAGE"].resource.id == reference.id
            assert selected_by_capability["ANNOTATION_ENGINE"].resource.id == bound_vep.id
            assert selected_by_capability["POPULATION"].resource.id == population.id
            assert selected_by_capability["ACMG_RULE_SPECIFICATION"].resource.id == acmg.id

            # The persisted registry identities and exact qualification versions
            # are carried into the resolved plan; the resolver does not invent
            # a provider version or use a globally available trial resource.
            for item in ready.selected:
                assert item.execution.resource_id == item.resource.id
                assert item.execution.qualification_version == "qualification-1"
                assert item.execution.contract.execution_scope == "ORGANIZATION_MANAGED"
    finally:
        engine.dispose()
