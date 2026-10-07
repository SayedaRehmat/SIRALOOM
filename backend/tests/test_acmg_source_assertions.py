from types import SimpleNamespace
from uuid import uuid4

from backend.app.acmg.source_assertions import (
    _source_direction,
    persist_clingen_source_assertions,
)
from backend.app.infrastructure.db.models import Evidence


class FakeDB:
    def __init__(self):
        self.rows = []
        self.added = []

    def scalar(self, _statement):
        return None

    def add(self, row):
        self.added.append(row)


def test_source_direction_is_criterion_level_only():
    assert _source_direction("PS3") == "SUPPORTS"
    assert _source_direction("PP3_Moderate") == "SUPPORTS"
    assert _source_direction("BS1") == "REFUTES"
    assert _source_direction("BA1") == "REFUTES"
    assert _source_direction("OTHER") == "NEUTRAL"


def test_clingen_source_assertion_is_bound_to_evidence_and_keeps_review_boundary():
    analysis_id = uuid4()
    variant_id = uuid4()
    evidence_id = uuid4()
    evidence = Evidence(
        id=evidence_id,
        analysis_id=analysis_id,
        variant_id=variant_id,
        evidence_type="CLINICAL_DATABASE",
        statement="ClinGen VCEP source assertion.",
        direction="SUPPORTS",
        source_name="ClinGen Variant Pathogenicity",
        source_version="ERepo",
        source_record_id="ERepo:abc-123",
        payload={
            "classification": "Likely Pathogenic",
            "condition": "Example disease",
            "gene": "TP53",
            "mondo_id": "MONDO:0018875",
            "expert_panel": "Example VCEP",
            "criterion_assertions": [
                {
                    "code": "PS3",
                    "status": "MET",
                    "strength": "Strong",
                    "source": "ClinGen ERepo classification API",
                    "rationale": "Functional assay supports the source assertion.",
                    "pmids": ["12345678"],
                },
                {
                    "code": "BS1",
                    "status": "NOT_MET",
                    "strength": None,
                    "source": "ClinGen ERepo classification API",
                    "rationale": "Frequency does not support the benign criterion.",
                    "pmids": [],
                },
            ],
            "criterion_detail_available": True,
            "criterion_detail_note": "Detailed ERepo criterion evidence preserved.",
            "erepo_classification_url": "https://erepo.clinicalgenome.org/evrepo/api/classification/abc-123",
        },
    )
    db = FakeDB()

    rows = persist_clingen_source_assertions(db, evidence=evidence)

    assert len(rows) == 2
    assert len(db.added) == 2
    assert {row.criterion for row in rows} == {"PS3", "BS1"}
    assert all(row.analysis_id == analysis_id for row in rows)
    assert all(row.variant_id == variant_id for row in rows)
    assert all(row.evidence_id == evidence_id for row in rows)
    assert rows[0].source_record_id == "ERepo:abc-123"
    assert rows[0].source_classification == "Likely Pathogenic"
    assert rows[0].condition == "Example disease"
    assert rows[0].gene == "TP53"
    assert rows[0].mondo_id == "MONDO:0018875"
    assert rows[0].pmids == ["12345678"]
    assert rows[0].source_payload["direction"] == "SUPPORTS"
    assert rows[1].source_payload["direction"] == "REFUTES"
