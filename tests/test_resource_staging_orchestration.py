from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.resource_staging import (
    ResourceStagingError,
    create_staging_candidate,
    stage_resource_release,
    staging_recovery_decision,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Resource, ResourceStaging


class FakeResponse:
    status = 200

    def __init__(self, payload: bytes):
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size=-1):
        if not self.payload:
            return b""
        chunk, self.payload = self.payload[:size], self.payload[size:]
        return chunk


class FakeOpener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Resource.__table__, ResourceStaging.__table__],
    )
    return engine, Session(engine)


def _remote_resource(access_mode="PUBLIC"):
    return Resource(
        id=uuid4(),
        organization_id=None,
        name="ClinVar",
        provider="NCBI",
        resource_type="EVIDENCE",
        version="2026-01",
        genome_build="GRCh38",
        access_method="HTTPS",
        license_text=None,
        checksum=None,
        location=None,
        status="CANDIDATE",
        population_definition=None,
        metadata_json={
            "source_contract": {
                "publisher": "NCBI",
                "canonical_source_url": "https://www.ncbi.nlm.nih.gov/clinvar/",
                "artifact_url": "https://ftp.ncbi.nlm.nih.gov/clinvar/release.xml.gz",
                "release_identity": "2026-01",
                "access_mode": access_mode,
                "license_status": "NOT_REQUIRED",
                "checksum_status": "PUBLISHED_AND_VERIFIED",
                "authority_evidence_url": "https://www.ncbi.nlm.nih.gov/clinvar/",
            }
        },
    )


def test_orchestrator_routes_public_https_resource_to_governed_remote(monkeypatch, tmp_path):
    payload = b"authoritative release"
    opener = FakeOpener(FakeResponse(payload))
    monkeypatch.setattr(
        "backend.app.domain.resource_remote_staging.build_opener",
        lambda *_: opener,
    )
    (tmp_path / "staged").mkdir()

    engine, db = _db()
    try:
        resource = _remote_resource()
        db.add(resource)
        db.flush()
        row = create_staging_candidate(
            db,
            resource=resource,
            source_uri="https://ftp.ncbi.nlm.nih.gov/clinvar/release.xml.gz",
            destination_uri=str(tmp_path / "staged" / "release.xml.gz"),
            expected_sha256=sha256(payload).hexdigest(),
            expected_size_bytes=len(payload),
        )
        result = stage_resource_release(db, row, max_remote_bytes=1024)
        assert result.status == "STAGED"
        assert Path(result.destination_uri).read_bytes() == payload
    finally:
        db.close()
        engine.dispose()


def test_orchestrator_does_not_use_generic_remote_path_for_authenticated_resource(tmp_path):
    (tmp_path / "staged").mkdir()
    engine, db = _db()
    try:
        resource = _remote_resource("AUTHENTICATED")
        db.add(resource)
        db.flush()
        row = create_staging_candidate(
            db,
            resource=resource,
            source_uri="https://ftp.ncbi.nlm.nih.gov/clinvar/release.xml.gz",
            destination_uri=str(tmp_path / "staged" / "release.xml.gz"),
            expected_sha256="0" * 64,
        )
        with pytest.raises(ResourceStagingError, match="PUBLIC source contract"):
            stage_resource_release(db, row)
        assert not Path(row.destination_uri).exists()
    finally:
        db.close()
        engine.dispose()


def test_orchestrator_rejects_source_contract_artifact_mismatch(tmp_path):
    (tmp_path / "staged").mkdir()
    engine, db = _db()
    try:
        resource = _remote_resource()
        db.add(resource)
        db.flush()
        row = create_staging_candidate(
            db,
            resource=resource,
            source_uri="https://ftp.ncbi.nlm.nih.gov/clinvar/other.xml.gz",
            destination_uri=str(tmp_path / "staged" / "release.xml.gz"),
            expected_sha256="0" * 64,
        )
        with pytest.raises(ResourceStagingError, match="does not match the registered source contract"):
            stage_resource_release(db, row)
    finally:
        db.close()
        engine.dispose()


def test_checksum_failure_produces_explicit_lab_action_and_preserves_active_release(
    monkeypatch, tmp_path
):
    payload = b"tampered release"
    opener = FakeOpener(FakeResponse(payload))
    monkeypatch.setattr(
        "backend.app.domain.resource_remote_staging.build_opener",
        lambda *_: opener,
    )
    (tmp_path / "staged").mkdir()

    engine, db = _db()
    try:
        active = _remote_resource()
        active.id = uuid4()
        active.version = "2025-12"
        active.status = "ACTIVE"
        active.metadata_json = {}
        candidate = _remote_resource()
        db.add_all([active, candidate])
        db.flush()
        row = create_staging_candidate(
            db,
            resource=candidate,
            source_uri="https://ftp.ncbi.nlm.nih.gov/clinvar/release.xml.gz",
            destination_uri=str(tmp_path / "staged" / "release.xml.gz"),
            expected_sha256="0" * 64,
            expected_size_bytes=len(payload),
        )

        result = stage_resource_release(db, row, max_remote_bytes=1024)
        decision = staging_recovery_decision(result)

        assert result.status == "INTEGRITY_FAILED"
        assert result.error_code == "CHECKSUM_MISMATCH"
        assert decision.action.value == "REQUEST_LAB_ACTION"
        assert decision.lab_action_required is True
        assert db.get(Resource, active.id).status == "ACTIVE"
        assert not Path(result.destination_uri).exists()
    finally:
        db.close()
        engine.dispose()


def test_transient_remote_failure_is_retryable_without_touching_active_release(
    monkeypatch, tmp_path
):
    (tmp_path / "staged").mkdir()

    class FailingOpener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 503, "temporary unavailable", {}, None)

    monkeypatch.setattr(
        "backend.app.domain.resource_remote_staging.build_opener",
        lambda *_: FailingOpener(),
    )

    engine, db = _db()
    try:
        active = _remote_resource()
        active.id = uuid4()
        active.version = "2025-12"
        active.status = "ACTIVE"
        active.metadata_json = {}
        candidate = _remote_resource()
        db.add_all([active, candidate])
        db.flush()
        row = create_staging_candidate(
            db,
            resource=candidate,
            source_uri="https://ftp.ncbi.nlm.nih.gov/clinvar/release.xml.gz",
            destination_uri=str(tmp_path / "staged" / "release.xml.gz"),
            expected_sha256="0" * 64,
        )

        with pytest.raises(ResourceStagingError) as exc_info:
            stage_resource_release(db, row, max_remote_bytes=1024)

        decision = staging_recovery_decision(row)

        assert exc_info.value.retryable is True
        assert row.error_code == "REMOTE_HTTP_RETRYABLE"
        assert row.metadata_json["recovery_outcome"] == "RETRYABLE_FAILURE"
        assert decision.action.value == "RETRY"
        assert decision.retryable is True
        assert db.get(Resource, active.id).status == "ACTIVE"
    finally:
        db.close()
        engine.dispose()
