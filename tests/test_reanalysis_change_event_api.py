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
            principal=type("Principal", (), {"organization_id": uuid4()})(),
        )

    assert exc_info.value.status_code == 422
    assert called is False


def test_change_event_api_accepts_governed_resource_trigger_pair(monkeypatch):
    organization_id = uuid4()
    received = {}

    def detect_change(_db, **kwargs):
        received.update(kwargs)
        return []

    monkeypatch.setattr(reanalysis_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reanalysis_api, "detect_change", detect_change)

    result = reanalysis_api.register_change(
        {
            "trigger_type": "POPULATION_UPDATE",
            "resource_kind": "POPULATION",
            "resource_name": "gnomAD",
            "new_version": "v4",
        },
        db=object(),
        principal=type("Principal", (), {"organization_id": organization_id})(),
    )

    assert result == {"candidates_created": 0, "candidate_ids": []}
    assert received["organization_id"] == organization_id
    assert received["trigger_type"] == "POPULATION_UPDATE"
    assert received["resource_kind"] == "POPULATION"
