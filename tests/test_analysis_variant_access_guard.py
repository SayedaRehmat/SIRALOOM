from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _DB:
    def __init__(self, variant, partition_metadata=()):
        self.variant = variant
        self.partition_metadata = list(partition_metadata)

    def get(self, model, _variant_id):
        from backend.app.infrastructure.db.models import Variant

        assert model is Variant
        return self.variant

    def scalars(self, _statement):
        return _Rows(self.partition_metadata)

    def scalar(self, _statement):
        return None


def test_analysis_variant_guard_accepts_normalization_manifest_membership():
    from backend.app.auth.authorization import get_analysis_variant

    analysis_id, variant_id = uuid4(), uuid4()
    variant = SimpleNamespace(id=variant_id)
    analysis = SimpleNamespace(id=analysis_id)
    db = _DB(variant, [{"variant_ids": [str(uuid4()), str(variant_id)]}])

    assert get_analysis_variant(analysis, variant_id, db) is variant


def test_analysis_variant_guard_rejects_variant_outside_analysis():
    from backend.app.auth.authorization import get_analysis_variant

    analysis = SimpleNamespace(id=uuid4())
    variant_id = uuid4()
    with pytest.raises(HTTPException) as exc:
        get_analysis_variant(analysis, variant_id, _DB(SimpleNamespace(id=variant_id), []))
    assert exc.value.status_code == 404


def test_pedigree_write_denies_variant_from_another_analysis_before_mutation(monkeypatch):
    from backend.app.api.v1 import pedigree

    analysis_id, variant_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4())
    principal = SimpleNamespace(user_id=uuid4(), role="bioinformatician")
    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args: analysis)

    def deny_nonmember_variant(*_args):
        raise HTTPException(status_code=404, detail="Variant is not part of this analysis")

    monkeypatch.setattr(pedigree, "get_analysis_variant", deny_nonmember_variant)

    class ForbiddenDB:
        def add(self, *_args):
            pytest.fail("Segregation observation was written for a non-member variant")

    with pytest.raises(HTTPException) as exc:
        pedigree.add_segregation(
            analysis_id,
            variant_id,
            SimpleNamespace(pedigree_member_id=uuid4()),
            ForbiddenDB(),
            principal,
        )
    assert exc.value.status_code == 404


def test_context_evidence_write_denies_read_only_member_before_database_access(monkeypatch):
    from backend.app.api.v1 import evidence_context

    analysis_id, variant_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4())
    principal = SimpleNamespace(user_id=uuid4(), role="read_only")
    monkeypatch.setattr(evidence_context, "get_accessible_analysis", lambda *_args: analysis)

    class ForbiddenDB:
        def scalar(self, *_args):
            pytest.fail("Read-only member reached evidence lookup")

    with pytest.raises(HTTPException) as exc:
        evidence_context.add_context_evidence(
            analysis_id,
            variant_id,
            evidence_context.ContextEvidenceRequest(
                evidence_type="LITERATURE",
                source_name="test source",
                statement="test statement",
            ),
            ForbiddenDB(),
            principal,
        )
    assert exc.value.status_code == 403
