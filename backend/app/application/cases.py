from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.domain.enums import CaseStatus, UserRole
from backend.app.infrastructure.db.models import Case, Organization, User
from backend.app.infrastructure.audit.service import AuditService

DEV_ORG_ID = uuid4()
DEV_USER_ID = uuid4()
DEV_REVIEWER_ID = uuid4()

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
        db.commit()
    return org, user

def create_case(db: Session, *, case_identifier: str, language: str, clinical_context: dict):
    org, user = ensure_dev_identity(db)
    existing = db.scalar(select(Case).where(Case.organization_id == org.id, Case.case_identifier == case_identifier))
    if existing:
        return existing, user, False
    case = Case(id=uuid4(), organization_id=org.id, case_identifier=case_identifier, status=CaseStatus.DRAFT, clinical_context=clinical_context, language=language, created_by=user.id)
    db.add(case)
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
