from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1 import reports
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import Artifact, Case, CaseExport


@pytest.mark.parametrize(
    ("artifact_case_id", "artifact_type", "artifact_export_id", "sha256"),
    [
        (uuid4(), "AUDIT_PACKAGE", "export", "a" * 64),
        (None, "REPORT_PDF", "export", "a" * 64),
        (None, "AUDIT_PACKAGE", "different-export", "a" * 64),
        (None, "AUDIT_PACKAGE", "export", "not-a-sha256"),
    ],
)
def test_download_rejects_export_artifact_with_invalid_lineage(
    monkeypatch, artifact_case_id, artifact_type, artifact_export_id, sha256
):
    export_id, case_id, organization_id, user_id = (uuid4() for _ in range(4))
    export = type(
        "Export",
        (),
        {
            "id": export_id,
            "case_id": case_id,
            "status": "SUCCEEDED",
            "artifact_id": uuid4(),
        },
    )()
    case = type("CaseRow", (), {"id": case_id, "organization_id": organization_id})()
    artifact = type(
        "ArtifactRow",
        (),
        {
            "id": export.artifact_id,
            "case_id": artifact_case_id or case_id,
            "analysis_id": None,
            "artifact_type": artifact_type,
            "metadata_json": {
                "export_id": str(export_id) if artifact_export_id == "export" else artifact_export_id
            },
            "sha256": sha256,
        },
    )()

    class FakeDB:
        def get(self, model, requested_id):
            if model is CaseExport:
                return export
            if model is Case:
                return case
            if model is Artifact:
                return artifact
            raise AssertionError(f"Unexpected model lookup: {model}")

    def storage_must_not_be_opened(*args, **kwargs):
        raise AssertionError("Invalid export lineage must fail before storage access")

    monkeypatch.setattr(reports, "artifact_store_for_organization", storage_must_not_be_opened)

    with pytest.raises(HTTPException) as error:
        reports.download_case_export(
            export_id,
            db=FakeDB(),
            principal=Principal(user_id, organization_id, "read_only", str(user_id)),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Export artifact not found"


def test_download_accepts_export_artifact_with_matching_lineage(monkeypatch, tmp_path):
    export_id, case_id, organization_id, user_id = (uuid4() for _ in range(4))
    export = type(
        "Export",
        (),
        {
            "id": export_id,
            "case_id": case_id,
            "status": "SUCCEEDED",
            "artifact_id": export_id,
        },
    )()
    case = type("CaseRow", (), {"id": case_id, "organization_id": organization_id})()
    artifact = type(
        "ArtifactRow",
        (),
        {
            "id": export_id,
            "case_id": case_id,
            "analysis_id": None,
            "artifact_type": "AUDIT_PACKAGE",
            "metadata_json": {"export_id": str(export_id)},
            "sha256": "a" * 64,
            "storage_uri": "file:///audit-package.zip",
            "media_type": "application/zip",
            "filename": "audit-package.zip",
        },
    )()
    expected_path = tmp_path / artifact.filename
    expected_path.write_bytes(b"PK")

    class FakeDB:
        def get(self, model, requested_id):
            if model is CaseExport:
                return export
            if model is Case:
                return case
            if model is Artifact:
                return artifact
            raise AssertionError(f"Unexpected model lookup: {model}")

    class FakeStore:
        def local_path(self, uri):
            assert uri == artifact.storage_uri
            return expected_path

    monkeypatch.setattr(reports, "artifact_store_for_organization", lambda *a, **k: FakeStore())

    response = reports.download_case_export(
        export_id,
        db=FakeDB(),
        principal=Principal(user_id, organization_id, "read_only", str(user_id)),
    )

    assert Path(response.path) == expected_path
    assert response.media_type == "application/zip"
