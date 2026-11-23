from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from backend.app.api.v1.phenotypes import (
    _active_export_observations,
    _phenotype_export_sidecar,
)


def _observation(identifier):
    return SimpleNamespace(
        id=identifier,
        record_fingerprint=f"{identifier.hex}",
        subject_member_id=None,
        hpo_id="HP:0001250",
        canonical_hpo_id="HP:0001250",
        label="Seizure",
        phenotype_status="PRESENT",
        present=True,
        onset=None,
        severity=None,
        observed_at=None,
        created_at=datetime(2026, 11, 7, tzinfo=UTC),
        clinical_attributes={},
        ontology_resolution={},
        source="CLINICAL_INPUT",
        evidence={},
    )


def test_standards_documents_exclude_superseded_and_retracted_phenotypes_but_sidecar_preserves_history():
    superseded_id = uuid4()
    retracted_id = uuid4()
    active_id = uuid4()
    observations = [
        _observation(superseded_id),
        _observation(retracted_id),
        _observation(active_id),
    ]
    amendments = {
        superseded_id: SimpleNamespace(
            observation_id=superseded_id,
            amendment_type="SUPERSEDED",
            replacement_observation_id=active_id,
            reason="Corrected clinical abstraction",
            recorded_at=datetime(2026, 11, 7, tzinfo=UTC),
        ),
        retracted_id: SimpleNamespace(
            observation_id=retracted_id,
            amendment_type="RETRACTED",
            replacement_observation_id=None,
            reason="Entered in error",
            recorded_at=datetime(2026, 11, 7, tzinfo=UTC),
        ),
    }

    active = _active_export_observations(observations, amendments)
    assert [row.id for row in active] == [active_id]

    sidecar = _phenotype_export_sidecar(observations, [], amendments)
    by_fingerprint = {row["record_fingerprint"]: row for row in sidecar}
    assert by_fingerprint[superseded_id.hex]["record_lifecycle_status"] == "SUPERSEDED"
    assert by_fingerprint[superseded_id.hex]["replacement_record_fingerprint"] == active_id.hex
    assert by_fingerprint[retracted_id.hex]["record_lifecycle_status"] == "RETRACTED"
    assert by_fingerprint[retracted_id.hex]["amendment_reason"] == "Entered in error"
    assert by_fingerprint[active_id.hex]["record_lifecycle_status"] == "ACTIVE"
