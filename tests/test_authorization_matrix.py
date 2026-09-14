from uuid import uuid4
import pytest
from fastapi import HTTPException
from backend.app.auth.authorization import CASE_WRITE_ROLES, REPORT_FINALIZE_ROLES, REVIEW_ROLES, require_role
from backend.app.auth.principal import Principal

def principal(role: str): return Principal(user_id=uuid4(), organization_id=uuid4(), role=role, subject="verified-firebase-subject")

def test_read_only_cannot_write_review_or_finalize():
    for allowed in (CASE_WRITE_ROLES, REVIEW_ROLES, REPORT_FINALIZE_ROLES):
        with pytest.raises(HTTPException) as error: require_role(principal("read_only"), allowed)
        assert error.value.status_code == 403

def test_reviewer_cannot_finalize_report():
    with pytest.raises(HTTPException): require_role(principal("reviewer"), REPORT_FINALIZE_ROLES)

def test_clinical_geneticist_can_finalize_report():
    assert require_role(principal("clinical_geneticist"), REPORT_FINALIZE_ROLES).role == "clinical_geneticist"
