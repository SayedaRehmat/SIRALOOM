from types import SimpleNamespace
from uuid import uuid4

from backend.app.api.v1 import evidence_context
from backend.app.infrastructure.db.models import Analysis, Case


def test_evidence_context_lock_refreshes_analysis_and_rechecks_write_access(monkeypatch):
    analysis_id, case_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    case = SimpleNamespace(id=case_id)
    calls = []

    class FakeDb:
        def get(self, model, identity, *, with_for_update=False):
            if model is Analysis:
                assert identity == analysis_id
                assert with_for_update is True
                calls.append("locked-analysis")
                return analysis
            assert model is Case
            assert identity == case_id
            return case

        def refresh(self, row, *, with_for_update=False):
            assert row is analysis
            assert with_for_update is True
            calls.append("refreshed-analysis")

    def check_permission(_case, _principal, _db, permission):
        assert permission == "write"
        calls.append("permission-rechecked")

    monkeypatch.setattr(evidence_context, "require_case_permission", check_permission)
    principal = SimpleNamespace(user_id=uuid4())

    assert evidence_context._lock_analysis_for_evidence(FakeDb(), analysis_id, principal) is analysis
    assert calls == ["locked-analysis", "refreshed-analysis", "permission-rechecked"]
