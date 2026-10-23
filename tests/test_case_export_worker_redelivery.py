from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db import session as session_module
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Artifact,
    AuditEvent,
    Case,
    CaseExport,
    CaseExportDispatch,
    Organization,
    User,
)
from backend.app.infrastructure.queue import celery_app as queue
from backend.app.reporting import export_task


def test_case_export_redelivery_reuses_artifact_after_worker_loss_between_flush_and_commit(
    monkeypatch, tmp_path
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    make_session = sessionmaker(
        bind=engine, expire_on_commit=False, class_=Session
    )
    organization = Organization(id=uuid4(), name="Export replay lab")
    user = User(
        id=uuid4(),
        organization_id=organization.id,
        display_name="Export replay reviewer",
        role="AUDITOR",
        status="ACTIVE",
    )
    case = Case(
        id=uuid4(),
        organization_id=organization.id,
        case_identifier=f"EXPORT-REPLAY-{uuid4()}",
        status="ACTIVE",
        clinical_context={},
        language="en",
        created_by=user.id,
    )
    export_id = uuid4()
    dispatch_id = uuid4()
    export = CaseExport(
        id=export_id,
        case_id=case.id,
        requested_by=user.id,
        status="QUEUED",
        queue_task_id=str(dispatch_id),
        include_artifacts=False,
        include_reports=False,
        include_evidence=False,
        include_audit=False,
        include_provenance=False,
    )
    dispatch = CaseExportDispatch(
        id=dispatch_id,
        case_export_id=export_id,
        dispatch_generation=1,
        status="PUBLISHED",
        task_id=str(dispatch_id),
        attempts=1,
    )
    with make_session() as db:
        db.add(organization)
        db.commit()
        db.add(user)
        db.commit()
        db.add(case)
        db.commit()
        db.add(export)
        db.add(dispatch)
        db.commit()

    store = ArtifactStore(tmp_path / "lab-owned-store")
    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", make_session)
    monkeypatch.setattr(export_task, "SessionLocal", make_session)
    monkeypatch.setattr(
        export_task,
        "artifact_store_for_organization",
        lambda _db, *, organization_id: store,
    )

    original_build = export_task.build_case_export

    def crash_after_artifact_flush(db, *, export, store):
        original_build(db, export=export, store=store)
        raise SystemExit("simulated worker loss after artifact flush")

    monkeypatch.setattr(export_task, "build_case_export", crash_after_artifact_flush)
    task = queue.run_case_export_task
    task.push_request(
        id=str(dispatch_id), retries=0, delivery_info={"redelivered": False}
    )
    try:
        with pytest.raises(SystemExit, match="simulated worker loss"):
            task.run(str(export_id))
    finally:
        task.pop_request()

    expected_uri = store.uri_for_artifact(
        case_id=case.id,
        artifact_id=export_id,
        filename=f"case_export_{case.case_identifier}.zip",
    )
    with make_session() as db:
        interrupted_export = db.get(CaseExport, export_id)
        assert interrupted_export.status == "RUNNING"
        assert interrupted_export.artifact_id is None
        assert db.scalar(select(Artifact).where(Artifact.id == export_id)) is None
        assert store.exists(expected_uri)
        assert db.scalars(select(AuditEvent)).all() == []

    monkeypatch.setattr(export_task, "build_case_export", original_build)
    task.push_request(
        id=str(dispatch_id), retries=0, delivery_info={"redelivered": True}
    )
    try:
        result = task.run(str(export_id))
    finally:
        task.pop_request()

    with make_session() as db:
        completed_export = db.get(CaseExport, export_id)
        artifacts = db.scalars(
            select(Artifact).where(
                Artifact.case_id == case.id,
                Artifact.artifact_type == "AUDIT_PACKAGE",
            )
        ).all()
        completion_events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.case_id == case.id,
                AuditEvent.event_type == "CASE_EXPORT_COMPLETED",
            )
        ).all()
        assert result == {"export_id": str(export_id), "status": "completed"}
        assert completed_export.status == "SUCCEEDED"
        assert completed_export.artifact_id == export_id
        assert len(artifacts) == 1
        assert artifacts[0].id == export_id
        assert artifacts[0].storage_uri == expected_uri
        assert store.exists(expected_uri)
        actual_sha256 = hashlib.sha256(store.read_bytes(expected_uri)).hexdigest()
        assert artifacts[0].sha256 == actual_sha256
        assert len(completion_events) == 1

    engine.dispose()
