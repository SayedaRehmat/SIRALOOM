import hashlib
import zipfile
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.domain.artifact_integrity import ArtifactIntegrityError
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Artifact, Organization, User, Case, CaseExport
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.domain.local_uri import local_path_from_uri
from backend.app.reporting.export_service import build_case_export

def test_case_export_contains_core_manifests(tmp_path):
    e=create_engine("sqlite+pysqlite:///:memory:"); Base.metadata.create_all(e); db=Session(e)
    org=Organization(id=uuid4(),name="Lab"); user=User(id=uuid4(),organization_id=org.id,display_name="Auditor",role="AUDITOR",status="ACTIVE")
    case=Case(id=uuid4(),organization_id=org.id,case_identifier="CASE-X",status="ACTIVE",clinical_context={},language="en",created_by=user.id)
    export=CaseExport(id=uuid4(),case_id=case.id,requested_by=user.id,status="RUNNING",include_artifacts=False,include_reports=False,include_evidence=True,include_audit=True,include_provenance=True)
    db.add_all([org,user,case,export]); db.commit()
    artifact=build_case_export(db,export=export,store=ArtifactStore(str(tmp_path)))
    assert artifact.artifact_type == "AUDIT_PACKAGE"
    data=local_path_from_uri(artifact.storage_uri).read_bytes()
    assert data[:2] == b"PK"


def test_case_export_uses_durable_export_id_as_artifact_identity(tmp_path):
    e = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(e)
    db = Session(e)

    org = Organization(id=uuid4(), name="Lab")
    user = User(
        id=uuid4(),
        organization_id=org.id,
        display_name="Auditor",
        role="AUDITOR",
        status="ACTIVE",
    )
    case = Case(
        id=uuid4(),
        organization_id=org.id,
        case_identifier="CASE-IDEMPOTENT",
        status="ACTIVE",
        clinical_context={},
        language="en",
        created_by=user.id,
    )
    export = CaseExport(
        id=uuid4(),
        case_id=case.id,
        requested_by=user.id,
        status="RUNNING",
        include_artifacts=False,
        include_reports=False,
        include_evidence=True,
        include_audit=True,
        include_provenance=True,
    )
    db.add_all([org, user, case, export])
    db.commit()

    artifact = build_case_export(
        db,
        export=export,
        store=ArtifactStore(str(tmp_path)),
    )

    assert artifact.id == export.id
    assert artifact.metadata_json["export_id"] == str(export.id)


def _case_export_fixture(*, include_artifacts=True):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    org = Organization(id=uuid4(), name="Lab")
    user = User(id=uuid4(), organization_id=org.id, display_name="Auditor", role="AUDITOR", status="ACTIVE")
    case = Case(id=uuid4(), organization_id=org.id, case_identifier="CASE-FILES", status="ACTIVE", clinical_context={}, language="en", created_by=user.id)
    export = CaseExport(id=uuid4(), case_id=case.id, requested_by=user.id, status="RUNNING", include_artifacts=include_artifacts, include_reports=False, include_evidence=False, include_audit=False, include_provenance=False)
    db.add_all([org, user, case, export])
    db.commit()
    return db, case, export


def test_case_export_verifies_local_artifact_bytes_before_packaging(tmp_path):
    db, case, export = _case_export_fixture()
    store = ArtifactStore(str(tmp_path / "store"))
    source = tmp_path / "input.vcf"
    source.write_bytes(b"trusted input")
    stored = store.put_file(
        db=db, case_id=case.id, analysis_id=None, source_path=source,
        filename=source.name, artifact_type="VCF", media_type="text/plain",
        genome_build="GRCh38", artifact_id=uuid4(),
    )
    stored_file = store.local_path(stored.storage_uri)

    package = build_case_export(db, export=export, store=store)
    with zipfile.ZipFile(store.local_path(package.storage_uri)) as archive:
        assert archive.read(f"artifacts/{stored.id}-{stored.filename}") == b"trusted input"

    stored_file.write_bytes(b"tampered input")
    with pytest.raises(ArtifactIntegrityError):
        build_case_export(db, export=export, store=store)


def test_case_export_downloads_and_verifies_cloud_artifacts(tmp_path):
    db, case, export = _case_export_fixture()
    content = b"cloud input"
    artifact = Artifact(
        id=uuid4(), case_id=case.id, analysis_id=None, artifact_type="VCF",
        filename="cloud.vcf", media_type="text/plain", size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(), storage_uri="gs://test-bucket/input",
        genome_build="GRCh38", validation_status="VALID", metadata_json={},
    )
    db.add(artifact)
    db.commit()

    class CloudStore:
        package_path = None

        def download_to_file(self, uri, destination, *, expected_sha256, expected_size_bytes):
            assert uri == artifact.storage_uri
            assert expected_sha256 == artifact.sha256
            assert expected_size_bytes == artifact.size_bytes
            Path(destination).write_bytes(content)

        def put_file(self, *, db, case_id, analysis_id, source_path, filename, artifact_type, media_type, genome_build, metadata, artifact_id):
            target = tmp_path / filename
            target.write_bytes(Path(source_path).read_bytes())
            self.package_path = target
            return Artifact(
                id=artifact_id, case_id=case_id, analysis_id=analysis_id,
                artifact_type=artifact_type, filename=filename, media_type=media_type,
                size_bytes=target.stat().st_size, sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                storage_uri=target.as_uri(), genome_build=genome_build,
                validation_status="VALID", metadata_json=metadata,
            )

    cloud_store = CloudStore()
    build_case_export(db, export=export, store=cloud_store)
    with zipfile.ZipFile(cloud_store.package_path) as archive:
        assert archive.read(f"artifacts/{artifact.id}-{artifact.filename}") == content
