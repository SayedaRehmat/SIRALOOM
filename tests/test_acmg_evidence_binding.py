from types import SimpleNamespace
from uuid import uuid4

from backend.app.acmg.assessment_service import _resolve_evidence_ids


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, _statement):
        return FakeResult(self.rows)


def test_population_observation_id_resolves_to_persisted_evidence_id():
    analysis_id = uuid4()
    variant_id = uuid4()
    observation_id = uuid4()
    evidence_id = uuid4()

    db = FakeDB([
        SimpleNamespace(
            id=evidence_id,
            analysis_id=analysis_id,
            variant_id=variant_id,
            observation_ids=[str(observation_id)],
        )
    ])

    resolved, unresolved = _resolve_evidence_ids(
        db,
        analysis_id=analysis_id,
        variant_id=variant_id,
        source_ids=(str(observation_id),),
    )

    assert resolved == (evidence_id,)
    assert unresolved == ()


def test_unresolved_population_observation_cannot_become_acmg_evidence():
    analysis_id = uuid4()
    variant_id = uuid4()
    observation_id = uuid4()

    db = FakeDB([])

    resolved, unresolved = _resolve_evidence_ids(
        db,
        analysis_id=analysis_id,
        variant_id=variant_id,
        source_ids=(str(observation_id),),
    )

    assert resolved == ()
    assert unresolved == (str(observation_id),)


def test_cross_analysis_or_variant_evidence_is_not_resolved():
    analysis_id = uuid4()
    variant_id = uuid4()
    observation_id = uuid4()
    evidence_id = uuid4()

    db = FakeDB([
        SimpleNamespace(
            id=evidence_id,
            analysis_id=uuid4(),
            variant_id=variant_id,
            observation_ids=[str(observation_id)],
        ),
        SimpleNamespace(
            id=uuid4(),
            analysis_id=analysis_id,
            variant_id=uuid4(),
            observation_ids=[str(observation_id)],
        ),
    ])

    resolved, unresolved = _resolve_evidence_ids(
        db,
        analysis_id=analysis_id,
        variant_id=variant_id,
        source_ids=(str(observation_id),),
    )

    assert resolved == ()
    assert unresolved == (str(observation_id),)
