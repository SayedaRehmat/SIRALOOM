from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.resource_remote_staging import stage_remote_artifact
from backend.app.domain.resource_staging import ResourceStagingError, create_staging_candidate
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Resource, ResourceStaging


class FakeResponse:
    status = 200

    def __init__(self, payload: bytes, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = headers or {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size: int = -1):
        if not self.payload:
            return b""
        if size < 0:
            chunk, self.payload = self.payload, b""
            return chunk
        chunk, self.payload = self.payload[:size], self.payload[size:]
        return chunk


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Resource.__table__, ResourceStaging.__table__])
    return engine, Session(engine)


def _resource():
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
        metadata_json={},
    )


def _row(db, tmp_path: Path, payload: bytes, checksum: str | None = None, size: int | None = None):
    resource = _resource()
    db.add(resource)
    db.flush()
    (tmp_path / "staged").mkdir(parents=True, exist_ok=True)
    return create_staging_candidate(
        db,
        resource=resource,
        source_uri="https://ftp.ncbi.nlm.nih.gov/clinvar/release.xml.gz",
        destination_uri=str(tmp_path / "staged" / "release.xml.gz"),
        expected_sha256=checksum or sha256(payload).hexdigest(),
        expected_size_bytes=size if size is not None else len(payload),
        staging_key="ncbi:2026-01:release.xml.gz",
    )


def test_remote_staging_requires_allowlisted_publisher(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        row = _row(db, tmp_path, b"payload")
        with pytest.raises(ResourceStagingError, match="not in the governed publisher allow-list"):
            stage_remote_artifact(db, row, allowed_hosts={"example.org"}, max_bytes=1024)
        assert row.status == "INTEGRITY_FAILED"
        assert row.error_code == "REMOTE_ACQUISITION_REJECTED"
        assert not Path(row.destination_uri).exists()
    finally:
        db.close()
        engine.dispose()


def test_remote_staging_streams_and_atomically_verifies(monkeypatch, tmp_path):
    payload = b"authoritative release bytes"
    opener = FakeOpener(FakeResponse(payload))
    monkeypatch.setattr(
        "backend.app.domain.resource_remote_staging.build_opener",
        lambda *_: opener,
    )
    engine, db = _db()
    try:
        row = _row(db, tmp_path, payload)
        staged = stage_remote_artifact(
            db,
            row,
            allowed_hosts={"ftp.ncbi.nlm.nih.gov"},
            max_bytes=1024,
        )
        destination = Path(row.destination_uri)
        assert staged.status == "STAGED"
        assert destination.read_bytes() == payload
        assert staged.observed_sha256 == sha256(payload).hexdigest()
        assert staged.metadata_json["integrity"] == "SHA256_VERIFIED"
        assert opener.requests[0][0].get_header("User-agent") == "SIRALOOM-resource-stager/1"
    finally:
        db.close()
        engine.dispose()


def test_remote_staging_rejects_checksum_before_activation(monkeypatch, tmp_path):
    payload = b"tampered release"
    opener = FakeOpener(FakeResponse(payload))
    monkeypatch.setattr(
        "backend.app.domain.resource_remote_staging.build_opener",
        lambda *_: opener,
    )
    engine, db = _db()
    try:
        row = _row(db, tmp_path, payload, checksum="0" * 64)
        staged = stage_remote_artifact(
            db,
            row,
            allowed_hosts={"ftp.ncbi.nlm.nih.gov"},
            max_bytes=1024,
        )
        assert staged.status == "INTEGRITY_FAILED"
        assert staged.error_code == "CHECKSUM_MISMATCH"
        assert not Path(row.destination_uri).exists()
    finally:
        db.close()
        engine.dispose()


def test_remote_staging_rejects_oversized_content(monkeypatch, tmp_path):
    payload = b"123456789"
    opener = FakeOpener(FakeResponse(payload))
    monkeypatch.setattr(
        "backend.app.domain.resource_remote_staging.build_opener",
        lambda *_: opener,
    )
    engine, db = _db()
    try:
        row = _row(db, tmp_path, payload)
        with pytest.raises(ResourceStagingError, match="exceeds configured maximum"):
            stage_remote_artifact(
                db,
                row,
                allowed_hosts={"ftp.ncbi.nlm.nih.gov"},
                max_bytes=4,
            )
        assert row.status == "INTEGRITY_FAILED"
        assert not Path(row.destination_uri).exists()
    finally:
        db.close()
        engine.dispose()
