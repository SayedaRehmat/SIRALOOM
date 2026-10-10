from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1 import cases, pedigree, phenotypes
from backend.app.auth.principal import Principal


class _Db:
    def get(self, _model, object_id):
        return SimpleNamespace(id=object_id, case_id=object_id)


def _read_only_principal():
    return Principal(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="read_only",
        subject="verified-firebase-subject",
    )


def _assert_forbidden(call):
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == 403


def test_read_only_cannot_create_case():
    _assert_forbidden(
        lambda: cases.create(payload=None, db=None, principal=_read_only_principal())
    )


def test_read_only_cannot_update_case_or_register_specimen(monkeypatch):
    monkeypatch.setattr(cases, "require_case_tenant", lambda _case, _principal: None)
    db = _Db()
    principal = _read_only_principal()

    _assert_forbidden(
        lambda: cases.update_case(case_id=uuid4(), payload=None, db=db, principal=principal)
    )
    _assert_forbidden(
        lambda: cases.create_specimen(
            case_id=uuid4(), payload=None, db=db, principal=principal
        )
    )


def test_read_only_cannot_add_case_phenotype(monkeypatch):
    monkeypatch.setattr(phenotypes, "require_case_tenant", lambda _case, _principal: None)
    _assert_forbidden(
        lambda: phenotypes.add_case_phenotype(
            case_id=uuid4(), body=None, db=_Db(), principal=_read_only_principal()
        )
    )


def test_read_only_cannot_mutate_pedigree_or_inheritance(monkeypatch):
    monkeypatch.setattr(pedigree, "require_case_tenant", lambda _case, _principal: None)
    monkeypatch.setattr(
        pedigree,
        "get_accessible_analysis",
        lambda _analysis_id, _db, _principal: SimpleNamespace(case_id=uuid4()),
    )
    principal = _read_only_principal()
    db = _Db()

    _assert_forbidden(
        lambda: pedigree.add_member(case_id=uuid4(), body=None, db=db, principal=principal)
    )
    _assert_forbidden(
        lambda: pedigree.add_relationship(
            case_id=uuid4(), body=None, db=db, principal=principal
        )
    )
    _assert_forbidden(
        lambda: pedigree.add_segregation(
            analysis_id=uuid4(), variant_id=uuid4(), body=None, db=db, principal=principal
        )
    )
    _assert_forbidden(
        lambda: pedigree.assess_inheritance(
            analysis_id=uuid4(), variant_id=uuid4(), body=None, db=db, principal=principal
        )
    )
