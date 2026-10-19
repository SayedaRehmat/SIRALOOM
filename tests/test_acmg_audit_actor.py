from types import SimpleNamespace
from uuid import uuid4

from backend.app.api.v1 import acmg
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import ACMGAssessment, Analysis, Classification, Evidence


def test_manual_acmg_assessment_audit_identifies_authenticated_reviewer(monkeypatch):
    analysis_id, variant_id, evidence_id = uuid4(), uuid4(), uuid4()
    user_id, organization_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4())
    evidence = SimpleNamespace(
        id=evidence_id,
        analysis_id=analysis_id,
        variant_id=variant_id,
    )

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Db:
        def __init__(self):
            self.added = []

        def get(self, model, object_id, **_kwargs):
            assert model is Analysis
            assert object_id == analysis_id
            return analysis

        def refresh(self, *_args, **_kwargs):
            return None

        def scalars(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            return _Result([evidence] if entity is Evidence else [])

        def scalar(self, _statement):
            return None

        def add(self, row):
            self.added.append(row)

        def commit(self):
            return None

    captured = {}

    class _Audit:
        def __init__(self, _db):
            pass

        def record(self, **kwargs):
            captured.update(kwargs)

    db = _Db()
    principal = Principal(
        user_id=user_id,
        organization_id=organization_id,
        role="reviewer",
        subject="verified-reviewer",
    )
    monkeypatch.setattr(acmg, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(acmg, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(acmg, "require_role", lambda *_args: None)
    monkeypatch.setattr(acmg, "AuditService", _Audit)

    payload = acmg.ACMGAssessRequest.model_validate(
        {
            "variant_id": str(variant_id),
            "criteria": [
                {
                    "criterion": "PM2",
                    "strength": "MODERATE",
                    "direction": "PATHOGENIC",
                    "evidence_ids": [str(evidence_id)],
                    "reason": "Reviewed persisted evidence",
                }
            ],
        }
    )

    acmg.assess(analysis_id, variant_id, payload, db, principal)

    assert captured["event_type"] == "ACMG_ASSESSMENT_CREATED"
    assert captured["actor_type"] == "HUMAN"
    assert captured["actor_id"] == str(user_id)
    assert any(isinstance(row, ACMGAssessment) for row in db.added)
    assert any(isinstance(row, Classification) for row in db.added)
