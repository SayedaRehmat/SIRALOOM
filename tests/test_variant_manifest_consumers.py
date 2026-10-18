from uuid import uuid4

import pytest

from backend.app.api.v1.analyses import list_variants
from backend.app.infrastructure.db.models import AnalysisPartition, WorkflowStep
from backend.app.reporting.variant_report import build_variant_rows
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
