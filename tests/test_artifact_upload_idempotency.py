from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.domain.upload_idempotency import (
    idempotency_key_sha256,
    upload_request_fingerprint,
)
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.artifacts.upload_intents import (
    UploadIdempotencyConflict,
    reserve_upload_intent,
)
from backend.app.infrastructure.db.artifact_upload_intents import ArtifactUploadIntent
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db import models as _models
from backend.app.infrastructure.db.models import Artifact, Case, Organization, User


def _request_fingerprint(content: bytes = b"VCF source bytes") -> str:
    import hashlib

    return upload_request_fingerprint(
        content_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        filename="sample.vcf",
        artifact_type="VCF",
        media_type="text/vcf",
        genome_build="GRCh38",
        specimen_id=None,
        paired_artifact_id=None,
    )


def _database(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'upload-idempotency.db'}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    db.add(Organization(
        id=organization_id,
        name="Upload Recovery Lab",
        external_identifier=str(organization_id),
    ))
    db.flush()
    db.add(User(
        id=user_id,
        organization_id=organization_id,
        external_subject=str(user_id),
        email=f"{user_id}@test.local",
        display_name="Upload Recovery",
        role="ADMIN",
        status="ACTIVE",
    ))
    db.flush()
    db.add(Case(
        id=case_id,
        organization_id=organization_id,
        case_identifier=f"UPLOAD-RECOVERY-{case_id}",
        status="OPEN",
        clinical_context={},
        language="en",
        created_by=user_id,
    ))
    db.commit()
    return engine, db, organization_id, case_id


def test_idempotency_key_is_hashed_and_rejects_ambiguous_values():
    key = "client-upload-request-000001"
    digest = idempotency_key_sha256(key)

    assert digest is not None
    assert len(digest) == 64
    assert digest != key
    assert idempotency_key_sha256(None) is None

    with pytest.raises(ValueError, match="between 16 and 255"):
        idempotency_key_sha256("short")
    with pytest.raises(ValueError, match="printable"):
        idempotency_key_sha256("client upload request 000001")


def test_upload_intent_reuses_identity_and_rejects_changed_request(tmp_path):
    engine, db, organization_id, case_id = _database(tmp_path)
    try:
        key_hash = idempotency_key_sha256("client-upload-request-000001")
        fingerprint = _request_fingerprint()
        first, created = reserve_upload_intent(
            db,
            organization_id=organization_id,
            case_id=case_id,
            key_sha256=key_hash,
            request_fingerprint=fingerprint,
        )
        replay, replay_created = reserve_upload_intent(
            db,
            organization_id=organization_id,
            case_id=case_id,
            key_sha256=key_hash,
            request_fingerprint=fingerprint,
        )

        assert created is True
        assert replay_created is False
        assert replay.id == first.id
        assert replay.artifact_id == first.artifact_id
        assert replay.status == "RESERVED"

        with pytest.raises(UploadIdempotencyConflict):
            reserve_upload_intent(
                db,
                organization_id=organization_id,
                case_id=case_id,
                key_sha256=key_hash,
                request_fingerprint=_request_fingerprint(b"different VCF bytes"),
            )
    finally:
        db.close()
        engine.dispose()


def test_upload_idempotency_scope_is_tenant_and_case_bound(tmp_path):
    engine, db, organization_id, case_id = _database(tmp_path)
    try:
        key_hash = idempotency_key_sha256("client-upload-request-000002")
        fingerprint = _request_fingerprint()
        first, _ = reserve_upload_intent(
            db,
            organization_id=organization_id,
            case_id=case_id,
            key_sha256=key_hash,
            request_fingerprint=fingerprint,
        )

        other_case_id = uuid4()
        db.add(Case(
            id=other_case_id,
            organization_id=organization_id,
            case_identifier=f"UPLOAD-RECOVERY-{other_case_id}",
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=db.scalar(select(User.id).where(User.organization_id == organization_id)),
        ))
        db.commit()
        other_case, created = reserve_upload_intent(
            db,
            organization_id=organization_id,
            case_id=other_case_id,
            key_sha256=key_hash,
            request_fingerprint=fingerprint,
        )

        assert created is True
        assert other_case.artifact_id != first.artifact_id
    finally:
        db.close()
        engine.dispose()


def test_reserved_upload_recovers_identical_orphaned_storage_bytes(tmp_path):
    engine, db, organization_id, case_id = _database(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "sample.vcf"
    content = b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    source.write_bytes(content)
    try:
        intent, created = reserve_upload_intent(
            db,
            organization_id=organization_id,
            case_id=case_id,
            key_sha256=idempotency_key_sha256("client-upload-request-000003"),
            request_fingerprint=_request_fingerprint(content),
        )
        assert created is True
        storage_uri = store.uri_for_artifact(
            case_id=case_id,
            artifact_id=intent.artifact_id,
            filename="sample.vcf",
        )

        original_flush = db.flush

        def fail_after_object_publish(*_args, **_kwargs):
            raise RuntimeError("simulated API process failure before artifact-row flush")

        db.flush = fail_after_object_publish
        with pytest.raises(RuntimeError, match="simulated API process failure"):
            store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=None,
                source_path=source,
                filename="sample.vcf",
                artifact_type="VCF",
                media_type="text/vcf",
                genome_build="GRCh38",
                metadata={
                    "ingestion": {
                        "upload_request_fingerprint": _request_fingerprint(content),
                    }
                },
                validation_status="VALID",
                artifact_id=intent.artifact_id,
            )
        db.rollback()
        db.flush = original_flush

        assert db.get(Artifact, intent.artifact_id) is None
        assert store.exists(storage_uri)
        assert store.read_bytes(storage_uri) == content

        recovered = store.put_file(
            db=db,
            case_id=case_id,
            analysis_id=None,
            source_path=source,
            filename="sample.vcf",
            artifact_type="VCF",
            media_type="text/vcf",
            genome_build="GRCh38",
            metadata={
                "ingestion": {
                    "upload_request_fingerprint": _request_fingerprint(content),
                }
            },
            validation_status="VALID",
            artifact_id=intent.artifact_id,
        )
        intent.status = "COMMITTED"
        db.commit()

        assert recovered.id == intent.artifact_id
        assert recovered.sha256 == __import__("hashlib").sha256(content).hexdigest()
        assert store.read_bytes(storage_uri) == content
        assert db.scalar(
            select(func.count(Artifact.id)).where(Artifact.id == intent.artifact_id)
        ) == 1
        assert db.get(ArtifactUploadIntent, intent.id).status == "COMMITTED"
    finally:
        db.close()
        engine.dispose()
