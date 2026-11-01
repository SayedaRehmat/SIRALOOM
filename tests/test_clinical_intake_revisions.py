from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect

from backend.app.api.v1.clinical_intake import (
    AgeAtAssessmentInput,
    ClinicalIntakeInput,
    DifferentialDiagnosisInput,
    clinical_intake_fingerprint,
)


def test_draft_clinical_intake_can_be_incomplete_without_claiming_review_complete():
    body = ClinicalIntakeInput(
        intake_status="DRAFT",
        referral_indication="Developmental delay",
    )
    assert body.intake_status == "DRAFT"
    assert body.phenotype_review_status == "PENDING"
    assert body.family_history_review_status == "PENDING"


def test_complete_clinical_intake_requires_referral_and_explicit_review_states():
    with pytest.raises(ValidationError):
        ClinicalIntakeInput(intake_status="COMPLETE")

    with pytest.raises(ValidationError):
        ClinicalIntakeInput(
            intake_status="COMPLETE",
            referral_indication="Developmental delay",
            referral_question="Investigate a possible monogenic cause",
        )


def test_complete_clinical_intake_requires_rationales_for_not_assessed_states():
    with pytest.raises(ValidationError):
        ClinicalIntakeInput(
            intake_status="COMPLETE",
            referral_indication="Developmental delay",
            referral_question="Investigate a possible monogenic cause",
            phenotype_review_status="NOT_ASSESSED",
            family_history_review_status="NOT_APPLICABLE",
        )
    body = ClinicalIntakeInput(
        intake_status="COMPLETE",
        referral_indication="Developmental delay",
        referral_question="Investigate a possible monogenic cause",
        phenotype_review_status="NOT_ASSESSED",
        family_history_review_status="NOT_APPLICABLE",
        phenotype_review_note="Phenotype data were not supplied by the referring service.",
        family_history_review_note="Family history was not available at accession.",
    )
    assert body.phenotype_review_status == "NOT_ASSESSED"


def test_complete_intake_accepts_structured_age_prior_testing_and_differentials():
    body = ClinicalIntakeInput(
        intake_status="COMPLETE",
        referral_indication="Unexplained seizures",
        referral_question="Evaluate a suspected inherited epilepsy",
        clinical_summary="Recurrent seizures beginning in early childhood.",
        age_at_assessment={"value": 7, "unit": "YEARS", "as_of_date": "2026-10-15"},
        prior_testing=[{
            "test_type": "Chromosomal microarray",
            "performed_at": "2024-05-01",
            "laboratory": "Regional genetics laboratory",
            "accession_reference": "LAB-2024-001",
            "result_status": "NEGATIVE",
            "result_summary": "No reportable copy-number finding.",
        }],
        differential_diagnoses=[{
            "system": "http://snomed.info/sct",
            "code": "84757009",
            "display": "Epilepsy",
            "certainty": "SUSPECTED",
        }],
        phenotype_review_status="NOT_ASSESSED",
        family_history_review_status="NOT_ASSESSED",
        phenotype_review_note="HPO observations pending review.",
        family_history_review_note="Pedigree history pending review.",
    )
    assert body.age_at_assessment.as_of_date == date(2026, 10, 15)
    assert body.prior_testing[0].result_status == "NEGATIVE"
    assert body.differential_diagnoses[0].system == "http://snomed.info/sct"


def test_differential_diagnosis_requires_coded_concept_system_uri():
    with pytest.raises(ValidationError):
        DifferentialDiagnosisInput(system="SNOMED", code="123", display="Condition")


def test_age_at_assessment_rejects_non_finite_values():
    with pytest.raises(ValidationError):
        AgeAtAssessmentInput(value=float("nan"), unit="YEARS", as_of_date=date(2026, 10, 15))
    with pytest.raises(ValidationError):
        AgeAtAssessmentInput(value=7, unit="YEARS")


def test_clinical_intake_revision_fingerprint_is_deterministic_and_version_sensitive():
    base = ClinicalIntakeInput(
        intake_status="DRAFT",
        referral_indication="Developmental delay",
        clinical_summary="Initial referral",
    )
    same = ClinicalIntakeInput(
        clinical_summary="Initial referral",
        referral_indication="Developmental delay",
        intake_status="DRAFT",
    )
    changed = ClinicalIntakeInput(
        intake_status="DRAFT",
        referral_indication="Developmental delay",
        clinical_summary="Updated referral summary",
    )
    assert clinical_intake_fingerprint(base) == clinical_intake_fingerprint(same)
    assert clinical_intake_fingerprint(base) != clinical_intake_fingerprint(changed)


def test_clinical_intake_revision_migration_creates_versioned_append_only_table(tmp_path, monkeypatch):
    database = tmp_path / "clinical-intake-revisions.sqlite"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0057_clinical_intake_revisions")
    engine = create_engine(url)
    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("clinical_intake_revisions")}
        assert {
            "case_id", "version", "schema_version", "revision_fingerprint",
            "intake_status", "phenotype_review_status", "family_history_review_status",
            "context", "recorded_by", "recorded_at",
        }.issubset(columns)
        indexes = {item["name"] for item in inspect(connection).get_indexes("clinical_intake_revisions")}
        assert "ix_clinical_intake_revisions_case_version" in indexes
    engine.dispose()
