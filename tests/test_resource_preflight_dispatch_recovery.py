"""Integration tests for governed resource preflight and durable dispatch."""

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.application import analysis as analysis_application
from backend.app.domain.enums import AnalysisStatus
from backend.app.domain.resource_capabilities import CLINICAL_DATABASE, REFERENCE_PACKAGE
from backend.app.domain.resource_profile_resolver import AnalysisResourcePlan, ResourceResolutionIssue
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisDispatch,
    Case,
    Organization,
    ResourceDeploymentProfile,
    User,
    WorkflowStep,
)


def _plan(*, status: str, plan_hash: str, issues=()):
    return AnalysisResourcePlan(
        profile_id="WES_GRCh38_STANDARD",
        profile_version="1",
        genome_build="GRCh38",
        deployment_profile_type="LABORATORY",
        deployment_profile_version="1",
        status=status,
        selected=(),
        issues=tuple(issues),
        plan_hash=plan_hash,
    )


def test_resource_blocked_analysis_recovers_and_dispatches_once(monkeypatch):
    """Exercise the real start route, SQL persistence, and dispatch outbox boundary."""
    from backend.app.api.v1 import analyses as analyses_api
    from backend.app.infrastructure.queue import celery_app

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()

    blocked_plan = _plan(
        status="BLOCKED",
        plan_hash="blocked-no-reference",
        issues=(
            ResourceResolutionIssue(
                capability=REFERENCE_PACKAGE,
                required=True,
                code="RESOURCE_UNAVAILABLE",
                message="No approved GRCh38 reference package is available.",
                candidate_count=0,
            ),
        ),
    )
    recovered_plan = _plan(status="READY", plan_hash="recovered-approved-reference")
    active_plan = {"value": blocked_plan}
    monkeypatch.setattr(
        analysis_application,
        "resolve_analysis_resource_profile",
        lambda *_args, **_kwargs: active_plan["value"],
    )
    monkeypatch.setattr(
        analyses_api,
        "get_accessible_analysis",
        lambda requested_id, db, _principal: db.get(Analysis, requested_id),
    )
    monkeypatch.setattr(analyses_api, "require_role", lambda *_args, **_kwargs: None)
    published = []
    monkeypatch.setattr(
        celery_app,
        "publish_analysis_dispatch",
        lambda dispatch_id: published.append(str(dispatch_id)) or str(dispatch_id),
    )
    principal = SimpleNamespace(organization_id=organization_id, user_id=user_id)

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Integration Lab", external_identifier="lab-001"))
        db.add(
            User(
                id=user_id,
                organization_id=organization_id,
                external_subject="integration-user",
                email="integration@example.test",
                display_name="Integration User",
                role="LAB_ADMIN",
                status="ACTIVE",
            )
        )
        db.flush()
        db.add(
            Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier="CASE-RESOURCE-RECOVERY",
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

        first = analyses_api.start(analysis_id, db, principal)

        assert first["status"] == AnalysisStatus.BLOCKED
        assert first["task_id"] is None
        assert first["resource_plan_status"] == "BLOCKED"
        assert db.scalar(select(AnalysisDispatch).where(AnalysisDispatch.analysis_id == analysis_id)) is None
        assert published == []
        blocked_steps = db.scalars(
            select(WorkflowStep).where(WorkflowStep.analysis_id == analysis_id)
        ).all()
        assert any(
            step.step_id == "normalize"
            and step.status == "BLOCKED"
            and step.metadata_json.get("workflow_action") == "WAIT_FOR_RESOURCE"
            for step in blocked_steps
        )

        # Simulate the lab registering, approving, and qualifying the missing
        # resource. The resolver now returns the runnable plan from that catalog.
        active_plan["value"] = recovered_plan
        second = analyses_api.start(analysis_id, db, principal)

        assert second["status"] == AnalysisStatus.QUEUED
        assert second["task_id"] is not None
        assert len(published) == 1
        dispatches = db.scalars(
            select(AnalysisDispatch).where(AnalysisDispatch.analysis_id == analysis_id)
        ).all()
        assert len(dispatches) == 1
        assert dispatches[0].status == "PENDING"
        assert dispatches[0].dispatch_generation == 1
        persisted = db.get(Analysis, analysis_id)
        assert persisted.configuration["resource_plan"]["status"] == "READY"
        assert persisted.configuration["resource_plan"]["plan_hash"] == "recovered-approved-reference"
        resumed_steps = db.scalars(
            select(WorkflowStep).where(WorkflowStep.analysis_id == analysis_id)
        ).all()
        normalize = next(step for step in resumed_steps if step.step_id == "normalize")
        assert normalize.status == "PENDING"
        assert "resource_blocked" not in normalize.metadata_json

        # A duplicate start returns the existing dispatch identity and must not
        # create a second durable outbox row or publish another task.
        third = analyses_api.start(analysis_id, db, principal)
        assert third["task_id"] == second["task_id"]
        assert len(
            db.scalars(
                select(AnalysisDispatch).where(AnalysisDispatch.analysis_id == analysis_id)
            ).all()
        ) == 1
        assert len(published) == 1

    engine.dispose()


def test_optional_resource_gap_does_not_block_preflight_or_dispatch(monkeypatch):
    """Optional evidence-provider absence is recorded without blocking the run."""
    from backend.app.api.v1 import analyses as analyses_api
    from backend.app.infrastructure.queue import celery_app

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    limited_plan = _plan(
        status="READY_WITH_LIMITATIONS",
        plan_hash="ready-without-optional-clinvar",
        issues=(
            ResourceResolutionIssue(
                capability=CLINICAL_DATABASE,
                required=False,
                code="RESOURCE_UNAVAILABLE",
                message="No approved ClinVar release is available.",
                candidate_count=0,
            ),
        ),
    )
    monkeypatch.setattr(
        analysis_application,
        "resolve_analysis_resource_profile",
        lambda *_args, **_kwargs: limited_plan,
    )
    monkeypatch.setattr(
        analyses_api,
        "get_accessible_analysis",
        lambda requested_id, db, _principal: db.get(Analysis, requested_id),
    )
    monkeypatch.setattr(analyses_api, "require_role", lambda *_args, **_kwargs: None)
    published = []
    monkeypatch.setattr(
        celery_app,
        "publish_analysis_dispatch",
        lambda dispatch_id: published.append(str(dispatch_id)) or str(dispatch_id),
    )
    principal = SimpleNamespace(organization_id=organization_id, user_id=user_id)

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Optional Resource Lab", external_identifier="lab-002"))
        db.add(
            User(
                id=user_id,
                organization_id=organization_id,
                external_subject="optional-user",
                email="optional@example.test",
                display_name="Optional Resource User",
                role="LAB_ADMIN",
                status="ACTIVE",
            )
        )
        db.flush()
        db.add(
            Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier="CASE-OPTIONAL-RESOURCE",
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

        result = analyses_api.start(analysis_id, db, principal)

        assert result["status"] == AnalysisStatus.QUEUED
        assert len(published) == 1
        persisted = db.get(Analysis, analysis_id)
        assert persisted.configuration["resource_plan"]["status"] == "READY_WITH_LIMITATIONS"
        evidence_stage = next(
            item for item in persisted.configuration["resource_stage_plan"]
            if item["step_id"] == "build_evidence"
        )
        assert evidence_stage["status"] == "READY_WITH_LIMITATIONS"
        assert evidence_stage["issues"][0]["required"] is False

    engine.dispose()
