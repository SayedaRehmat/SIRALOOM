import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import Case, Organization, Report, User


@pytest.mark.integration
def test_postgres_report_version_allocation_is_serialized():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name=f"report-{organization_id}", external_identifier=str(organization_id)))
        db.commit()
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="Report Integration",
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

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def create_one():
        try:
            with Session(engine) as db:
                barrier.wait(timeout=10)
                case = db.get(Case, case_id, with_for_update=True)
                last = db.scalar(
                    select(Report.report_version)
                    .where(
                        Report.case_id == case_id,
                        Report.report_type == "CLINICAL_INTERPRETATION",
                    )
                    .order_by(Report.report_version.desc())
                    .limit(1)
                ) or 0
                version = int(last) + 1
                db.add(Report(
                    id=uuid4(),
                    case_id=case.id,
                    analysis_id=uuid4(),
                    report_version=version,
                    language="en",
                    report_type="CLINICAL_INTERPRETATION",
                    status="DRAFT",
                    content_json={"report_version": version},
                ))
                db.commit()
                results.append(version)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=create_one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
        assert not errors
        assert sorted(results) == [1, 2]
        with Session(engine) as db:
            versions = db.scalars(
                select(Report.report_version)
                .where(
                    Report.case_id == case_id,
                    Report.report_type == "CLINICAL_INTERPRETATION",
                )
                .order_by(Report.report_version)
            ).all()
            assert versions == [1, 2]
    finally:
        with Session(engine) as db:
            db.query(Report).filter(Report.case_id == case_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
