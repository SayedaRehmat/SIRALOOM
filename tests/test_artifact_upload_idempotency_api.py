from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import backend.app.api.v1.artifacts as artifacts_api
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db import models as _models
from backend.app.infrastructure.db.artifact_upload_intents import ArtifactUploadIntent
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Artifact,
    AuditEvent,
    Case,
    Organization,
    User,
)
from backend.app.infrastructure.db.session import get_db
from backend.app.main import app


@pytest.fixture
def upload_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'upload-api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        organization = Organization(
            id=organization_id,
            name="Upload API Lab",
            external_identifier=str(organization_id),
        )
        user = User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@test.local",
            display_name="Upload API Reviewer",
            role="organization_admin",
            status="ACTIVE",
        )
        case = Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=f"UPLOAD-API-{case_id}",
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=user_id,
        )
        db.add_all([organization, user, case])
        db.commit()

    principal = Principal(
        user_id=user_id,
        organization_id=organization_id,
        role="organization_admin",
        subject=str(user_id),
    )

    def override_db():
        with session_factory() as db:
            yield db

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = lambda: principal

    storage_root = tmp_path / "artifact-storage"
    scratch_root = tmp_path / "worker-scratch"
    scratch_root.mkdir()
    monkeypatch.setattr(artifacts_api.settings, "worker_scratch_root", str(scratch_root))
    monkeypatch.setattr(artifacts_api, "require_case_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(artifacts_api, "require_role", lambda *args, **kwargs: None)
    monkeypatch.setattr(artifacts_api, "effective_max_upload_bytes", lambda *args, **kwargs: 10_000_000)
    monkeypatch.setattr(
        artifacts_api,
        "artifact_storage_target_for_organization",
        lambda db, *, organization_id: ("LOCAL_FILESYSTEM", "test-target", str(storage_root)),
    )
    monkeypatch.setattr(
        artifacts_api,
        "preflight_upload_capacity",
        lambda incoming_size, **kwargs: {"status": "READY", "issues": []},
    )
    monkeypatch.setattr(
        artifacts_api,
        "_store",
        lambda db, organization_id: ArtifactStore(storage_root),
    )

    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "engine": engine,
                "session_factory": session_factory,
                "organization_id": organization_id,
                "user_id": user_id,
                "case_id": case_id,
                "storage_root": storage_root,
                "scratch_root": scratch_root,
            }
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()


def _post_vcf(client: TestClient, case_id, content: bytes, key: str):
    return client.post(
        f"/api/v1/cases/{case_id}/artifacts",
        data={"genome_build": "GRCh38"},
        files={"file": ("sample.vcf", content, "text/vcf")},
        headers={"Idempotency-Key": key},
    )


def test_artifact_upload_http_retry_returns_original_artifact_and_rejects_changed_bytes(upload_api):
    content = (
        b"##fileformat=VCFv4.2\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"1\t10\t.\tA\tG\t.\tPASS\t.\n"
    )
    key = "browser-upload-attempt-000001"
    client = upload_api["client"]
    case_id = upload_api["case_id"]

    first = _post_vcf(client, case_id, content, key)
    replay = _post_vcf(client, case_id, content, key)
    conflict = _post_vcf(client, case_id, content + b"\n", key)

    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert conflict.status_code == 409, conflict.text
    assert first.json()["artifact_id"] == replay.json()["artifact_id"]
    assert first.json()["sha256"] == replay.json()["sha256"]
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    listed = client.get(f"/api/v1/cases/{case_id}/artifacts")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["validation_status"] == "PENDING"
    assert listed.json()[0]["validation_dispatch_status"] == "PENDING"
    assert listed.json()[0]["validation_dispatch_error"] is None

    with upload_api["session_factory"]() as db:
        artifacts = list(db.scalars(select(Artifact).where(Artifact.case_id == case_id)))
        intents = list(
            db.scalars(
                select(ArtifactUploadIntent).where(ArtifactUploadIntent.case_id == case_id)
            )
        )
        from backend.app.infrastructure.db.models import ArtifactValidationDispatch
        queued_audits = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.case_id == case_id,
                    AuditEvent.event_type == "ARTIFACT_VALIDATION_QUEUED",
                )
            )
        )
        dispatches = list(
            db.scalars(
                select(ArtifactValidationDispatch).where(
                    ArtifactValidationDispatch.case_id == case_id
                )
            )
        )
        assert len(artifacts) == 1
        assert artifacts[0].validation_status == "PENDING"
        assert len(intents) == 1
        assert intents[0].status == "COMMITTED"
        assert len(queued_audits) == 1
        assert len(dispatches) == 1
        assert dispatches[0].status == "PENDING"
        assert dispatches[0].artifact_id == artifacts[0].id


def test_artifact_upload_http_retry_fails_closed_for_committed_intent_without_artifact(upload_api):
    content = (
        b"##fileformat=VCFv4.2\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"1\t10\t.\tA\tG\t.\tPASS\t.\n"
    )
    key = "browser-upload-attempt-000002"
    client = upload_api["client"]
    case_id = upload_api["case_id"]

    first = _post_vcf(client, case_id, content, key)
    assert first.status_code == 201, first.text
    artifact_id = UUID(first.json()["artifact_id"])

    with upload_api["session_factory"]() as db:
        artifact = db.get(Artifact, artifact_id)
        intent = db.scalar(
            select(ArtifactUploadIntent).where(ArtifactUploadIntent.case_id == case_id)
        )
        assert artifact is not None
        assert intent is not None
        db.delete(artifact)
        db.commit()

    retry = _post_vcf(client, case_id, content, key)

    assert retry.status_code == 503, retry.text
    assert retry.json()["detail"]["code"] == "UPLOAD_RECOVERY_REQUIRED"
    with upload_api["session_factory"]() as db:
        intent = db.scalar(
            select(ArtifactUploadIntent).where(ArtifactUploadIntent.case_id == case_id)
        )
        assert intent.status == "RECOVERY_REQUIRED"
        assert db.scalar(
            select(func.count(Artifact.id)).where(Artifact.case_id == case_id)
        ) == 0


def test_artifact_upload_stages_on_configured_worker_scratch_volume(upload_api, monkeypatch):
    observed = {}
    original_temporary_directory = artifacts_api.tempfile.TemporaryDirectory

    def recording_temporary_directory(*args, **kwargs):
        observed["dir"] = Path(kwargs["dir"])
        return original_temporary_directory(*args, **kwargs)

    monkeypatch.setattr(
        artifacts_api.tempfile,
        "TemporaryDirectory",
        recording_temporary_directory,
    )
    content = (
        b"##fileformat=VCFv4.2\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"1\t10\t.\tA\tG\t.\tPASS\t.\n"
    )

    response = _post_vcf(
        upload_api["client"], upload_api["case_id"], content,
        "browser-upload-attempt-scratch-000001",
    )

    assert response.status_code == 201, response.text
    assert observed["dir"] == upload_api["scratch_root"]
    assert list(upload_api["scratch_root"].iterdir()) == []


def test_artifact_upload_fails_closed_when_configured_scratch_root_is_unavailable(
    upload_api, monkeypatch, tmp_path
):
    invalid_scratch_root = tmp_path / "not-a-directory"
    invalid_scratch_root.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(
        artifacts_api.settings, "worker_scratch_root", str(invalid_scratch_root)
    )
    content = (
        b"##fileformat=VCFv4.2\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"1\t10\t.\tA\tG\t.\tPASS\t.\n"
    )

    response = _post_vcf(
        upload_api["client"], upload_api["case_id"], content,
        "browser-upload-attempt-scratch-000002",
    )

    assert response.status_code == 507, response.text
    assert response.json()["detail"]["code"] == "UPLOAD_STAGING_UNAVAILABLE"
    with upload_api["session_factory"]() as db:
        assert db.scalar(
            select(func.count(Artifact.id)).where(Artifact.case_id == upload_api["case_id"])
        ) == 0

def test_artifact_upload_fails_closed_when_scratch_volume_write_fails(
    upload_api, monkeypatch
):
    original_open = Path.open

    def fail_staging_write(path, mode="r", *args, **kwargs):
        if mode == "wb" and path.parent.name.startswith("siraloom-ingest-"):
            raise OSError("simulated scratch volume exhaustion")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(artifacts_api.Path, "open", fail_staging_write)
    content = (
        b"##fileformat=VCFv4.2\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"1\t10\t.\tA\tG\t.\tPASS\t.\n"
    )

    response = _post_vcf(
        upload_api["client"], upload_api["case_id"], content,
        "browser-upload-attempt-scratch-000003",
    )

    assert response.status_code == 507, response.text
    assert response.json()["detail"]["code"] == "UPLOAD_STAGING_UNAVAILABLE"
    with upload_api["session_factory"]() as db:
        assert db.scalar(
            select(func.count(Artifact.id)).where(Artifact.case_id == upload_api["case_id"])
        ) == 0
