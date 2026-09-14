from uuid import uuid4
from backend.app.infrastructure.db.models import WorkflowStep
from backend.app.domain.enums import StepStatus
from backend.app.workflows.variant import _batch_checkpoint, _chunk_ranges, _save_batch_checkpoint
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.session import engine
from sqlalchemy.orm import Session

def test_chunk_ranges_are_bounded():
    assert list(_chunk_ranges(601, 250)) == [(0,250),(250,500),(500,601)]

def test_batch_checkpoint_persists_state():
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        # Uses the application's configured test database; isolate with a unique analysis id.
        aid=uuid4(); step=WorkflowStep(id=uuid4(), analysis_id=aid, step_id="build_evidence", step_order=5, status=StepStatus.PENDING, attempt=0, input_artifacts=[], output_artifacts=[], metadata_json={})
        db.add(step); db.commit()
        _save_batch_checkpoint(db, step, 0, 10, status="SUCCEEDED", attempt=1, metadata={"created":3})
        assert _batch_checkpoint(step,0,10)["status"] == "SUCCEEDED"
        assert _batch_checkpoint(step,0,10)["created"] == 3
