from __future__ import annotations

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
