import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from backend.app.review.service import approve_classification
from backend.app.infrastructure.db.models import (
    Analysis, AuditEvent, Case, Classification, Organization, ReviewAction, User, Variant,
)


@pytest.mark.integration
def test_postgres_concurrent_classification_approval_allocates_one_version():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id, analysis_id, variant_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name=f"approval-race-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

        with Session(engine) as db:
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@example.test",
                display_name="Review Integration", role="reviewer", status="ACTIVE",
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=str(case_id), status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1",
                position=555, reference="T", alternate="C",
                normalization_status="NORMALIZED",
                canonical_key=f"GRCh38:1:555:T:C:{variant_id}", identifiers={},
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="integration",
                status="REQUIRES_REVIEW", queue_task_id=None,
                reference_build="GRCh38", configuration={},
                started_at=None, completed_at=None, created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Classification(
                id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                framework_name="ACMG/AMP", framework_version="2015",
                specification_provider=None, specification_id=None,
                specification_version=None, result="VUS", criterion_ids=[],
                metadata_json={"fixture": "approval-race"},
                state="PROPOSED", review_status="IN_REVIEW", version=1,
                review_version=1, reviewed_by=user_id,
            ))
            db.commit()

        barrier = threading.Barrier(2)
        outcomes = []
        errors = []

        def approve():
            try:
                with Session(engine) as db:
                    reviewer = db.get(User, user_id)
                    barrier.wait(timeout=10)
                    classification = approve_classification(
                        db, analysis_id=analysis_id, variant_id=variant_id,
                        reviewer=reviewer, expected_version=1,
                        reason="Concurrent approval regression test.",
                    )
                    db.commit()
                    outcomes.append((str(classification.id), classification.version, classification.review_status))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=approve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert not errors
        assert len(outcomes) == 2
        assert outcomes[0] == outcomes[1]
        assert outcomes[0][1:] == (2, "APPROVED")

        with Session(engine) as db:
            versions = db.scalars(
                select(Classification.version).where(
                    Classification.analysis_id == analysis_id,
                    Classification.variant_id == variant_id,
                ).order_by(Classification.version)
            ).all()
            assert versions == [1, 2]
            assert db.scalar(select(func.count(ReviewAction.id)).where(
                ReviewAction.analysis_id == analysis_id,
                ReviewAction.action_type == "CLASSIFICATION_APPROVED",
            )) == 1
            assert db.scalar(select(func.count(AuditEvent.id)).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "CLASSIFICATION_APPROVED",
            )) == 1
    finally:
        with Session(engine) as db:
            db.query(ReviewAction).filter(ReviewAction.analysis_id == analysis_id).delete()
            db.query(AuditEvent).filter(AuditEvent.analysis_id == analysis_id).delete()
            db.query(Classification).filter(Classification.analysis_id == analysis_id).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Variant).filter(Variant.id == variant_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
