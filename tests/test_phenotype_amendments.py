from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect

from backend.app.api.v1.phenotypes import PhenotypeInput, PhenotypeRetractionInput
from backend.app.domain.clinical_input_snapshot import (
    clinical_input_snapshot_digest,
    family_phenotype_observations,
    patient_phenotype_observations,
)


def test_superseding_phenotype_requires_reason_and_replacement_reference():
    with pytest.raises(ValidationError):
        PhenotypeInput(hpo_id="HP:0001250", supersedes_observation_id=uuid4())
    with pytest.raises(ValidationError):
        PhenotypeInput(hpo_id="HP:0001250", amendment_reason="Correcting a data-entry error")
    corrected = PhenotypeInput(
        hpo_id="HP:0001250",
        supersedes_observation_id=uuid4(),
        amendment_reason="Original term was entered against the wrong clinical finding.",
    )
    assert corrected.amendment_reason.startswith("Original term")


def test_phenotype_retraction_requires_nonempty_reason():
    with pytest.raises(ValidationError):
        PhenotypeRetractionInput(reason="   ")
    assert PhenotypeRetractionInput(reason="Entered in error").reason == "Entered in error"


def test_patient_and_family_phenotype_helpers_exclude_superseded_and_retracted_rows():
    proband_id = str(uuid4())
    relative_id = str(uuid4())
    snapshot = {
        "schema_version": 2,
        "clinical_context": {},
        "clinical_context_revision": None,
        "pedigree_context": {
            "members": [
                {"member_id": proband_id, "is_proband": True},
                {"member_id": relative_id, "is_proband": False},
            ],
            "relationships": [],
        },
        "phenotype_observations": [
            {"phenotype_id": str(uuid4()), "scope": "CASE", "hpo_id": "HP:0001250", "phenotype_status": "PRESENT", "subject_member_id": None, "record_lifecycle_status": "ACTIVE"},
            {"phenotype_id": str(uuid4()), "scope": "CASE", "hpo_id": "HP:0001251", "phenotype_status": "PRESENT", "subject_member_id": proband_id, "record_lifecycle_status": "ACTIVE"},
            {"phenotype_id": str(uuid4()), "scope": "CASE", "hpo_id": "HP:0001252", "phenotype_status": "PRESENT", "subject_member_id": proband_id, "record_lifecycle_status": "SUPERSEDED", "replacement_observation_id": str(uuid4()), "replacement_observation_fingerprint": "f" * 64},
            {"phenotype_id": str(uuid4()), "scope": "CASE", "hpo_id": "HP:0001253", "phenotype_status": "PRESENT", "subject_member_id": relative_id, "record_lifecycle_status": "ACTIVE"},
            {"phenotype_id": str(uuid4()), "scope": "CASE", "hpo_id": "HP:0001254", "phenotype_status": "PRESENT", "subject_member_id": relative_id, "record_lifecycle_status": "RETRACTED", "amendment_reason": "Recorded in error"},
        ],
        "gene_disease_evidence": [],
        "literature_evidence": [],
    }
    patient = patient_phenotype_observations(snapshot)
    family = family_phenotype_observations(snapshot)
    assert {row["hpo_id"] for row in patient} == {"HP:0001250", "HP:0001251"}
    assert {row["hpo_id"] for row in family} == {"HP:0001253"}


def test_phenotype_amendment_migration_creates_append_only_event_table(tmp_path, monkeypatch):
    database = tmp_path / "phenotype-amendments.sqlite"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0058_phenotype_observation_amendments")
    engine = create_engine(url)
    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("phenotype_observation_amendments")}
        assert {
            "case_id", "observation_id", "replacement_observation_id",
            "amendment_type", "reason", "amendment_fingerprint", "recorded_by",
        }.issubset(columns)
        indexes = {item["name"] for item in inspect(connection).get_indexes("phenotype_observation_amendments")}
        assert "ix_phenotype_amendments_case_recorded" in indexes
    engine.dispose()



def test_clinical_snapshot_digest_ignores_database_ids_but_tracks_phenotype_lifecycle():
    import copy

    member_id = str(uuid4())
    phenotype_id = str(uuid4())
    snapshot = {
        "schema_version": 3,
        "clinical_context": {
            "clinical_intake_revision": {
                "revision_id": str(uuid4()),
                "version": 1,
                "intake_status": "COMPLETE",
            }
        },
        "clinical_context_revision": {
            "revision_id": str(uuid4()),
            "version": 1,
            "revision_fingerprint": "a" * 64,
            "intake_status": "COMPLETE",
            "phenotype_review_status": "COMPLETE",
            "family_history_review_status": "COMPLETE",
            "context": {},
            "recorded_by": str(uuid4()),
            "recorded_at": "2026-11-01T10:00:00+00:00",
        },
        "pedigree_context": {
            "members": [{
                "member_id": member_id,
                "member_identifier": "proband",
                "is_proband": True,
                "specimen_id": str(uuid4()),
                "specimen_identifier": "SAMPLE-1",
            }],
            "relationships": [],
        },
        "phenotype_observations": [{
            "phenotype_id": phenotype_id,
            "case_id": str(uuid4()),
            "analysis_id": str(uuid4()),
            "scope": "ANALYSIS",
            "record_lifecycle_status": "ACTIVE",
            "hpo_id": "HP:0001250",
            "phenotype_status": "PRESENT",
            "subject_member_id": member_id,
        }],
        "gene_disease_evidence": [],
        "literature_evidence": [],
    }
    equivalent = copy.deepcopy(snapshot)
    equivalent["clinical_context"]["clinical_intake_revision"]["revision_id"] = str(uuid4())
    equivalent["clinical_context_revision"]["revision_id"] = str(uuid4())
    equivalent["clinical_context_revision"]["revision_fingerprint"] = "b" * 64
    equivalent["clinical_context_revision"]["recorded_by"] = str(uuid4())
    equivalent["clinical_context_revision"]["recorded_at"] = "2026-11-02T11:00:00+00:00"
    equivalent["pedigree_context"]["members"][0]["member_id"] = str(uuid4())
    equivalent["pedigree_context"]["members"][0]["specimen_id"] = str(uuid4())
    equivalent["phenotype_observations"][0]["phenotype_id"] = str(uuid4())
    equivalent["phenotype_observations"][0]["case_id"] = str(uuid4())
    equivalent["phenotype_observations"][0]["analysis_id"] = str(uuid4())
    equivalent["phenotype_observations"][0]["subject_member_id"] = equivalent["pedigree_context"]["members"][0]["member_id"]
    assert clinical_input_snapshot_digest(snapshot) == clinical_input_snapshot_digest(equivalent)

    changed = copy.deepcopy(snapshot)
    changed["phenotype_observations"][0]["record_lifecycle_status"] = "RETRACTED"
    changed["phenotype_observations"][0]["amendment_reason"] = "Observation was entered in error."
    assert clinical_input_snapshot_digest(snapshot) != clinical_input_snapshot_digest(changed)
