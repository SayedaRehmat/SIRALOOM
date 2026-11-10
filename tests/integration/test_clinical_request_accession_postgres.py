"""PostgreSQL concurrency and immutable-history tests for accession decisions.

These tests exercise the real route functions with authentication dependencies
isolated, while retaining PostgreSQL row-locking, transaction and audit behavior.
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.api.v1 import clinical_requests as routes
from backend.app.api.v1.clinical_requests import DecisionInput, RevisionInput
from backend.app.infrastructure.db.clinical_requests import (
    AccessionDecision,
    ClinicalRequest,
    ClinicalRequestRevision,
    ReferrerVerification,
)
from backend.app.infrastructure.db.models import Case, Organization, User


def _postgres_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")
    return create_engine(url, pool_pre_ping=True)


def _seed_request(engine, suffix):
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    request_id, revision_id, verification_id = uuid4(), uuid4(), uuid4()
    fingerprint = f"test-{uuid4().hex}"
    with Session(engine) as db:
        db.add(Organization(
            id=organization_id,
            name=f"accession-{suffix}-{organization_id}",
            external_identifier=str(organization_id),
        ))
        db.commit()
    with Session(engine) as db:
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="Accession integration test",
            role="LAB_DIRECTOR",
            status="ACTIVE",
        ))
        db.commit()
    with Session(engine) as db:
        case = Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=f"ACC-{suffix}-{case_id}",
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=user_id,
        )
        db.add(case)
        db.commit()
    payload = {
        "requested_examination": "Germline SNV and small-indel interpretation",
        "referral_indication": "Integration-test indication",
        "clinical_question": "Test accession concurrency",
        "referrer_name": "Dr Integration",
        "referrer_role": "Clinical geneticist",
        "referrer_organization": "Test referral service",
        "referrer_identifier": f"REF-{suffix}",
        "referrer_contact": "referrer@example.test",
        "referral_channel": "SECURE_PORTAL",
        "source_evidence_reference": f"REF-EVIDENCE-{suffix}",
    }
    with Session(engine) as db:
        request = ClinicalRequest(
            id=request_id,
            case_id=case_id,
            organization_id=organization_id,
            request_identifier=f"REQ-{suffix}-{request_id}",
            status="SUBMITTED",
            current_revision_id=revision_id,
            created_by=user_id,
        )
        revision = ClinicalRequestRevision(
            id=revision_id,
            request_id=request_id,
            version=1,
            schema_version=1,
            fingerprint=fingerprint,
            payload=payload,
            created_by=user_id,
        )
        verification = ReferrerVerification(
            id=verification_id,
            request_id=request_id,
            revision_id=revision_id,
            status="VERIFIED",
            method="Controlled callback",
            evidence_reference=f"VERIFY-{suffix}",
            outcome_note="Identity confirmed for integration test",
            verified_by=user_id,
        )
        db.add_all([request, revision, verification])
        db.commit()
    principal = SimpleNamespace(
        user_id=user_id,
        organization_id=organization_id,
        role="lab_director",
    )
    return {
        "organization_id": organization_id,
        "user_id": user_id,
        "case_id": case_id,
        "request_id": request_id,
        "revision_id": revision_id,
        "verification_id": verification_id,
        "principal": principal,
    }


@pytest.mark.integration
def test_postgres_concurrent_acceptance_records_only_one_decision(monkeypatch):
    engine = _postgres_engine()
    seeded = _seed_request(engine, "CONCURRENT")
    request_id = seeded["request_id"]
    principal = seeded["principal"]
    barrier = threading.Barrier(2)

    def request_lookup(db, requested_id, _principal, _permission="read"):
        row = db.get(ClinicalRequest, requested_id)
        case = db.get(Case, row.case_id)
        return row, case

    monkeypatch.setattr(routes, "_request_or_404", request_lookup)
    monkeypatch.setattr(routes, "_require_capability", lambda *_args, **_kwargs: None)

    def decide():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                result = routes.decide_accession(
                    request_id,
                    DecisionInput(
                        decision="ACCEPT",
                        reason="Concurrent PostgreSQL acceptance test",
                        verification_id=seeded["verification_id"],
                    ),
                    db=db,
                    principal=principal,
                )
                return ("accepted", result)
            except HTTPException as exc:
                db.rollback()
                return ("rejected", exc.status_code)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: decide(), range(2)))
        assert sorted(outcome[0] for outcome in outcomes) == ["accepted", "rejected"]
        rejected = next(outcome for outcome in outcomes if outcome[0] == "rejected")
        assert rejected[1] == 409
        with Session(engine) as db:
            request = db.get(ClinicalRequest, request_id)
            decisions = list(db.scalars(
                select(AccessionDecision).where(
                    AccessionDecision.request_id == request_id,
                )
            ))
            assert request.status == "ACCEPTED"
            assert len(decisions) == 1
            assert decisions[0].decision == "ACCEPT"
            assert decisions[0].revision_id == seeded["revision_id"]
            assert decisions[0].verification_id == seeded["verification_id"]
    finally:
        engine.dispose()


@pytest.mark.integration
def test_postgres_revision_after_acceptance_preserves_historical_decision(monkeypatch):
    engine = _postgres_engine()
    seeded = _seed_request(engine, "HISTORY")
    request_id = seeded["request_id"]
    principal = seeded["principal"]
    monkeypatch.setattr(
        routes,
        "_request_or_404",
        lambda db, requested_id, _principal, _permission="read": (
            db.get(ClinicalRequest, requested_id),
            db.get(Case, seeded["case_id"]),
        ),
    )
    monkeypatch.setattr(routes, "_require_capability", lambda *_args, **_kwargs: None)

    try:
        with Session(engine) as db:
            routes.decide_accession(
                request_id,
                DecisionInput(
                    decision="ACCEPT",
                    reason="Initial acceptance for historical preservation test",
                    verification_id=seeded["verification_id"],
                ),
                db=db,
                principal=principal,
            )
        with Session(engine) as db:
            request = db.get(ClinicalRequest, request_id)
            request.status = "ACCEPTED"
            db.commit()
        with Session(engine) as db:
            result = routes.create_request_revision(
                request_id,
                RevisionInput(
                    requested_examination="Updated germline SNV and small-indel interpretation",
                    referral_indication="Updated integration-test indication",
                    clinical_question="Updated question following new clinical information",
                    referrer_name="Dr Integration",
                    referrer_role="Clinical geneticist",
                    referrer_organization="Test referral service",
                    referrer_identifier="REF-HISTORY-UPDATED",
                    referrer_contact="referrer@example.test",
                    referral_channel="SECURE_PORTAL",
                    source_evidence_reference="REF-EVIDENCE-HISTORY-UPDATED",
                ),
                db=db,
                principal=principal,
            )
            new_revision_id = result["revision_id"]
        with Session(engine) as db:
            request = db.get(ClinicalRequest, request_id)
            decisions = list(db.scalars(
                select(AccessionDecision).where(
                    AccessionDecision.request_id == request_id,
                )
            ))
            revisions = list(db.scalars(
                select(ClinicalRequestRevision).where(
                    ClinicalRequestRevision.request_id == request_id,
                )
            ))
            assert request.status == "REASSESSMENT_REQUIRED"
            assert str(request.current_revision_id) == new_revision_id
            assert len(revisions) == 2
            assert len(decisions) == 1
            assert decisions[0].revision_id == seeded["revision_id"]
            assert decisions[0].decision == "ACCEPT"
    finally:
        engine.dispose()
