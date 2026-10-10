"""Integration tests for real organization-bound resource profile resolution.

These tests use the SQLAlchemy registry, qualification records, deployment policy,
organization bindings, and the actual analysis-start route. The resolver is not mocked.
"""
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.resource_profile_resolver import resolve_analysis_resource_profile
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisDispatch,
    Case,
    Organization,
    OrganizationResourceBinding,
    Resource,
    ResourceDeploymentProfile,
    ResourceQualification,
    User,
    WorkflowStep,
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
    toolchain = (
        {
            "vep_binary": "/opt/vep/vep",
            "cache_dir": location,
            "cache_version": version,
            "assembly": "GRCh38",
            "fasta": "/lab-resources/GRCh38.fa",
        }
        if provider == "VEP"
        else None
    )
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
                "toolchain": toolchain,
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
                    "toolchain": toolchain,
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


def _seed_required_resources(db: Session, organization_id):
    return {
        "reference": _resource(
            db,
            organization_id=organization_id,
            name="GRCh38 reference",
            provider="REFERENCE",
            resource_type="REFERENCE_PACKAGE",
        ),
        "population": _resource(
            db,
            organization_id=organization_id,
            name="gnomAD GRCh38",
            provider="GNOMAD",
            resource_type="POPULATION",
        ),
        "acmg": _resource(
            db,
            organization_id=organization_id,
            name="ClinGen ACMG specifications",
            provider="CLINGEN",
            resource_type="ACMG_RULE_SPECIFICATION",
            version="2024-01",
        ),
    }


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

            resources = _seed_required_resources(db, organization_id)
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
                resources["reference"].id,
                resources["population"].id,
                resources["acmg"].id,
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
            selected_by_capability = {item.capability: item for item in ready.selected}
            assert set(selected_by_capability) >= {
                "REFERENCE_PACKAGE",
                "ANNOTATION_ENGINE",
                "POPULATION",
                "ACMG_RULE_SPECIFICATION",
            }
            assert selected_by_capability["REFERENCE_PACKAGE"].resource.id == resources["reference"].id
            assert selected_by_capability["ANNOTATION_ENGINE"].resource.id == bound_vep.id
            assert selected_by_capability["POPULATION"].resource.id == resources["population"].id
            assert selected_by_capability["ACMG_RULE_SPECIFICATION"].resource.id == resources["acmg"].id

            for item in ready.selected:
                assert item.execution.resource_id == item.resource.id
                assert item.execution.qualification_version == "qualification-1"
                assert item.execution.contract.execution_scope == "ORGANIZATION_MANAGED"
    finally:
        engine.dispose()


def test_real_registry_recovery_queues_one_durable_dispatch_and_duplicate_start_is_idempotent(monkeypatch):
    """Exercise actual resource resolution through block, recovery, and dispatch."""
    from backend.app.api.v1 import analyses as analyses_api
    from backend.app.domain.enums import AnalysisStatus
    from backend.app.infrastructure.queue import celery_app

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    published = []
    monkeypatch.setattr(
        analyses_api,
        "get_accessible_analysis",
        lambda requested_id, db, _principal: db.get(Analysis, requested_id),
    )
    monkeypatch.setattr(analyses_api, "require_role", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        celery_app,
        "publish_analysis_dispatch",
        lambda dispatch_id: published.append(str(dispatch_id)) or str(dispatch_id),
    )
    principal = SimpleNamespace(organization_id=organization_id, user_id=user_id)

    try:
        with Session(engine) as db:
            db.add(
                Organization(
                    id=organization_id,
                    name="Real Resolver Dispatch Lab",
                    external_identifier="real-resolver-dispatch-lab",
                )
            )
            db.add(
                User(
                    id=user_id,
                    organization_id=organization_id,
                    external_subject="real-resolver-reviewer",
                    email="real-resolver@example.test",
                    display_name="Real Resolver User",
                    role="LAB_ADMIN",
                    status="ACTIVE",
                )
            )
            db.flush()
            db.add(
                Case(
                    id=case_id,
                    organization_id=organization_id,
                    case_identifier="CASE-REAL-RESOURCE-RECOVERY",
                    status="OPEN",
                    clinical_context={},
                    language="en",
                    created_by=user_id,
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
            _seed_required_resources(db, organization_id)
            db.add(
                Analysis(
                    id=analysis_id,
                    case_id=case_id,
                    parent_analysis_id=None,
                    assay_id=None,
                    analysis_type="GERMLINE",
                    workflow_id="variant",
                    workflow_version="1",
                    status="CREATED",
                    queue_task_id=None,
                    reference_build="GRCh38",
                    configuration={"resource_profile_id": "WES_GRCh38_STANDARD"},
                    started_at=None,
                    completed_at=None,
                    created_by=user_id,
                )
            )
            db.commit()

            # Missing required VEP: the real resolver must block, persist the
            # resource gap, and avoid creating or publishing a dispatch.
            first = analyses_api.start(analysis_id, db, principal)
            assert first["status"] == AnalysisStatus.BLOCKED
            assert first["task_id"] is None
            assert first["resource_plan_status"] == "BLOCKED"
            assert db.scalar(
                select(AnalysisDispatch).where(AnalysisDispatch.analysis_id == analysis_id)
            ) is None
            assert published == []
            blocked_steps = db.scalars(
                select(WorkflowStep).where(WorkflowStep.analysis_id == analysis_id)
            ).all()
            assert any(
                step.step_id == "annotate"
                and step.status == "BLOCKED"
                and step.metadata_json.get("workflow_action") == "WAIT_FOR_RESOURCE"
                for step in blocked_steps
            )

            # A qualified, organization-bound VEP resource is then registered.
            vep = _resource(
                db,
                organization_id=organization_id,
                name="VEP cache 115",
                provider="VEP",
                resource_type="ANNOTATION_ENGINE",
                version="115",
            )
            db.commit()

            second = analyses_api.start(analysis_id, db, principal)
            assert second["status"] == AnalysisStatus.QUEUED
            assert second["task_id"] is not None
            assert len(published) == 1

            persisted = db.get(Analysis, analysis_id)
            plan = persisted.configuration["resource_plan"]
            assert plan["status"] == "READY"
            selected_vep = [
                item for item in plan["selected"]
                if item["capability"] == "ANNOTATION_ENGINE"
            ]
            assert len(selected_vep) == 1
            assert selected_vep[0]["resource_id"] == str(vep.id)
            assert selected_vep[0]["execution"]["qualification_version"] == "qualification-1"

            dispatches = db.scalars(
                select(AnalysisDispatch).where(AnalysisDispatch.analysis_id == analysis_id)
            ).all()
            assert len(dispatches) == 1
            assert dispatches[0].status == "PENDING"
            assert dispatches[0].dispatch_generation == 1

            third = analyses_api.start(analysis_id, db, principal)
            assert third["task_id"] == second["task_id"]
            assert len(
                db.scalars(
                    select(AnalysisDispatch).where(AnalysisDispatch.analysis_id == analysis_id)
                ).all()
            ) == 1
            assert len(published) == 1
    finally:
        engine.dispose()
