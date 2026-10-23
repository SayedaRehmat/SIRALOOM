import json
from uuid import uuid4

import pytest

from backend.app.api.v1.analyses import list_variants
from backend.app.infrastructure.db.models import AnalysisPartition, Case, PopulationObservation, Resource, WorkflowStep
from backend.app.reporting.variant_report import build_variant_rows, render_json
from tests.test_review_queue import seed


@pytest.mark.parametrize("manifest_value", [[], None, "malformed", 42])
def test_present_malformed_normalization_manifest_prevents_annotation_fallback(manifest_value):
    db, principal, analysis, _variant = seed()
    db.add(AnalysisPartition(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize",
        partition_key="0:0", ordinal=0, record_start=0, record_end=0,
        variant_count=0, status="SUCCEEDED", metadata_json={"variant_ids": manifest_value},
    ))
    db.commit()

    assert list_variants(analysis.id, db=db, principal=principal) == []
    assert build_variant_rows(db, analysis.id) == []


def test_legacy_analysis_without_normalization_manifest_keeps_annotation_fallback():
    db, principal, analysis, variant = seed()

    listed = list_variants(analysis.id, db=db, principal=principal)
    report_rows = build_variant_rows(db, analysis.id)

    assert [row["variant_id"] for row in listed] == [str(variant.id)]
    assert [row["variant_id"] for row in report_rows] == [str(variant.id)]


def test_completed_empty_normalization_step_does_not_enable_legacy_fallback():
    db, principal, analysis, _variant = seed()
    db.add(WorkflowStep(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize", step_order=2,
        status="SUCCEEDED", attempt=1,
        metadata_json={"streaming": True, "partition_count": 0, "record_count": 0},
    ))
    db.commit()

    assert list_variants(analysis.id, db=db, principal=principal) == []
    assert build_variant_rows(db, analysis.id) == []


def test_variant_csv_rows_keep_gnomad_exome_and_genome_frequencies_distinct():
    db, _principal, analysis, variant = seed()
    resource = Resource(
        id=uuid4(), organization_id=db.get(Case, analysis.case_id).organization_id, name="gNOMAD",
        provider="gnomAD", resource_type="POPULATION", version="test-release",
        genome_build="GRCh38", access_method="API", status="APPROVED",
    )
    db.add(resource)
    db.add_all([
        PopulationObservation(
            id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
            resource_id=resource.id, population_level="GLOBAL",
            population_code="GLOBAL_EXOMES", population_label="gnomAD exomes",
            allele_count=2, allele_number=500, allele_frequency=0.004,
            availability="AVAILABLE", quality_status="PASS",
        ),
        PopulationObservation(
            id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
            resource_id=resource.id, population_level="GLOBAL",
            population_code="GLOBAL_GENOMES", population_label="gnomAD genomes",
            allele_count=0, allele_number=500, allele_frequency=0.0,
            availability="AVAILABLE", quality_status="PASS",
        ),
    ])
    db.commit()

    row = build_variant_rows(db, analysis.id)[0]
    assert row["gnomad_exomes_af"] == 0.004
    assert row["gnomad_genomes_af"] == 0.0
    # The legacy fixture's global row has an AF without its denominator.
    assert row["global_af"] is None
    assert json.loads(render_json([row]))["schema_version"] == "1.1.0"


def test_variant_report_hides_stored_frequency_without_denominator():
    db, _principal, analysis, variant = seed()
    resource = Resource(
        id=uuid4(), organization_id=db.get(Case, analysis.case_id).organization_id,
        name="provider", provider="GeneBe", resource_type="POPULATION",
        version="test", genome_build="GRCh38", access_method="API", status="APPROVED",
    )
    db.add(resource)
    db.add(PopulationObservation(
        id=uuid4(), analysis_id=analysis.id, variant_id=variant.id, resource_id=resource.id,
        population_level="GLOBAL", population_code="GLOBAL_EXOMES", population_label="gnomAD exomes",
        allele_count=1, allele_number=None, allele_frequency=0.01,
        availability="AVAILABLE", quality_status="PROVIDER_DERIVED",
    ))
    db.commit()
    row = build_variant_rows(db, analysis.id)[0]
    assert row["gnomad_exomes_af"] is None
