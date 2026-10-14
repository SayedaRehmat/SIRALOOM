from datetime import datetime, timezone
from uuid import uuid4, uuid5

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, Organization, User
from backend.app.workflows.variant import _put_idempotent_stage_artifact


def test_report_pdf_artifact_replay_reuses_same_identity_and_rejects_changed_bytes(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'report-artifact-replay.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    artifact_id = uuid5(analysis_id, "siraloom:report-pdf:draft:v1:1")
    store = ArtifactStore(tmp_path / "artifacts")
    first_source = tmp_path / "report-first.pdf"
    replay_source = tmp_path / "report-replay.pdf"
    changed_source = tmp_path / "report-changed.pdf"
    first_source.write_bytes(b"%PDF-1.7\ncontrolled report bytes\n")
    replay_source.write_bytes(first_source.read_bytes())
    changed_source.write_bytes(b"%PDF-1.7\nchanged report bytes\n")
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Report Replay Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Report Replay Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"REPORT-REPLAY-{case_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="report-replay-test",
                status="RUNNING",
                queue_task_id="report-replay",
                reference_build="GRCh38",
                configuration={},
                started_at=datetime.now(timezone.utc),
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

            metadata = {
                "rendered_format": "PDF",
                "report_schema_version": "1",
                "report_status": "DRAFT",
            }
            first = _put_idempotent_stage_artifact(
                store,
                artifact_id=artifact_id,
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=first_source,
                filename="report_v1.pdf",
                artifact_type="REPORT_PDF",
                media_type="application/pdf",
                genome_build="GRCh38",
                metadata=metadata,
            )
            db.commit()
            replay = _put_idempotent_stage_artifact(
                store,
                artifact_id=artifact_id,
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=replay_source,
                filename="report_v1.pdf",
                artifact_type="REPORT_PDF",
                media_type="application/pdf",
                genome_build="GRCh38",
                metadata=metadata,
            )
            assert replay.id == first.id == artifact_id
            assert db.scalar(select(func.count(Artifact.id)).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "REPORT_PDF",
            )) == 1

            with pytest.raises(RuntimeError, match="produced different bytes on replay"):
                _put_idempotent_stage_artifact(
                    store,
                    artifact_id=artifact_id,
                    db=db,
                    case_id=case_id,
                    analysis_id=analysis_id,
                    source_path=changed_source,
                    filename="report_v1.pdf",
                    artifact_type="REPORT_PDF",
                    media_type="application/pdf",
                    genome_build="GRCh38",
                    metadata=metadata,
                )
    finally:
        engine.dispose()
