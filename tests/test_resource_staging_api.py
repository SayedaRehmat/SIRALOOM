"""API tests for tenant-scoped, capacity-aware resource staging."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from kombu.exceptions import OperationalError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1 import resources as resources_api
from backend.app.config import settings
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    AuditEvent,
    Organization,
    Resource,
    ResourceQualification,
    ResourceStaging,
)


@pytest.mark.parametrize(
    ("dispatch_status", "task_state", "lookup_fails", "expected"),
    [
        ("QUEUING", "PENDING", False, False),
        ("QUEUING", "UNKNOWN", False, False),
        ("PUBLISHED", "PENDING", False, False),
        ("PUBLISHED", "FAILURE", False, True),
        ("QUEUING", "REVOKED", False, True),
        ("PUBLISHED", "FAILURE", True, False),
        ("RUNNING", "FAILURE", False, False),
    ],
)
def test_stale_staging_dispatch_is_retried_only_when_celery_proves_dead(
    dispatch_status, task_state, lookup_fails, expected,
):
    now = datetime.now(timezone.utc)
    timestamp_name = "published_at" if dispatch_status == "PUBLISHED" else "queued_at"
    dispatch = {
        "status": dispatch_status,
        "task_id": "staging-task-1",
        timestamp_name: (now - timedelta(minutes=10)).isoformat(),
    }

    def lookup(task_id):
        assert task_id == "staging-task-1"
        if lookup_fails:
            raise RuntimeError("result backend unavailable")
        return task_state

    assert resources_api._staging_dispatch_is_definitively_dead(
        dispatch,
        now=now,
        task_state_lookup=lookup,
    ) is expected


@pytest.mark.parametrize("timestamp", [None, "not-a-timestamp"])
def test_staging_dispatch_without_valid_timestamp_is_not_replaced(timestamp):
    lookup_calls = []
    dispatch = {
        "status": "QUEUING",
        "task_id": "staging-task-1",
        "queued_at": timestamp,
    }

    assert resources_api._staging_dispatch_is_definitively_dead(
        dispatch,
        now=datetime.now(timezone.utc),
        task_state_lookup=lambda task_id: lookup_calls.append(task_id) or "FAILURE",
    ) is False
    assert lookup_calls == []


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
        scheduled_scans = []
        monkeypatch.setattr(
            "backend.app.infrastructure.queue.celery_app.scan_reanalysis_resources",
            SimpleNamespace(delay=lambda *args: scheduled_scans.append(args)),
        )
        principal = _principal(organization_id)
        result = resources_api.register_resource(payload, db, principal)
        destination = Path(result["location"])
        assert destination.is_relative_to((tmp_path / "cache" / str(organization_id)).resolve())
        resource = db.get(Resource, UUID(result["resource_id"]))
        assert resource.metadata_json["execution"]["location"] == str(destination)
        event = db.query(AuditEvent).filter_by(event_type="RESOURCE_VERSION_REGISTERED").one()
        assert event.actor_id == str(principal.user_id)
        assert event.subject_id == str(resource.id)
        assert event.after_state["status"] == "CANDIDATE"
        assert event.workflow["organization_id"] == str(organization_id)
        assert result["reanalysis_scan_queued"] is False
        assert scheduled_scans == []
        duplicate = resources_api.register_resource(payload, db, principal)
        assert duplicate["created"] is False
        assert db.query(AuditEvent).filter_by(event_type="RESOURCE_VERSION_REGISTERED").count() == 1
    finally:
        db.close()
        engine.dispose()


def test_resource_qualification_is_recorded_in_the_audit_chain(monkeypatch, tmp_path):
    from backend.app.domain import resource_qualification

    engine, db = _db()
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"))
        root = tmp_path / "cache"
        monkeypatch.setattr(settings, "resource_cache_root", str(root))
        resource, _ = _seed_remote_resource(db, organization_id, root)
        db.commit()
        monkeypatch.setattr(
            resource_qualification,
            "qualify_resource",
            lambda *_args, **_kwargs: SimpleNamespace(
                qualification_version="qualification-test-v1",
                checks={"passed": True, "qualification_outcome": "PASS"},
                passed=True,
                blockers=[],
            ),
        )
        principal = _principal(organization_id)

        result = resources_api.qualify_resource(
            resource.id,
            {"qualification_version": "qualification-test-v1"},
            db,
            principal,
        )

        event = db.query(AuditEvent).filter_by(event_type="RESOURCE_QUALIFICATION_RECORDED").one()
        assert event.actor_id == str(principal.user_id)
        assert event.subject_id == str(resource.id)
        assert event.before_state == {"status": "CANDIDATE"}
        assert event.after_state["status"] == "QUALIFIED"
        assert event.after_state["qualification_id"] == result["qualification_id"]
        assert event.after_state["qualification_status"] == "QUALIFIED"
    finally:
        db.close()
        engine.dispose()


def test_resource_activation_is_recorded_with_lifecycle_before_and_after(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        organization_id, user_id = uuid4(), uuid4()
        db.add(Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"))
        resource = Resource(
            id=uuid4(), organization_id=organization_id, name="Qualified release",
            provider="TestProvider", resource_type="CLINICAL_DATABASE", version="1",
            genome_build="GRCh38", access_method="LOCAL", checksum="d" * 64,
            location=str(tmp_path / "qualified-release"), status="QUALIFIED",
            metadata_json={}, population_definition=None,
        )
        qualification = ResourceQualification(
            id=uuid4(), resource_id=resource.id,
            qualification_version="qualification-test-v1", status="QUALIFIED",
            checks_json={"passed": True}, qualified_by=user_id,
        )
        db.add_all([resource, qualification])
        db.commit()
        principal = _principal(organization_id)
        scheduled_scans = []
        monkeypatch.setattr(
            "backend.app.infrastructure.queue.celery_app.scan_reanalysis_resources",
            SimpleNamespace(delay=lambda *args: scheduled_scans.append(args)),
        )

        result = resources_api.activate_resource(
            resource.id,
            {"qualification_version": "qualification-test-v1"},
            db,
            principal,
        )

        event = db.query(AuditEvent).filter_by(event_type="RESOURCE_VERSION_ACTIVATED").one()
        assert event.actor_id == str(principal.user_id)
        assert event.subject_id == str(resource.id)
        assert event.before_state["resource"]["status"] == "QUALIFIED"
        assert event.after_state["resource"]["status"] == "ACTIVE"
        assert event.workflow["organization_id"] == str(organization_id)
        assert result["reanalysis_scan_queued"] is True
        assert scheduled_scans == [(str(organization_id),)]
    finally:
        db.close()
        engine.dispose()


def test_resource_activation_survives_reanalysis_dispatch_failure(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        organization_id, user_id = uuid4(), uuid4()
        db.add(Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"))
        resource = Resource(
            id=uuid4(), organization_id=organization_id, name="Qualified release",
            provider="TestProvider", resource_type="CLINICAL_DATABASE", version="1",
            genome_build="GRCh38", access_method="LOCAL", checksum="d" * 64,
            location=str(tmp_path / "qualified-release"), status="QUALIFIED",
            metadata_json={}, population_definition=None,
        )
        qualification = ResourceQualification(
            id=uuid4(), resource_id=resource.id,
            qualification_version="qualification-test-v1", status="QUALIFIED",
            checks_json={"passed": True}, qualified_by=user_id,
        )
        db.add_all([resource, qualification])
        db.commit()

        log_calls = []

        def capture_warning(message, *args):
            log_calls.append((message, args))

        monkeypatch.setattr(resources_api.logger, "warning", capture_warning)

        def fail_dispatch(*_args):
            raise OperationalError("broker unavailable; credential=must-not-be-logged")

        monkeypatch.setattr(
            "backend.app.infrastructure.queue.celery_app.scan_reanalysis_resources",
            SimpleNamespace(delay=fail_dispatch),
        )

        result = resources_api.activate_resource(
            resource.id,
            {"qualification_version": "qualification-test-v1"},
            db,
            _principal(organization_id),
        )

        db.refresh(resource)
        assert resource.status == "ACTIVE"
        assert result["status"] == "ACTIVE"
        assert result["reanalysis_scan_queued"] is False
        assert db.query(AuditEvent).filter_by(event_type="RESOURCE_VERSION_ACTIVATED").count() == 1
        assert log_calls == [(
            "Reanalysis scan dispatch failed; daily scan will recover "
            "(error_type=%s)",
            ("OperationalError",),
        )]
        assert "must-not-be-logged" not in repr(log_calls)
    finally:
        db.close()
        engine.dispose()


def test_resource_adoption_request_audits_actor_and_is_idempotent(tmp_path):
    engine, db = _db()
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Resource Lab", external_identifier="resource-lab"))
        resource, _ = _seed_remote_resource(db, organization_id, tmp_path / "cache")
        qualification = ResourceQualification(
            id=uuid4(), resource_id=resource.id,
            qualification_version="qualification-test-v1", status="QUALIFIED",
            checks_json={"passed": True}, qualified_by=None,
        )
        db.add(qualification)
        db.commit()
        principal = _principal(organization_id)
        payload = {"qualification_version": "qualification-test-v1"}

        first = resources_api.create_resource_approval_request(
            resource.id, payload, db, principal,
        )
        second = resources_api.create_resource_approval_request(
            resource.id, payload, db, principal,
        )

        assert first["approval_id"] == second["approval_id"]
        event = db.query(AuditEvent).filter_by(event_type="RESOURCE_ADOPTION_REQUESTED").one()
        assert event.actor_id == str(principal.user_id)
        assert event.subject_id == str(resource.id)
        assert event.workflow["organization_id"] == str(organization_id)
        assert event.after_state["approval_id"] == first["approval_id"]
        assert event.after_state["status"] == "PENDING"
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
        metadata = dict(resource.metadata_json)
        source_contract = dict(metadata["source_contract"])
        source_contract["license_status"] = "REVIEW_REQUIRED"
        metadata["source_contract"] = source_contract
        resource.metadata_json = metadata
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



@pytest.mark.parametrize("storage_backend", ["", "ORGANIZATION_UNKNOWN", "LOCAL_FILESYSTEM"])
def test_resource_staging_rejects_unsupported_storage_backend(monkeypatch, tmp_path, storage_backend):
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

        with pytest.raises((HTTPException, ValueError)):
            resources_api.create_resource_staging(
                resource.id,
                resources_api.ResourceStagingCreateRequest(
                    expected_size_bytes=len(payload),
                    storage_backend=storage_backend,
                ),
                db,
                _principal(organization_id),
            )
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

        dispatch = dict(db.get(ResourceStaging, UUID(staged["staging_id"])).metadata_json["staging_dispatch"])
        original_task_id = dispatch["task_id"]
        dispatch["published_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        staging_row = db.get(ResourceStaging, UUID(staged["staging_id"]))
        staging_row.metadata_json = {**staging_row.metadata_json, "staging_dispatch": dispatch}
        db.commit()
        monkeypatch.setattr(resources_api, "_celery_task_state", lambda _task_id: "PENDING")

        duplicate_retry = resources_api.execute_resource_staging(
            resource.id,
            UUID(staged["staging_id"]),
            db,
            _principal(organization_id),
        )
        assert duplicate_retry["dispatch"]["task_id"] == original_task_id
        assert duplicate_retry["dispatch"]["status"] == "PUBLISHED"
        assert len(published) == 1
    finally:
        db.close()
        engine.dispose()
