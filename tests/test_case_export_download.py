import asyncio
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from backend.app.api.v1 import reports
from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.infrastructure.db.models import Artifact, Case, CaseExport


class FakeDB:
    def __init__(self, export, case, artifact):
        self.export = export
        self.case = case
        self.artifact = artifact

    def get(self, model, key):
        if model is CaseExport:
            return self.export
        if model is Case:
            return self.case
        if model is Artifact:
            return self.artifact
        raise AssertionError(f"Unexpected model lookup: {model!r}")


def test_case_export_download_uses_organization_cloud_store(monkeypatch):
    export_id = uuid4()
    case_id = uuid4()
    artifact_id = uuid4()
    organization_id = uuid4()
    export = SimpleNamespace(
        id=export_id,
        case_id=case_id,
        status="SUCCEEDED",
        artifact_id=artifact_id,
    )
    case = SimpleNamespace(id=case_id, organization_id=organization_id)
    artifact = SimpleNamespace(
        id=artifact_id,
        case_id=case_id,
        analysis_id=None,
        artifact_type="AUDIT_PACKAGE",
        metadata_json={"export_id": str(export_id)},
        sha256=hashlib.sha256(b"PKarchive").hexdigest(),
        size_bytes=len(b"PKarchive"),
        storage_uri=(
            f"gs://test-bucket/cases/{case_id}/artifacts/"
            f"{artifact_id}/case-export.zip"
        ),
        filename="case-export.zip",
        media_type="application/zip",
    )
    db = FakeDB(export, case, artifact)
    store = FirebaseArtifactStore("test-bucket")
    monkeypatch.setattr(reports, "artifact_store_for_organization", lambda _db, *, organization_id: store)
    monkeypatch.setattr(reports, "require_case_tenant", lambda _case, _principal: None)
    def download_to_file(uri, destination, *, expected_sha256, expected_size_bytes):
        assert uri == artifact.storage_uri
        assert expected_sha256 == artifact.sha256
        assert expected_size_bytes == artifact.size_bytes
        from pathlib import Path

        Path(destination).write_bytes(b"PKarchive")

    monkeypatch.setattr(store, "download_to_file", download_to_file)
    principal = SimpleNamespace()

    response = reports.download_case_export(export_id, db, principal)

    assert response.media_type == "application/zip"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]

    assert response.path.read_bytes() == b"PKarchive"
    asyncio.run(response.background())
    assert not response.path.exists()
