from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1.reanalysis import notifications
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Case,
    CaseAccessGrant,
    Notification,
    Organization,
    OrganizationMembership,
    User,
)


def test_inaccessible_notifications_do_not_push_visible_items_out_of_limit(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'notification-inbox.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id = uuid4(), uuid4()
    visible_case_id, revoked_case_id = uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Inbox Lab"))
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject="inbox-user",
            email="reader@example.test",
            display_name="Reader",
            role="read_only",
            status="ACTIVE",
        ))
        db.add(OrganizationMembership(
            id=uuid4(), organization_id=organization_id, user_id=user_id,
            role="read_only", status="ACTIVE",
        ))
        db.add_all([
            Case(
                id=visible_case_id, organization_id=organization_id,
                case_identifier="VISIBLE", status="ACTIVE", clinical_context={},
                language="en", created_by=user_id,
            ),
            Case(
                id=revoked_case_id, organization_id=organization_id,
                case_identifier="REVOKED", status="ACTIVE", clinical_context={},
                language="en", created_by=user_id,
            ),
            CaseAccessGrant(
                id=uuid4(), case_id=visible_case_id, user_id=user_id,
                can_read=True, can_write=False, can_review=False,
            ),
        ])
        now = datetime.now(timezone.utc)
        db.add(Notification(
            id=uuid4(), organization_id=organization_id, user_id=user_id,
            notification_type="REANALYSIS_CANDIDATE", status="UNREAD",
            title="Assigned case", body="Visible", case_id=visible_case_id,
            metadata_json={}, created_at=now - timedelta(seconds=120),
        ))
        db.add_all([
            Notification(
                id=uuid4(), organization_id=organization_id, user_id=user_id,
                notification_type="REANALYSIS_CANDIDATE", status="UNREAD",
                title=f"Revoked case {index}", body="Hidden", case_id=revoked_case_id,
                metadata_json={}, created_at=now - timedelta(seconds=index),
            )
            for index in range(1, 106)
        ])
        db.commit()

        result = notifications(
            db,
            Principal(
                user_id=user_id, organization_id=organization_id, role="read_only",
                subject="inbox-user", email="reader@example.test",
            ),
        )

        assert [item["title"] for item in result] == ["Assigned case"]
    engine.dispose()
