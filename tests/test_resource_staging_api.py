"""API tests for tenant-scoped, capacity-aware resource staging."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1 import resources as resources_api
from backend.app.config import settings
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, Resource, ResourceStaging


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _principal(organization_id):
    return SimpleNamespace(
        organization_id=organization_id,
        user_id=uuid4(),
        role="lab_director",
    )


def _seed_remote_resource(db, organization_id, root, *, host="ftp.example.test"):
    payload = b"known public release payload"
    checksum = sha256(payload).hexdigest()
    destination = root / str(organization_id) / "NCBI" / "release-1" / "release.gz"
    resource = Resource(
        id=uuid4(),
        organization_id=organization_id,
        name="Example release",
        provider="NCBI",
        resource_type="CLINICAL_DATABASE",
        version="release-1",
        genome_build="GRCh38",
        access_method="HTTPS",
        license_text="Public release",
        checksum=checksum,
        location=str(destination),
        status="CANDIDATE",
        population_definition=None,
        metadata_json={
            "source_contract": {
                "publisher": "NCBI",
                "canonical_source_url": f"https://{host}/catalog",
                "artifact_url": f"https://{host}/release.gz",
                "release_identity": "release-1",
                "access_mode": "PUBLIC",
                "license_status": "NOT_REQUIRED",
                "license_url": None,
                "terms_url": None,
                "checksum_status": "PUBLISHED_AND_VERIFIED",
                "authority_evidence_url": f"https://{host}/catalog",
            },
            "execution": {
                "provider_id": "NCBI",
                "provider_version": "release-1",
                "access_method": "HTTPS",
                "location": str(destination),
            },
        },
    )
    db.add(resource)
    db.flush()
    return resource, payload


def test_register_public_file_resource_assigns_organization_scoped_destination(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"))
        db.commit()
        monkeypatch.setattr(settings, "resource_cache_root", str(tmp_path / "cache"))
        payload = {
            "name": "ClinVar release",
            "provider": "NCBI",
            "resource_type": "CLINICAL_DATABASE",
            "version": "2026-10",
            "genome_build": "GRCh38",
            "access_method": "HTTPS",
            "location": None,
            "checksum": "a" * 64,
            "status": "CANDIDATE",
            "metadata": {
                "source_contract": {
                    "publisher": "NCBI",
                    "canonical_source_url": "https://ftp.ncbi.nlm.nih.gov/clinvar/",
                    "artifact_url": "https://ftp.ncbi.nlm.nih.gov/clinvar/release.xml.gz",
                    "release_identity": "2026-10",
                    "access_mode": "PUBLIC",
                    "license_status": "NOT_REQUIRED",
                    "license_url": None,
                    "terms_url": None,
                    "checksum_status": "PUBLISHED_AND_VERIFIED",
                    "authority_evidence_url": "https://ftp.ncbi.nlm.nih.gov/clinvar/",
                },
                "execution": {"provider_id": "NCBI", "provider_version": "2026-10"},
            },
        }
        monkeypatch.setattr(
            "backend.app.infrastructure.queue.celery_app.scan_reanalysis_resources",
            SimpleNamespace(delay=lambda: None),
        )
        result = resources_api.register_resource(payload, db, _principal(organization_id))
        destination = Path(result["location"])
        assert destination.is_relative_to((tmp_path / "cache" / str(organization_id)).resolve())
        resource = db.get(Resource, UUID(result["resource_id"]))
        assert resource.metadata_json["execution"]["location"] == str(destination)
    finally:
        db.close()
        engine.dispose()


def test_create_resource_staging_persists_capacity_preflight(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"))
        db.flush()
        root = tmp_path / "cache"
        monkeypatch.setattr(settings, "resource_cache_root", str(root))
        monkeypatch.setattr(settings, "resource_staging_allowed_hosts", "ftp.example.test")
        resource, payload = _seed_remote_resource(db, organization_id, root)
        db.commit()

        result = resources_api.create_resource_staging(
            resource.id,
            resources_api.ResourceStagingCreateRequest(expected_size_bytes=len(payload)),
            db,
            _principal(organization_id),
        )
        assert result["status"] == "READY_TO_STAGE"
        assert result["expected_size_bytes"] == len(payload)
        assert result["storage_preflight"]["passed"] is True
        assert Path(result["destination_uri"]).is_relative_to((root / str(organization_id)).resolve())
    finally:
        db.close()
        engine.dispose()


def test_create_resource_staging_rejects_unapproved_publisher(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"))
        db.flush()
        root = tmp_path / "cache"
        monkeypatch.setattr(settings, "resource_cache_root", str(root))
        monkeypatch.setattr(settings, "resource_staging_allowed_hosts", "approved.example.test")
        resource, payload = _seed_remote_resource(db, organization_id, root, host="unapproved.example.test")
        db.commit()

        with pytest.raises(HTTPException) as exc:
            resources_api.create_resource_staging(
                resource.id,
                resources_api.ResourceStagingCreateRequest(expected_size_bytes=len(payload)),
                db,
                _principal(organization_id),
            )
        assert exc.value.status_code == 403
        assert db.query(ResourceStaging).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_create_resource_staging_blocks_unresolved_license_review(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"))
        db.flush()
        root = tmp_path / "cache"
        monkeypatch.setattr(settings, "resource_cache_root", str(root))
        monkeypatch.setattr(settings, "resource_staging_allowed_hosts", "ftp.example.test")
        resource, payload = _seed_remote_resource(db, organization_id, root)
        resource.metadata_json["source_contract"]["license_status"] = "REVIEW_REQUIRED"
        db.add(resource)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            resources_api.create_resource_staging(
                resource.id,
                resources_api.ResourceStagingCreateRequest(expected_size_bytes=len(payload)),
                db,
                _principal(organization_id),
            )
        assert exc.value.status_code == 409
        assert db.query(ResourceStaging).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_create_resource_staging_rejects_cross_organization_resource(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        organization_id = uuid4()
        other_organization_id = uuid4()
        db.add_all([
            Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"),
            Organization(id=other_organization_id, name="Other Lab", external_identifier="other-lab"),
        ])
        db.flush()
        root = tmp_path / "cache"
        monkeypatch.setattr(settings, "resource_cache_root", str(root))
        monkeypatch.setattr(settings, "resource_staging_allowed_hosts", "ftp.example.test")
        resource, payload = _seed_remote_resource(db, other_organization_id, root)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            resources_api.create_resource_staging(
                resource.id,
                resources_api.ResourceStagingCreateRequest(expected_size_bytes=len(payload)),
                db,
                _principal(organization_id),
            )
        assert exc.value.status_code == 404
        assert db.query(ResourceStaging).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_execute_resource_staging_queues_durable_task(monkeypatch, tmp_path):
    engine, db = _db()
    published = []
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"))
        db.flush()
        root = tmp_path / "cache"
        monkeypatch.setattr(settings, "resource_cache_root", str(root))
        monkeypatch.setattr(settings, "resource_staging_allowed_hosts", "ftp.example.test")
        resource, payload = _seed_remote_resource(db, organization_id, root)
        db.commit()
        staged = resources_api.create_resource_staging(
            resource.id,
            resources_api.ResourceStagingCreateRequest(expected_size_bytes=len(payload)),
            db,
            _principal(organization_id),
        )
        monkeypatch.setattr(
            "backend.app.infrastructure.queue.celery_app.run_resource_staging_task",
            SimpleNamespace(apply_async=lambda **kwargs: published.append(kwargs) or SimpleNamespace(id=kwargs["task_id"])),
        )

        result = resources_api.execute_resource_staging(
            resource.id,
            UUID(staged["staging_id"]),
            db,
            _principal(organization_id),
        )
        assert result["dispatch"]["status"] == "PUBLISHED"
        assert len(published) == 1
        assert published[0]["args"] == [staged["staging_id"]]
    finally:
        db.close()
        engine.dispose()
