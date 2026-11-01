import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.artifacts.upload_intents import reserve_upload_intent
from backend.app.infrastructure.db.artifact_upload_intents import ArtifactUploadIntent
from backend.app.infrastructure.db.models import Case, Organization, User


@pytest.mark.integration
def test_postgres_concurrent_upload_intent_reservations_share_one_artifact_identity():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    barrier = threading.Barrier(2)
    reservations = []
    errors = []
    key_sha256 = "b" * 64
    request_fingerprint = "a" * 64

    with Session(engine) as db:
        db.add(Organization(
            id=organization_id,
            name=f"upload-intent-race-{organization_id}",
            external_identifier=str(organization_id),
        ))
        db.flush()
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="Upload Intent Integration",
            role="LAB_DIRECTOR",
            status="ACTIVE",
        ))
        db.flush()
        db.add(Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=str(case_id),
            status="DRAFT",
            clinical_context={},
            language="en",
            created_by=user_id,
        ))
        db.commit()

    def reserve():
        try:
            barrier.wait(timeout=10)
            with Session(engine) as db:
                intent, created = reserve_upload_intent(
                    db,
                    organization_id=organization_id,
                    case_id=case_id,
                    key_sha256=key_sha256,
                    request_fingerprint=request_fingerprint,
                )
                reservations.append((intent.id, intent.artifact_id, created))
        except Exception as exc:  # noqa: BLE001 - surface thread failures in the main test
            errors.append(exc)

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
        assert all(not thread.is_alive() for thread in threads), "Upload-intent reservations did not finish"
        assert not errors
        assert len(reservations) == 2
        assert reservations[0][0] == reservations[1][0]
        assert reservations[0][1] == reservations[1][1]
        assert sum(1 for _intent_id, _artifact_id, created in reservations if created) == 1

        with Session(engine) as db:
            assert db.scalar(
                select(func.count(ArtifactUploadIntent.id)).where(
                    ArtifactUploadIntent.organization_id == organization_id,
                    ArtifactUploadIntent.case_id == case_id,
                    ArtifactUploadIntent.idempotency_key_sha256 == key_sha256,
                )
            ) == 1
    finally:
        with Session(engine) as db:
            db.query(ArtifactUploadIntent).filter(
                ArtifactUploadIntent.organization_id == organization_id,
                ArtifactUploadIntent.case_id == case_id,
            ).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
