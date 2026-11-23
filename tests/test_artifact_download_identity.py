from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1 import artifacts
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Artifact, Case, Organization, User


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
    monkeypatch.setattr(artifacts, "artifact_store_for_uri", lambda *args, **kwargs: FakeStore())

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
    monkeypatch.setattr(routes, "artifact_store_for_uri", lambda *args, **kwargs: LocalStore(tmp_path))

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
    monkeypatch.setattr(routes, "artifact_store_for_uri", lambda *args, **kwargs: CloudStore("lab-bucket"))
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


def test_artifact_download_denies_foreign_tenant_using_persisted_rows(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'tenant-download.db'}")
    Base.metadata.create_all(engine)
    foreign_org_id, caller_org_id, owner_id, case_id, artifact_id = (uuid4() for _ in range(5))
    with Session(engine) as db:
        db.add_all([
            Organization(id=foreign_org_id, name="Foreign Lab", external_identifier=str(foreign_org_id)),
            Organization(id=caller_org_id, name="Caller Lab", external_identifier=str(caller_org_id)),
        ])
        db.flush()
        db.add(User(
            id=owner_id,
            organization_id=foreign_org_id,
            external_subject=str(owner_id),
            email=f"{owner_id}@foreign.test",
            display_name="Foreign Owner",
            role="organization_admin",
            status="ACTIVE",
        ))
        db.flush()
        db.add(Case(
            id=case_id,
            organization_id=foreign_org_id,
            case_identifier=f"FOREIGN-{case_id}",
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=owner_id,
        ))
        db.add(Artifact(
            id=artifact_id,
            case_id=case_id,
            artifact_type="VCF",
            filename="foreign.vcf",
            media_type="text/vcf",
            size_bytes=1,
            sha256="0" * 64,
            storage_uri="file:///foreign-lab/foreign.vcf",
            validation_status="VALID",
            metadata_json={},
        ))
        db.commit()

        def storage_must_not_be_resolved(*_args, **_kwargs):
            raise AssertionError("foreign tenant authorization must fail before storage lookup")

        monkeypatch.setattr(artifacts, "artifact_store_for_uri", storage_must_not_be_resolved)
        with pytest.raises(HTTPException) as error:
            artifacts.download_artifact(
                str(artifact_id),
                db,
                Principal(uuid4(), caller_org_id, "read_only", "caller"),
            )

    engine.dispose()
    assert error.value.status_code == 404
