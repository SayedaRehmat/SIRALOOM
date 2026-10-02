from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.resource_lifecycle import run_resource_lifecycle
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Resource, ResourceQualification, ResourceStaging


_TEST_REFERENCE_PAYLOAD = b">1\\nCAAAAAC\\n"
_TEST_REFERENCE_CHECKSUM = sha256(_TEST_REFERENCE_PAYLOAD).hexdigest()


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Resource.__table__,
            ResourceStaging.__table__,
            ResourceQualification.__table__,
        ],
    )
    return engine


def _local_resource(*, checksum: str = _TEST_REFERENCE_CHECKSUM) -> Resource:
    return Resource(
        id=uuid4(),
        organization_id=None,
        name="GRCh38 reference",
        provider="ReferenceAuthority",
        resource_type="REFERENCE",
        version="GRCh38-2026.1",
        genome_build="GRCh38",
        access_method="LOCAL",
        license_text=None,
        checksum=checksum,
        location=None,
        status="CANDIDATE",
        population_definition=None,
        metadata_json={
            "source_contract": {
                "publisher": "ReferenceAuthority",
                "canonical_source_url": "https://example.org/reference",
                "artifact_url": "https://example.org/reference/GRCh38-2026.1.fa",
                "release_identity": "GRCh38-2026.1",
                "access_mode": "PUBLIC",
                "license_status": "NOT_REQUIRED",
                "checksum_status": "PUBLISHED_AND_VERIFIED",
                "authority_evidence_url": "https://example.org/reference/docs",
            },
            "execution": {
                "provider_id": "ReferenceAuthority",
                "provider_version": "reference-v1",
                "access_method": "LOCAL",
                "location": "",
            },
        },
    )


def _create_staging(db: Session, resource: Resource, destination: Path, checksum: str):
    from backend.app.domain.resource_staging import create_staging_candidate

    return create_staging_candidate(
        db,
        resource=resource,
        source_uri="https://example.org/reference/GRCh38-2026.1.fa",
        destination_uri=str(destination),
        storage_backend="LOCAL_FILESYSTEM",
        expected_sha256=checksum,
        expected_size_bytes=len(_TEST_REFERENCE_PAYLOAD),
    )


def test_lifecycle_advances_candidate_to_staged_and_qualified(tmp_path):
    source = tmp_path / "source.fa"
    source.write_bytes(_TEST_REFERENCE_PAYLOAD)
    destination_dir = tmp_path / "staged"
    destination_dir.mkdir()

    engine = _db()
    with Session(engine) as db:
        resource = _local_resource()
        db.add(resource)
        db.flush()
        row = _create_staging(
            db,
            resource,
            destination_dir / "GRCh38-2026.1.fa",
            _TEST_REFERENCE_CHECKSUM,
        )
        resource.metadata_json["execution"]["location"] = str(
            destination_dir / "GRCh38-2026.1.fa"
        )

        result = run_resource_lifecycle(
            db,
            resource_id=resource.id,
            local_source_path=source,
        )

        assert result.stage == "QUALIFIED"
        assert result.staging is row
        assert row.status == "STAGED"
        assert result.qualification is not None
        assert result.qualification.status == "QUALIFIED"
        assert resource.status == "QUALIFIED"
        assert resource.location == str(destination_dir / "GRCh38-2026.1.fa")
        assert db.query(ResourceQualification).count() == 1


def test_lifecycle_is_idempotent_after_qualification(tmp_path):
    source = tmp_path / "source.fa"
    source.write_bytes(_TEST_REFERENCE_PAYLOAD)
    destination_dir = tmp_path / "staged"
    destination_dir.mkdir()

    engine = _db()
    with Session(engine) as db:
        resource = _local_resource()
        db.add(resource)
        db.flush()
        _create_staging(
            db,
            resource,
            destination_dir / "GRCh38-2026.1.fa",
            _TEST_REFERENCE_CHECKSUM,
        )
        resource.metadata_json["execution"]["location"] = str(
            destination_dir / "GRCh38-2026.1.fa"
        )

        first = run_resource_lifecycle(
            db,
            resource_id=resource.id,
            local_source_path=source,
        )
        first_attempt = first.staging.attempt

        second = run_resource_lifecycle(
            db,
            resource_id=resource.id,
            local_source_path=source,
        )

        assert first.stage == "QUALIFIED"
        assert second.stage == "QUALIFIED"
        assert second.staging.attempt == first_attempt
        assert db.query(ResourceQualification).count() == 1
        assert resource.status == "QUALIFIED"


def test_lifecycle_does_not_activate_or_replace_existing_active_release(tmp_path):
    source = tmp_path / "source.fa"
    source.write_bytes(_TEST_REFERENCE_PAYLOAD)
    destination_dir = tmp_path / "staged"
    destination_dir.mkdir()

    engine = _db()
    with Session(engine) as db:
        active = _local_resource()
        active.id = uuid4()
        active.version = "GRCh38-2025.4"
        active.status = "ACTIVE"
        active.location = str(tmp_path / "existing.fa")

        candidate = _local_resource()
        db.add_all([active, candidate])
        db.flush()
        _create_staging(
            db,
            candidate,
            destination_dir / "GRCh38-2026.1.fa",
            _TEST_REFERENCE_CHECKSUM,
        )
        candidate.metadata_json["execution"]["location"] = str(
            destination_dir / "GRCh38-2026.1.fa"
        )

        result = run_resource_lifecycle(
            db,
            resource_id=candidate.id,
            local_source_path=source,
        )

        assert result.stage == "QUALIFIED"
        assert candidate.status == "QUALIFIED"
        assert active.status == "ACTIVE"


def test_lifecycle_reports_missing_staging_configuration(tmp_path):
    engine = _db()
    with Session(engine) as db:
        resource = _local_resource()
        db.add(resource)
        db.flush()

        result = run_resource_lifecycle(db, resource_id=resource.id)

        assert result.stage == "WAITING_FOR_STAGING_CONFIGURATION"
        assert result.staging is None
        assert resource.status == "CANDIDATE"
