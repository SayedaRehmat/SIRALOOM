import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus
from backend.app.infrastructure.db.models import (
    Analysis,
    Annotation,
    Case,
    Organization,
    Resource,
    User,
    Variant,
)


@pytest.mark.integration
def test_postgres_annotation_observation_identity_is_unique_per_governed_release():
    """The database must prevent duplicate annotation observations for one exact release."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    variant_id = uuid4()
    resource_id = uuid4()
    second_resource_id = uuid4()

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"annotation-identity-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@example.test",
                display_name="Annotation Identity Test",
                role="LAB_DIRECTOR",
                status="ACTIVE",
            ))
            db.commit()

            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=str(case_id),
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()

            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="GERMLINE",
                workflow_id="integration",
                workflow_version="1",
                status=AnalysisStatus.RUNNING,
                queue_task_id=None,
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.add(Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=1000,
                reference="A",
                alternate="G",
                normalization_status="NORMALIZED",
                canonical_key=f"GRCh38:1:1000:A:G:{variant_id}",
                identifiers={},
            ))
            for rid, version in ((resource_id, "115"), (second_resource_id, "116")):
                db.add(Resource(
                    id=rid,
                    organization_id=organization_id,
                    name=f"VEP-{version}",
                    provider="Ensembl VEP",
                    resource_type="ANNOTATION",
                    version=version,
                    genome_build="GRCh38",
                    access_method="LOCAL",
                    license_text=None,
                    checksum=f"sha256-{version}",
                    location=f"/resources/vep/{version}",
                    status="ACTIVE",
                    population_definition=None,
                    metadata_json={},
                ))
            db.commit()

            common = dict(
                variant_id=variant_id,
                analysis_id=analysis_id,
                provider_name="VEP",
                provider_version="115",
                resource_id=resource_id,
                resource_name="VEP-115",
                resource_version="115",
                request_fingerprint="request-1",
                response_sha256="response-1",
                request_metadata={},
                observed_at=None,
                retry_count=0,
                payload={"normalized": {"gene": {"symbol": "TEST"}}},
            )
            db.add(Annotation(id=uuid4(), **common))
            db.commit()

            db.add(Annotation(id=uuid4(), **common))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()

            # A different governed resource release is a distinct observation
            # identity and is allowed to exist, rather than being collapsed into
            # the older release.
            db.add(Annotation(
                id=uuid4(),
                **{
                    **common,
                    "resource_id": second_resource_id,
                    "resource_name": "VEP-116",
                    "resource_version": "116",
                    "request_fingerprint": "request-2",
                    "response_sha256": "response-2",
                },
            ))
            db.commit()

            rows = db.scalars(
                select(Annotation).where(Annotation.analysis_id == analysis_id)
            ).all()
            assert len(rows) == 2
            assert {row.resource_version for row in rows} == {"115", "116"}
    finally:
        with Session(engine) as db:
            db.query(Annotation).filter(Annotation.analysis_id == analysis_id).delete(
                synchronize_session=False
            )
            db.query(Resource).filter(
                Resource.id.in_([resource_id, second_resource_id])
            ).delete(synchronize_session=False)
            db.query(Variant).filter(Variant.id == variant_id).delete(
                synchronize_session=False
            )
            db.query(Analysis).filter(Analysis.id == analysis_id).delete(
                synchronize_session=False
            )
            db.query(Case).filter(Case.id == case_id).delete(
                synchronize_session=False
            )
            db.query(User).filter(User.id == user_id).delete(
                synchronize_session=False
            )
            db.query(Organization).filter(Organization.id == organization_id).delete(
                synchronize_session=False
            )
            db.commit()
        engine.dispose()
