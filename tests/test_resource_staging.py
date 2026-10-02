from hashlib import sha256

import pytest

from backend.app.domain.resource_staging import ResourceStagingError, stage_and_verify


class FakeStager:
    def __init__(self, payload: bytes):
        self.payload = payload

    def stage(self, descriptor, destination):
        destination.write_bytes(self.payload)
        return type(
            "Staged",
            (),
            {
                "source": "fake-provider",
                "local_path": str(destination),
                "sha256": "provider-reported",
                "size_bytes": len(self.payload),
                "metadata": {"provider_version": descriptor["version"]},
            },
        )()


def test_stage_and_verify_requires_expected_integrity(tmp_path):
    payload = b"SIRALOOM resource"
    expected = sha256(payload).hexdigest()
    result = stage_and_verify(
        FakeStager(payload),
        {"version": "2026.09"},
        tmp_path / "staged-resource.bin",
        expected,
    )
    assert result.sha256 == expected
    assert result.size_bytes == len(payload)
    assert result.metadata["integrity"] == "SHA-256"


def test_stage_and_verify_rejects_tampered_resource(tmp_path):
    payload = b"original"
    path = tmp_path / "resource.bin"
    with pytest.raises(ResourceStagingError, match="checksum mismatch"):
        stage_and_verify(
            FakeStager(payload),
            {"version": "2026.09"},
            path,
            sha256(b"tampered").hexdigest(),
        )


from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.resource_staging import (
    create_staging_candidate,
    prepare_staging,
    stage_local_artifact,
    transition_staging,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Resource, ResourceStaging


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Resource.__table__, ResourceStaging.__table__])
    return engine, Session(engine)


def _resource(*, organization_id=None):
    return Resource(
        id=uuid4(),
        organization_id=organization_id,
        name="reference",
        provider="ReferenceProvider",
        resource_type="REFERENCE_PACKAGE",
        version="GRCh38-v1",
        genome_build="GRCh38",
        access_method="LOCAL",
        license_text=None,
        checksum=None,
        location=None,
        status="CANDIDATE",
        population_definition=None,
        metadata_json={},
    )


def test_candidate_registration_is_idempotent():
    engine, db = _db()
    try:
        resource = _resource()
        db.add(resource)
        db.flush()
        first = create_staging_candidate(
            db, resource=resource, source_uri="/incoming/GRCh38.fa",
            destination_uri="/var/lib/siraloom/GRCh38.fa",
        )
        second = create_staging_candidate(
            db, resource=resource, source_uri="/incoming/GRCh38.fa",
            destination_uri="/var/lib/siraloom/GRCh38.fa",
        )
        assert first.id == second.id
    finally:
        db.close()
        engine.dispose()


def test_prepare_staging_records_storage_preflight(tmp_path: Path):
    engine, db = _db()
    try:
        resource = _resource()
        db.add(resource)
        db.flush()
        row = create_staging_candidate(
            db, resource=resource, source_uri="/incoming/GRCh38.fa",
            destination_uri=str(tmp_path / "staged" / "GRCh38.fa"), expected_size_bytes=4,
        )
        assert prepare_staging(db, row).status == "READY_TO_STAGE"
        assert row.metadata_json["storage_preflight"]["passed"] is True
    finally:
        db.close()
        engine.dispose()


def test_local_staging_is_atomic_and_checksum_verified(tmp_path: Path):
    engine, db = _db()
    try:
        source = tmp_path / "incoming.fa"
        source.write_bytes(b">1\\nACGT\\n")
        destination = tmp_path / "staged" / "GRCh38.fa"
        checksum = sha256(source.read_bytes()).hexdigest()
        resource = _resource()
        db.add(resource)
        db.flush()
        row = create_staging_candidate(
            db, resource=resource, source_uri=str(source), destination_uri=str(destination),
            expected_sha256=checksum, expected_size_bytes=source.stat().st_size,
        )
        staged = stage_local_artifact(db, row, source_path=source)
        assert staged.status == "STAGED"
        assert destination.read_bytes() == source.read_bytes()
        assert staged.observed_sha256 == checksum
    finally:
        db.close()
        engine.dispose()


def test_checksum_mismatch_never_activates_destination(tmp_path: Path):
    engine, db = _db()
    try:
        source = tmp_path / "incoming.fa"
        source.write_bytes(b">1\\nACGT\\n")
        destination = tmp_path / "staged" / "GRCh38.fa"
        resource = _resource()
        db.add(resource)
        db.flush()
        row = create_staging_candidate(
            db, resource=resource, source_uri=str(source), destination_uri=str(destination),
            expected_sha256="0" * 64,
        )
        staged = stage_local_artifact(db, row, source_path=source)
        assert staged.status == "INTEGRITY_FAILED"
        assert staged.error_code == "CHECKSUM_MISMATCH"
        assert not destination.exists()
    finally:
        db.close()
        engine.dispose()


def test_organization_resource_cannot_use_siraloom_storage(tmp_path: Path):
    engine, db = _db()
    try:
        resource = _resource(organization_id=uuid4())
        db.add(resource)
        db.flush()
        with pytest.raises(ResourceStagingError, match="organization-managed"):
            create_staging_candidate(
                db, resource=resource, source_uri="/lab/reference.fa",
                destination_uri=str(tmp_path / "reference.fa"),
            )
    finally:
        db.close()
        engine.dispose()


def test_staging_state_machine_rejects_skipping_preflight(tmp_path: Path):
    engine, db = _db()
    try:
        resource = _resource()
        db.add(resource)
        db.flush()
        row = create_staging_candidate(
            db, resource=resource, source_uri="/incoming/GRCh38.fa",
            destination_uri=str(tmp_path / "reference.fa"),
        )
        with pytest.raises(ResourceStagingError, match="invalid staging transition"):
            transition_staging(db, row, "STAGED")
    finally:
        db.close()
        engine.dispose()
