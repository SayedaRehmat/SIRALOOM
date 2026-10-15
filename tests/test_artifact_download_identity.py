from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1 import artifacts
from backend.app.auth.principal import Principal


@pytest.mark.parametrize("storage_uri", ["gs://lab-bucket/cases/other-tenant/file.vcf", "file:///other/case/file.vcf"])
def test_artifact_download_rejects_uri_not_bound_to_artifact(monkeypatch, storage_uri):
    artifact_id, case_id, organization_id, user_id = (uuid4() for _ in range(4))
    artifact = type(
        "ArtifactRow",
        (),
        {
            "id": artifact_id,
            "case_id": case_id,
            "filename": "sample.vcf",
            "storage_uri": storage_uri,
            "media_type": "text/vcf",
        },
    )()

    class FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        def uri_for_artifact(self, **kwargs):
            assert kwargs == {
                "case_id": case_id,
                "artifact_id": artifact_id,
                "filename": "sample.vcf",
            }
            return "gs://lab-bucket/cases/current-case/artifacts/current-id/sample.vcf"

        def iter_bytes(self, uri):
            raise AssertionError("Mismatched URI must not be read")

        def local_path(self, uri):
            raise AssertionError("Mismatched URI must not be resolved")

    monkeypatch.setattr(artifacts, "get_accessible_artifact", lambda *args, **kwargs: artifact)
    monkeypatch.setattr(artifacts, "resolve_storage_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(artifacts, "FirebaseArtifactStore", FakeStore)
    monkeypatch.setattr(artifacts, "ArtifactStore", FakeStore)

    with pytest.raises(HTTPException) as error:
        artifacts.download_artifact(
            str(artifact_id),
            db=object(),
            principal=Principal(user_id, organization_id, "read_only", str(user_id)),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Artifact not found"


@pytest.mark.parametrize("corrupt", [False, True])
def test_local_artifact_download_verifies_bytes_before_response(monkeypatch, tmp_path, corrupt):
    from backend.app.api.v1 import artifacts as routes

    payload = b"verified VCF bytes"
    artifact_id, case_id, organization_id, user_id = (uuid4() for _ in range(4))
    source = tmp_path / "source.vcf"
    source.write_bytes(b"corrupt VCF bytes" if corrupt else payload)
    artifact = type(
        "ArtifactRow",
        (),
        {
            "id": artifact_id,
            "case_id": case_id,
            "filename": "sample.vcf",
            "storage_uri": source.as_uri(),
            "media_type": "text/vcf",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        },
    )()

    class LocalStore:
        def __init__(self, root):
            pass

        def uri_for_artifact(self, **kwargs):
            return artifact.storage_uri

        def local_path(self, uri):
            return source

    monkeypatch.setattr(routes, "get_accessible_artifact", lambda *args, **kwargs: artifact)
    monkeypatch.setattr(routes, "resolve_storage_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "ArtifactStore", LocalStore)

    if corrupt:
        with pytest.raises(HTTPException) as error:
            routes.download_artifact(
                str(artifact_id), object(), Principal(user_id, organization_id, "read_only", str(user_id))
            )
        assert error.value.status_code == 409
    else:
        response = routes.download_artifact(
            str(artifact_id), object(), Principal(user_id, organization_id, "read_only", str(user_id))
        )
        assert Path(response.path).read_bytes() == payload


@pytest.mark.parametrize("corrupt", [False, True])
def test_cloud_artifact_download_verifies_bytes_before_response(monkeypatch, corrupt):
    from backend.app.api.v1 import artifacts as routes

    payload = b"verified cloud VCF"
    artifact_id, case_id, organization_id, user_id = (uuid4() for _ in range(4))
    uri = f"gs://lab-bucket/cases/{case_id}/artifacts/{artifact_id}/sample.vcf"
    artifact = type(
        "ArtifactRow",
        (),
        {
            "id": artifact_id,
            "case_id": case_id,
            "filename": "sample.vcf",
            "storage_uri": uri,
            "media_type": "text/vcf",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        },
    )()

    class CloudStore:
        def __init__(self, bucket):
            pass

        def uri_for_artifact(self, **kwargs):
            return uri

        def download_to_file(self, requested_uri, destination, **expectations):
            assert requested_uri == uri
            assert expectations == {
                "expected_sha256": artifact.sha256,
                "expected_size_bytes": artifact.size_bytes,
            }
            Path(destination).write_bytes(b"tampered bytes" if corrupt else payload)

    monkeypatch.setattr(routes.settings, "firebase_storage_bucket", "lab-bucket")
    monkeypatch.setattr(routes, "get_accessible_artifact", lambda *args, **kwargs: artifact)
    monkeypatch.setattr(routes, "resolve_storage_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "FirebaseArtifactStore", CloudStore)
    principal = Principal(user_id, organization_id, "read_only", str(user_id))

    if corrupt:
        with pytest.raises(HTTPException) as error:
            routes.download_artifact(str(artifact_id), object(), principal)
        assert error.value.status_code == 503
    else:
        response = routes.download_artifact(str(artifact_id), object(), principal)
        response_path = Path(response.path)
        assert response_path.read_bytes() == payload
        asyncio.run(response.background())
        assert not response_path.exists()
