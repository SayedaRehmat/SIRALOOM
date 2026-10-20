import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.api.v1 import clinical_followup
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    Case,
    ConfirmationRecord,
    Organization,
    OrganizationMembership,
    SecondaryFindingDecision,
    User,
    Variant,
)


@pytest.mark.integration
@pytest.mark.parametrize("record_type", ["confirmation", "secondary_finding"])
def test_postgres_concurrent_governance_versions_form_a_serial_lineage(
    record_type, monkeypatch
):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id, analysis_id, variant_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    principal = Principal(
        user_id=user_id,
        organization_id=organization_id,
        role="lab_director",
        subject="verified-test-subject",
    )

    with Session(engine) as db:
        db.add(Organization(
            id=organization_id,
            name=f"governance-version-{organization_id}",
            external_identifier=str(organization_id),
        ))
        db.commit()
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="Governance Version Integration",
            role="lab_director",
            status="ACTIVE",
        ))
        db.add(OrganizationMembership(
            id=uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            role="lab_director",
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
            analysis_type="GERMLINE",
            workflow_id="integration",
            workflow_version="1",
            status="REQUIRES_REVIEW",
            reference_build="GRCh38",
            configuration={},
            created_by=user_id,
            analysis_version=1,
        ))
        db.commit()
        db.add(Variant(
            id=variant_id,
            genome_build="GRCh38",
            chromosome="1",
            position=123,
            reference="A",
            alternate="G",
            normalization_status="NORMALIZED",
            canonical_key=f"GRCh38:1:123:A:G:{variant_id}",
            identifiers={},
        ))
        db.commit()

    # This integration test targets analysis locking/version allocation. A real
    # membership and tenant lookup still runs through get_accessible_analysis.
    monkeypatch.setattr(clinical_followup, "_variant_access", lambda *_args: None)
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def record_one():
        try:
            with Session(engine) as db:
                barrier.wait(timeout=10)
                if record_type == "confirmation":
                    result = clinical_followup.record_confirmation(
                        analysis_id,
                        variant_id,
                        clinical_followup.ConfirmationInput(required=True, status="PENDING"),
                        db,
                        principal,
                    )
                else:
                    result = clinical_followup.record_secondary_finding(
                        analysis_id,
                        variant_id,
                        clinical_followup.SecondaryFindingInput(
                            policy_name="LAB_POLICY",
                            policy_version="1",
                            status="DRAFT",
                        ),
                        db,
                        principal,
                    )
                results.append(result)
        except Exception as exc:  # noqa: BLE001 - surface thread failures to the test
            errors.append(exc)

    threads = [threading.Thread(target=record_one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
        assert all(not thread.is_alive() for thread in threads), "governance writes did not finish"
        assert not errors
        assert len(results) == 2
        with Session(engine) as db:
            if record_type == "confirmation":
                rows = db.scalars(
                    select(ConfirmationRecord)
                    .where(
                        ConfirmationRecord.analysis_id == analysis_id,
                        ConfirmationRecord.variant_id == variant_id,
                    )
                    .order_by(ConfirmationRecord.version)
                ).all()
                assert [row.version for row in rows] == [1, 2]
                assert rows[1].supersedes_record_id == rows[0].id
            else:
                rows = db.scalars(
                    select(SecondaryFindingDecision)
                    .where(
                        SecondaryFindingDecision.analysis_id == analysis_id,
                        SecondaryFindingDecision.variant_id == variant_id,
                    )
                    .order_by(SecondaryFindingDecision.version)
                ).all()
                assert [row.version for row in rows] == [1, 2]
                assert rows[1].supersedes_decision_id == rows[0].id
            events = db.scalars(
                select(AuditEvent).where(AuditEvent.analysis_id == analysis_id)
            ).all()
            assert len(events) == 2
    finally:
        with Session(engine) as db:
            db.query(AuditEvent).filter(AuditEvent.case_id == case_id).delete()
            db.query(ConfirmationRecord).filter(
                ConfirmationRecord.analysis_id == analysis_id
            ).delete()
            db.query(SecondaryFindingDecision).filter(
                SecondaryFindingDecision.analysis_id == analysis_id
            ).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Variant).filter(Variant.id == variant_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(OrganizationMembership).filter(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            ).delete(synchronize_session=False)
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
