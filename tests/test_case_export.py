from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, User, Case, CaseExport
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.reporting.export_service import build_case_export

def test_case_export_contains_core_manifests(tmp_path):
    e=create_engine("sqlite+pysqlite:///:memory:"); Base.metadata.create_all(e); db=Session(e)
    org=Organization(id=uuid4(),name="Lab"); user=User(id=uuid4(),organization_id=org.id,display_name="Auditor",role="AUDITOR",status="ACTIVE")
    case=Case(id=uuid4(),organization_id=org.id,case_identifier="CASE-X",status="ACTIVE",clinical_context={},language="en",created_by=user.id)
    export=CaseExport(id=uuid4(),case_id=case.id,requested_by=user.id,status="RUNNING",include_artifacts=False,include_reports=False,include_evidence=True,include_audit=True,include_provenance=True)
    db.add_all([org,user,case,export]); db.commit()
    artifact=build_case_export(db,export=export,store=ArtifactStore(str(tmp_path)))
    assert artifact.artifact_type == "AUDIT_PACKAGE"
    data=Path(artifact.storage_uri.removeprefix("file://")).read_bytes()
    assert data[:2] == b"PK"
