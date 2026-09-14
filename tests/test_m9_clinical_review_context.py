from uuid import uuid4
from datetime import datetime, timezone
from backend.app.review.service import _evidence_context_dict
from backend.app.infrastructure.db.models import Evidence


def test_m9_evidence_context_preserves_source_and_payload():
    row = Evidence(
        id=uuid4(), variant_id=uuid4(), analysis_id=uuid4(),
        evidence_type="LITERATURE", statement="Published functional evidence",
        direction="SUPPORTS", source_name="PubMed", source_version="2026-01",
        source_record_id="PMID:123", observation_ids=[], payload={"gene":"GENE1"},
        created_by_type="SYSTEM", created_by_id="workflow",
        created_at=datetime.now(timezone.utc),
    )
    out = _evidence_context_dict(row)
    assert out["type"] == "LITERATURE"
    assert out["source_record_id"] == "PMID:123"
    assert out["payload"]["gene"] == "GENE1"
