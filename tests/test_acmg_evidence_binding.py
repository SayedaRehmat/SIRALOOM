from uuid import uuid4

from backend.app.acmg.assessment_service import _resolve_evidence_ids
from backend.app.infrastructure.db.models import Evidence


def test_acmg_resolves_observation_ids_to_evidence_ids(db_session):
    analysis_id = uuid4()
    variant_id = uuid4()
    observation_id = uuid4()
    evidence_id = uuid4()
    db_session.add(Evidence(
        id=evidence_id,
        analysis_id=analysis_id,
        variant_id=variant_id,
        evidence_type="POPULATION",
        statement="Observed rarity evidence",
        direction="PATHOGENIC",
        source_name="gnomAD",
        source_version="gnomad_r4",
        observation_ids=[str(observation_id)],
        payload={},
        created_by_type="SYSTEM",
        created_by_id="test",
        evidence_fingerprint="f" * 64,
    ))
    db_session.flush()

    assert _resolve_evidence_ids(
        db_session,
        analysis_id=analysis_id,
        variant_id=variant_id,
        observation_ids=(str(observation_id),),
    ) == (str(evidence_id),)


def test_acmg_does_not_treat_raw_observation_id_as_evidence_id(db_session):
    assert _resolve_evidence_ids(
        db_session,
        analysis_id=uuid4(),
        variant_id=uuid4(),
        observation_ids=(str(uuid4()),),
    ) == ()
