from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.api.v1 import reanalysis as reanalysis_api


def test_change_event_api_rejects_resource_kind_trigger_mismatch_before_detection(monkeypatch):
    called = False

    def detect_change(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(reanalysis_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reanalysis_api, "detect_change", detect_change)

    with pytest.raises(reanalysis_api.HTTPException) as exc_info:
        reanalysis_api.register_change(
            {
                "trigger_type": "POPULATION_UPDATE",
                "resource_kind": "ANNOTATION",
                "resource_name": "annotation release",
            },
            db=object(),
            principal=type("Principal", (), {
                "organization_id": uuid4(), "user_id": uuid4(), "role": "lab_director",
            })(),
        )

    assert exc_info.value.status_code == 422
    assert called is False


def test_change_event_api_accepts_governed_resource_trigger_pair(monkeypatch):
    organization_id = uuid4()
    user_id = uuid4()
    received = {}
    audit_records = []

    class _Audit:
        def record(self, **kwargs):
            audit_records.append(kwargs)

    class _Db:
        commits = 0
        rollbacks = 0

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    def detect_change(_db, **kwargs):
        received.update(kwargs)
        return [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(reanalysis_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reanalysis_api, "detect_change", detect_change)
    monkeypatch.setattr(reanalysis_api, "AuditService", lambda _db: _Audit())
    db = _Db()

    result = reanalysis_api.register_change(
        {
            "trigger_type": "POPULATION_UPDATE",
            "resource_kind": "POPULATION",
            "resource_name": "gnomAD",
            "new_version": "v4",
        },
        db=db,
        principal=type("Principal", (), {
            "organization_id": organization_id, "user_id": user_id, "role": "bioinformatician",
        })(),
    )

    assert result == {"change_registered": True, "candidates_created": 2}
    assert "candidate_ids" not in result
    assert db.commits == 1
    assert audit_records[0]["event_type"] == "REANALYSIS_RESOURCE_CHANGE_REGISTERED"
    assert audit_records[0]["actor_type"] == "HUMAN"
    assert audit_records[0]["actor_id"] == str(user_id)
    assert audit_records[0]["after_state"]["candidate_count"] == 2
    assert received["organization_id"] == organization_id
    assert received["trigger_type"] == "POPULATION_UPDATE"
    assert received["resource_kind"] == "POPULATION"
    assert received["commit"] is False
    assert db.rollbacks == 0


def test_resource_change_registration_rejects_case_writer_role(monkeypatch):
    called = False

    def detect_change(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(reanalysis_api, "detect_change", detect_change)
    principal = type("Principal", (), {
        "organization_id": uuid4(), "user_id": uuid4(), "role": "lab_scientist",
    })()

    with pytest.raises(reanalysis_api.HTTPException) as exc:
        reanalysis_api.register_change(
            {
                "trigger_type": "POPULATION_UPDATE",
                "resource_kind": "POPULATION",
                "resource_name": "gnomAD",
            },
            db=object(),
            principal=principal,
        )

    assert exc.value.status_code == 403
    assert called is False


def test_resource_id_must_match_change_kind_and_name(monkeypatch):
    organization_id = uuid4()
    resource_id = uuid4()
    called = False

    class _Db:
        def get(self, _model, requested_id):
            assert requested_id == resource_id
            return SimpleNamespace(
                organization_id=organization_id,
                resource_type="ANNOTATION",
                name="VEP",
            )

    def detect_change(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(reanalysis_api, "detect_change", detect_change)
    monkeypatch.setattr(reanalysis_api, "require_role", lambda *_args: None)

    with pytest.raises(reanalysis_api.HTTPException) as exc:
        reanalysis_api.register_change(
            {
                "trigger_type": "POPULATION_UPDATE",
                "resource_kind": "POPULATION",
                "resource_name": "gnomAD",
                "resource_id": str(resource_id),
            },
            db=_Db(),
            principal=type("Principal", (), {
                "organization_id": organization_id, "user_id": uuid4(), "role": "lab_director",
            })(),
        )

    assert exc.value.status_code == 422
    assert called is False


def test_resource_change_audit_failure_rolls_back_registration(monkeypatch):
    organization_id = uuid4()
    db = type("Db", (), {
        "commits": 0,
        "rollbacks": 0,
        "commit": lambda self: setattr(self, "commits", self.commits + 1),
        "rollback": lambda self: setattr(self, "rollbacks", self.rollbacks + 1),
    })()
    received = {}

    def detect_change(_db, **kwargs):
        received.update(kwargs)
        return []

    class _BrokenAudit:
        def record(self, **_kwargs):
            raise RuntimeError("audit persistence failed")

    monkeypatch.setattr(reanalysis_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reanalysis_api, "detect_change", detect_change)
    monkeypatch.setattr(reanalysis_api, "AuditService", lambda _db: _BrokenAudit())

    with pytest.raises(RuntimeError, match="audit persistence failed"):
        reanalysis_api.register_change(
            {
                "trigger_type": "POPULATION_UPDATE",
                "resource_kind": "POPULATION",
                "resource_name": "gnomAD",
                "new_version": "v4",
            },
            db=db,
            principal=type("Principal", (), {
                "organization_id": organization_id, "user_id": uuid4(), "role": "bioinformatician",
            })(),
        )

    assert received["commit"] is False
    assert db.commits == 0
    assert db.rollbacks == 1
