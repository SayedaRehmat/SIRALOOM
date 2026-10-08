import pytest
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Case, Organization, Report, User


def test_report_version_identity_is_unique():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab")
        user = User(
            id=uuid4(),
            organization_id=org.id,
            display_name="Reviewer",
            role="LAB_DIRECTOR",
            status="ACTIVE",
        )
        case = Case(
            id=uuid4(),
            organization_id=org.id,
            case_identifier="REPORT-IDENTITY",
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=user.id,
        )
        db.add_all([org, user, case])
        db.flush()

        first = Report(
            id=uuid4(),
            case_id=case.id,
            analysis_id=uuid4(),
            report_version=1,
            language="en",
            report_type="CLINICAL_INTERPRETATION",
            status="DRAFT",
            content_json={},
        )
        second = Report(
            id=uuid4(),
            case_id=case.id,
            analysis_id=uuid4(),
            report_version=1,
            language="en",
            report_type="CLINICAL_INTERPRETATION",
            status="DRAFT",
            content_json={},
        )
        db.add(first)
        db.commit()
        db.add(second)

        with pytest.raises(IntegrityError):
            db.commit()
