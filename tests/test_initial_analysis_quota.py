from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.application.analysis import create_analysis
from backend.app.application.entitlements import reserve_analysis_quota
from backend.app.domain.enums import AnalysisStatus, EntitlementPlan, EntitlementStatus
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    Case,
    Organization,
    OrganizationEntitlement,
    User,
)


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            User.__table__,
            Case.__table__,
            Artifact.__table__,
            OrganizationEntitlement.__table__,
            Analysis.__table__,
        ],
    )
    return engine


def _seed(db: Session, *, max_analyses: int = 1):
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    artifact_id = uuid4()

    db.add(
        Organization(
            id=organization_id,
            name="Quota Test Laboratory",
            external_identifier=None,
        )
    )
    db.add(
        User(
            id=user_id,
            organization_id=organization_id,
            external_subject=None,
            email="quota@test.local",
            display_name="Quota Test",
            role="ANALYST",
            status="ACTIVE",
        )
    )
    db.add(
        Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier="QUOTA-001",
            status="ACTIVE",
            clinical_context={},
            language="en",
            created_by=user_id,
        )
    )
    db.add(
        Artifact(
            id=artifact_id,
            analysis_id=None,
            case_id=case_id,
            artifact_type="VCF",
            filename="input.vcf",
            media_type="text/vcf",
            size_bytes=10,
            sha256="a" * 64,
            storage_uri="memory://input.vcf",
            genome_build="GRCh38",
            specimen_id=None,
            paired_artifact_id=None,
            validation_status="VALID",
            metadata_json={},
        )
    )
    db.add(
        OrganizationEntitlement(
            id=uuid4(),
            organization_id=organization_id,
            plan=EntitlementPlan.TRIAL,
            status=EntitlementStatus.ACTIVE,
            max_analyses=max_analyses,
            analyses_used=0,
            max_vcf_size_bytes=50 * 1024 * 1024,
        )
    )
    db.commit()
    return organization_id, case_id, artifact_id, user_id


def _create(db: Session, case_id, artifact_id, user_id):
    return create_analysis(
        db,
        case_id=case_id,
        input_artifact_id=artifact_id,
        assay_id=None,
        analysis_type="VARIANT_INTERPRETATION",
        workflow_id="siraloom.variant",
        workflow_version="1.0",
        reference_build="GRCh38",
        configuration={},
        created_by=user_id,
        commit=False,
    )


def test_quota_reservation_locks_authoritative_entitlement_row():
    organization_id = uuid4()
    entitlement = type(
        "Entitlement",
        (),
        {
            "organization_id": organization_id,
            "plan": EntitlementPlan.TRIAL,
            "status": EntitlementStatus.ACTIVE,
            "max_analyses": 2,
            "analyses_used": 0,
            "trial_expires_at": None,
        },
    )()

    class FakeDB:
        def __init__(self):
            self.statement = None
            self.commits = 0
            self.added = None

        def scalar(self, statement):
            self.statement = statement
            return entitlement

        def add(self, row):
            self.added = row

        def commit(self):
            self.commits += 1

    db = FakeDB()
    reserve_analysis_quota(db, organization_id)

    assert getattr(db.statement, "_for_update_arg", None) is not None
    assert entitlement.analyses_used == 1
    assert db.added is entitlement
    assert db.commits == 1


def test_exhausted_quota_is_rechecked_under_reservation_lock():
    organization_id = uuid4()
    entitlement = type(
        "Entitlement",
        (),
        {
            "organization_id": organization_id,
            "plan": EntitlementPlan.TRIAL,
            "status": EntitlementStatus.ACTIVE,
            "max_analyses": 1,
            "analyses_used": 1,
            "trial_expires_at": None,
        },
    )()

    class FakeDB:
        def scalar(self, statement):
            assert getattr(statement, "_for_update_arg", None) is not None
            return entitlement

        def add(self, _row):
            raise AssertionError("exhausted quota must not mutate the entitlement")

        def commit(self):
            raise AssertionError("exhausted quota must not commit")

    with pytest.raises(HTTPException) as exc_info:
        reserve_analysis_quota(FakeDB(), organization_id)

    assert exc_info.value.status_code == 402
    assert "used all 1 included analyses" in str(exc_info.value.detail)


def test_analysis_and_first_quota_reservation_commit_together():
    engine = _database()

    with Session(engine) as db:
        organization_id, case_id, artifact_id, user_id = _seed(db)

        analysis = _create(db, case_id, artifact_id, user_id)
        reserve_analysis_quota(db, organization_id, commit=False)
        db.commit()

        assert db.get(Analysis, analysis.id) is not None
        entitlement = db.scalar(
            select(OrganizationEntitlement).where(
                OrganizationEntitlement.organization_id == organization_id
            )
        )
        assert entitlement.analyses_used == 1


def test_failed_quota_reservation_rolls_back_new_analysis():
    engine = _database()

    with Session(engine) as db:
        organization_id, case_id, artifact_id, user_id = _seed(db)

        first = _create(db, case_id, artifact_id, user_id)
        reserve_analysis_quota(db, organization_id, commit=False)
        db.commit()

        second = _create(db, case_id, artifact_id, user_id)

        with pytest.raises(HTTPException) as exc_info:
            reserve_analysis_quota(db, organization_id, commit=False)

        assert exc_info.value.status_code == 402
        db.rollback()

        assert db.get(Analysis, first.id) is not None
        assert db.get(Analysis, second.id) is None
        entitlement = db.scalar(
            select(OrganizationEntitlement).where(
                OrganizationEntitlement.organization_id == organization_id
            )
        )
        assert entitlement.analyses_used == 1
        assert db.scalar(select(func.count(Analysis.id))) == 1


def test_unrestricted_plan_does_not_consume_usage():
    organization_id = uuid4()
    entitlement = type(
        "Entitlement",
        (),
        {
            "organization_id": organization_id,
            "plan": EntitlementPlan.PAID,
            "status": EntitlementStatus.ACTIVE,
            "max_analyses": 1,
            "analyses_used": 0,
            "trial_expires_at": None,
        },
    )()

    class FakeDB:
        def scalar(self, _statement):
            return entitlement

        def add(self, _row):
            raise AssertionError("unrestricted plans must not be mutated")

        def commit(self):
            raise AssertionError("unrestricted plans must not commit")

    reserve_analysis_quota(FakeDB(), organization_id)
