from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
import os
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.domain.enums import CaseStatus, UserRole
from backend.app.infrastructure.db.models import Case, CaseAccessGrant, Organization, OrganizationMembership, User
from backend.app.infrastructure.audit.service import AuditService

def _development_identity_id(environment_name: str, identity_name: str):
    configured = os.environ.get(environment_name, "").strip()
    if configured:
        try:
            return UUID(configured)
        except ValueError as exc:
            raise ValueError(f"{environment_name} must be a UUID") from exc
    return uuid5(NAMESPACE_URL, f"siraloom:development:{identity_name}:v1")


# Stable across API/worker processes and restarts. A development deployment can
# explicitly bind an existing development tenant without changing production IDs.
DEV_ORG_ID = _development_identity_id("SIRALOOM_DEV_ORGANIZATION_ID", "organization")
DEV_USER_ID = _development_identity_id("SIRALOOM_DEV_USER_ID", "analyst")
DEV_REVIEWER_ID = _development_identity_id("SIRALOOM_DEV_REVIEWER_ID", "reviewer")

def ensure_dev_identity(db: Session):
    org = db.get(Organization, DEV_ORG_ID)
    if not org:
        org = Organization(id=DEV_ORG_ID, name="SIRALOOM Development Laboratory")
        db.add(org)
        db.flush()
    user = db.get(User, DEV_USER_ID)
    if not user:
        user = User(id=DEV_USER_ID, organization_id=org.id, display_name="Development Analyst", email="dev@siraloom.local", role=UserRole.ANALYST, status="ACTIVE")
        db.add(user)
        db.flush()
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if membership is None:
        db.add(
            OrganizationMembership(
                id=uuid4(),
                organization_id=org.id,
                user_id=user.id,
                role="bioinformatician",
                status="ACTIVE",
            )
        )
    db.commit()
    return org, user

def create_case(db: Session, *, case_identifier: str, language: str, clinical_context: dict):
    org, user = ensure_dev_identity(db)
    existing = db.scalar(select(Case).where(Case.organization_id == org.id, Case.case_identifier == case_identifier))
    if existing:
        return existing, user, False
    case = Case(id=uuid4(), organization_id=org.id, case_identifier=case_identifier, status=CaseStatus.DRAFT, clinical_context=clinical_context, language=language, created_by=user.id)
    db.add(case)
    db.add(CaseAccessGrant(
        id=uuid4(), case_id=case.id, user_id=user.id,
        can_read=True, can_write=True, can_review=True, granted_by=user.id,
    ))
    audit = AuditService(db)
    audit.record(event_type="CASE_CREATED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(user.id), subject_type="CASE", subject_id=str(case.id), operation="CREATE", after_state={"case_identifier": case_identifier})
    db.commit()
    return case, user, True


def ensure_dev_reviewer_identity(db: Session):
    org, _ = ensure_dev_identity(db)
    user = db.get(User, DEV_REVIEWER_ID)
    if not user:
        user = User(
            id=DEV_REVIEWER_ID,
            organization_id=org.id,
            display_name="Development Reviewer",
            email="reviewer@siraloom.local",
            role=UserRole.REVIEWER,
            status="ACTIVE",
        )
        db.add(user)
        db.commit()
    return org, user
