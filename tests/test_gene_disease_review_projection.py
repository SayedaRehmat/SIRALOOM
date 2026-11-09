from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from backend.app.review.service import _evidence_context_dict


def test_review_evidence_projection_keeps_gene_disease_reconciliation_payload():
    evidence = SimpleNamespace(
        id=uuid4(), evidence_type="GENE_DISEASE", source_name="SIRALOOM gene-disease reconciliation",
        source_version="1", statement="Neutral reconciliation context", direction="NEUTRAL",
        source_record_id="reconciliation-1", resource_id=None, request_fingerprint=None,
        response_sha256=None, request_metadata={}, observation_ids=[], created_at=datetime.now(timezone.utc),
        payload={"interpretive_use":"GENE_DISEASE_RECONCILIATION_CONTEXT_ONLY", "clinical_conclusion":False,
                 "requires_human_review":True, "review_reasons":["SOURCE_DIMENSION_CONFLICT"],
                 "source_provenance":[{"source":"G2P", "source_record_id":"G2P:1", "raw_assertion":{"x":"y"}}]},
    )
    result = _evidence_context_dict(evidence)
    assert result["type"] == "GENE_DISEASE"
    assert result["direction"] == "NEUTRAL"
    assert result["payload"]["clinical_conclusion"] is False
    assert result["payload"]["source_provenance"][0]["raw_assertion"] == {"x":"y"}
