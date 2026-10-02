from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.workflow_decision import OutcomeKind
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Case,
    Organization,
    User,
    WorkflowDecisionRecord,
    WorkflowStep,
)
from backend.app.workflows.variant import _apply_scientific_limitation


def _fixture():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            User.__table__,
            Case.__table__,
            Analysis.__table__,
            WorkflowStep.__table__,
            WorkflowDecisionRecord.__table__,
        ],
    )
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    db = Session(engine)
    db.add(Organization(id=organization_id, name="Decision Test Laboratory", external_identifier=None))
    db.add(User(
        id=user_id, organization_id=organization_id, external_subject=None,
        email="decision@test.local", display_name="Decision Test",
        role="ANALYST", status="ACTIVE",
    ))
    db.add(Case(
        id=case_id, organization_id=organization_id, case_identifier="DECISION-001",
        status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
    ))
    db.add(Analysis(
        id=analysis_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
        analysis_type="VARIANT_INTERPRETATION", workflow_id="siraloom.variant",
        workflow_version="1.0", status=AnalysisStatus.RUNNING, queue_task_id=None,
        reference_build="GRCh38", configuration={}, started_at=None,
        completed_at=None, created_by=user_id,
    ))
    step = WorkflowStep(
        id=uuid4(), analysis_id=analysis_id, step_id="population", step_order=4,
        status=StepStatus.RUNNING, attempt=1, input_artifacts=[],
        output_artifacts=[], metadata_json={},
    )
    db.add(step)
    db.commit()
    return engine, db, step


def test_scientific_limitation_is_persisted_without_pipeline_failure():
    engine, db, step = _fixture()
    try:
        _apply_scientific_limitation(
            db, step, outcome=OutcomeKind.NO_DATA,
            code="POPULATION_NO_DATA",
            message="No population observation is available.",
            metadata={"resource_observations": 0},
        )
        persisted = db.get(WorkflowStep, step.id)
        assert persisted.status == StepStatus.SUCCEEDED
        assert persisted.error_code == "POPULATION_NO_DATA"
        assert persisted.metadata_json["scientific_outcome"] == "NO_DATA"
        assert persisted.metadata_json["workflow_action"] == "CONTINUE_WITH_LIMITATION"
        assert persisted.metadata_json["scientific_limitation"] is True
        assert persisted.metadata_json["resource_observations"] == 0
    finally:
        db.close()
        engine.dispose()


def test_limitation_helper_fails_closed_when_stage_requires_review():
    engine, db, step = _fixture()
    try:
        step.step_id = "acmg_assessment"
        db.commit()
        try:
            _apply_scientific_limitation(
                db, step, outcome=OutcomeKind.INSUFFICIENT_EVIDENCE,
                code="ACMG_NO_CRITERIA",
                message="No applicable ACMG criteria were established.",
            )
        except RuntimeError as exc:
            assert "not continuation-safe" in str(exc)
        else:
            raise AssertionError("Expected ACMG limitation to require human review")
        persisted = db.get(WorkflowStep, step.id)
        assert persisted.status == StepStatus.RUNNING
        assert persisted.error_code is None
    finally:
        db.close()
        engine.dispose()


from backend.app.domain.workflow_decision import WorkflowAction, WorkflowDecision
from backend.app.domain.workflow_decision_persistence import record_workflow_decision
from backend.app.infrastructure.db.models import WorkflowDecisionRecord


def test_workflow_decision_is_persisted_as_immutable_history():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    WorkflowDecisionRecord.__table__.create(engine)
    db = Session(engine)
    try:
        analysis_id = uuid4()
        decision = WorkflowDecision(
            action=WorkflowAction.CONTINUE_WITH_LIMITATION,
            code="POPULATION_NO_DATA",
            message="No population observation is available.",
        )
        record = record_workflow_decision(
            db,
            analysis_id=analysis_id,
            step_id="population",
            attempt=2,
            outcome=OutcomeKind.NO_DATA,
            decision=decision,
            metadata={"scientific_limitation": True},
        )
        db.commit()

        rows = db.scalars(
            select(WorkflowDecisionRecord).where(
                WorkflowDecisionRecord.analysis_id == analysis_id
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].id == record.id
        assert rows[0].step_id == "population"
        assert rows[0].attempt == 2
        assert rows[0].outcome_kind == "NO_DATA"
        assert rows[0].action == "CONTINUE_WITH_LIMITATION"
        assert rows[0].code == "POPULATION_NO_DATA"
        assert rows[0].metadata_json["scientific_limitation"] is True
    finally:
        db.close()
        engine.dispose()
