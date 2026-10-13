from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    READ_ROLES,
    REPORT_FINALIZE_ROLES,
    REVIEW_ROLES,
    require_role,
)
from backend.app.auth.principal import Principal


def principal(role: str) -> Principal:
    return Principal(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        subject="verified-firebase-subject",
    )


ROLE_POLICIES = [
    ("read", READ_ROLES),
    ("case_write", CASE_WRITE_ROLES),
    ("review", REVIEW_ROLES),
    ("report_finalize", REPORT_FINALIZE_ROLES),
]
KNOWN_AND_UNKNOWN_ROLES = sorted(
    set().union(*(roles for _, roles in ROLE_POLICIES)) | {"unknown_role"}
)


@pytest.mark.parametrize(("policy_name", "allowed_roles"), ROLE_POLICIES)
@pytest.mark.parametrize("role", KNOWN_AND_UNKNOWN_ROLES)
def test_role_authorization_matrix_is_exhaustive(policy_name, allowed_roles, role):
    candidate = principal(role)
    if role in allowed_roles:
        assert require_role(candidate, allowed_roles) is candidate
    else:
        with pytest.raises(HTTPException) as error:
            require_role(candidate, allowed_roles)
        assert error.value.status_code == 403, (policy_name, role)


def test_read_only_cannot_write_review_or_finalize():
    for allowed in (CASE_WRITE_ROLES, REVIEW_ROLES, REPORT_FINALIZE_ROLES):
        with pytest.raises(HTTPException) as error:
            require_role(principal("read_only"), allowed)
        assert error.value.status_code == 403


def test_reviewer_cannot_finalize_report():
    with pytest.raises(HTTPException) as error:
        require_role(principal("reviewer"), REPORT_FINALIZE_ROLES)
    assert error.value.status_code == 403


def test_clinical_geneticist_can_finalize_report():
    candidate = principal("clinical_geneticist")
    assert require_role(candidate, REPORT_FINALIZE_ROLES) is candidate
