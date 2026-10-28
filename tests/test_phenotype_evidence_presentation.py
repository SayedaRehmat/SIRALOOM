from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from backend.app.api.v1 import evidence as evidence_api
from backend.app.domain.phenotype_evidence import phenotype_evidence_display_payload


def test_legacy_phenotype_score_is_removed_from_display_copy_only():
    stored = {
        "phenotype_match": {
            "status": "SCORED",
            "score": 0.75,
            "exact_overlap_score": 0.75,
            "score_semantics": "fraction",
            "matched_terms": ["HP:0001250"],
        },
        "source_release": "legacy",
    }
    original = deepcopy(stored)

    displayed = phenotype_evidence_display_payload("GENE_DISEASE", stored)

    assert "score" not in displayed["phenotype_match"]
    assert "exact_overlap_score" not in displayed["phenotype_match"]
    assert "score_semantics" not in displayed["phenotype_match"]
    assert displayed["phenotype_match"]["status"] == "CONTEXT_ONLY"
    assert displayed["phenotype_match"]["clinical_prioritization_validated"] is False
    assert displayed["phenotype_match"]["interpretive_use"] == "HUMAN_REVIEW_CONTEXT_ONLY"
    assert displayed["phenotype_match"]["matched_terms"] == ["HP:0001250"]
    assert stored == original


def test_display_sanitizer_does_not_rewrite_other_evidence_or_current_context():
    non_phenotype = {"score": 0.75}
    current_context = {"phenotype_match": {"status": "CONTEXT_ONLY", "matched_terms": []}}

    assert phenotype_evidence_display_payload("POPULATION", non_phenotype) == non_phenotype
    assert phenotype_evidence_display_payload("GENE_DISEASE", current_context) == current_context


def test_legacy_score_is_removed_from_evidence_api_without_mutating_storage(monkeypatch):
    analysis_id, variant_id, evidence_id = uuid4(), uuid4(), uuid4()
    stored_payload = {
        "phenotype_match": {"status": "SCORED", "score": 1.0, "matched_terms": ["HP:1"]}
    }
    row = SimpleNamespace(
        id=evidence_id,
        analysis_id=analysis_id,
        variant_id=variant_id,
        evidence_type="GENE_DISEASE",
        statement="legacy context",
        direction="CONTEXTUAL",
        source_name="HPO",
        source_version="old",
        source_record_id=None,
        observation_ids=[],
        payload=stored_payload,
        created_by_type="SYSTEM",
        created_by_id="test",
        created_at=SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00+00:00"),
    )
    analysis = SimpleNamespace(id=analysis_id)
    monkeypatch.setattr(evidence_api, "get_accessible_analysis", lambda *_: analysis)
    monkeypatch.setattr(evidence_api, "get_analysis_variant", lambda *_: object())

    class Db:
        def get(self, *_):
            return row

    response = evidence_api.get_evidence(evidence_id, Db(), object())

    assert response["payload"]["phenotype_match"]["status"] == "CONTEXT_ONLY"
    assert "score" not in response["payload"]["phenotype_match"]
    assert stored_payload["phenotype_match"]["score"] == 1.0
