from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1 import acmg


class _DB:
    def __init__(self, analysis, variant):
        self.analysis = analysis
        self.variant = variant
        self.added = []
        self.commits = 0

    def get(self, model, _identifier, **_kwargs):
        if model is acmg.Analysis:
            return self.analysis
        if model is acmg.Variant:
            return self.variant
        return None

    def refresh(self, *_args, **_kwargs):
        return None

    def scalar(self, _statement):
        # The analysis-specific Annotation membership query deliberately finds
        # no row. This is the security/integrity boundary under test.
        return None

    def scalars(self, _statement):
        raise AssertionError("Evidence queries must not run for an out-of-scope variant")

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1


def test_acmg_assess_rejects_variant_not_present_in_analysis(monkeypatch):
    analysis_id = uuid4()
    variant_id = uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4())
    variant = SimpleNamespace(id=variant_id)
    db = _DB(analysis, variant)
    principal = SimpleNamespace()

    monkeypatch.setattr(acmg, "get_accessible_analysis", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(acmg, "require_role", lambda *_args, **_kwargs: principal)

    payload = acmg.ACMGAssessRequest(
        variant_id=variant_id,
        criteria=[],
    )

    with pytest.raises(HTTPException) as exc:
        acmg.assess(analysis_id, variant_id, payload, db, principal)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Variant is not part of this analysis"
    assert db.added == []
    assert db.commits == 0
