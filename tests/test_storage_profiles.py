from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.storage_profiles import (
    activate_storage_profile,
    get_active_storage_profile,
    register_storage_profile,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, OrganizationStorageProfile, User


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            User.__table__,
            OrganizationStorageProfile.__table__,
        ],
    )
    return engine


def test_storage_profile_activation_is_organization_scoped_and_versioned():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        db.add(org)
        db.flush()

        first = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={"purpose": "clinical-artifacts"},
            created_by=None,
        )
        db.commit()

        active = activate_storage_profile(
            db,
            organization_id=org.id,
            profile_id=first.id,
        )
        db.commit()

        assert active.status == "ACTIVE"
        assert get_active_storage_profile(db, organization_id=org.id).id == first.id

        second = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={"purpose": "clinical-artifacts-v2"},
            created_by=None,
        )
        assert second.version == 2

        db.commit()
        activate_storage_profile(
            db,
            organization_id=org.id,
            profile_id=second.id,
        )
        db.commit()

        db.refresh(first)
        assert first.status == "RETIRED"
        assert get_active_storage_profile(db, organization_id=org.id).id == second.id


def test_storage_profile_has_no_cross_organization_visibility():
    engine = _engine()
    with Session(engine) as db:
        org_a = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        org_b = Organization(id=uuid4(), name="Lab B", external_identifier=None)
        db.add_all([org_a, org_b])
        db.flush()

        profile = register_storage_profile(
            db,
            organization_id=org_a.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={},
            created_by=None,
        )
        db.commit()

        assert get_active_storage_profile(db, organization_id=org_b.id) is None
        assert profile.organization_id == org_a.id
