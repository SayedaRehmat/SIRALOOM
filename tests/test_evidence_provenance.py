from uuid import uuid4

from backend.app.domain.evidence import evidence_fingerprint
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Evidence


def test_evidence_fingerprint_changes_with_upstream_response_hash():
    variant_id = uuid4()
    analysis_id = uuid4()
    observation_id = uuid4()
    common = dict(
        variant_id=variant_id,
        analysis_id=analysis_id,
        evidence_type="POPULATION",
        statement="Population observation is available.",
        direction="NEUTRAL",
        source_name="gnomAD",
        source_version="gnomad_r4",
        observation_ids=(observation_id,),
        payload={"population_code": "MID", "allele_frequency": 0.001},
        resource_id=uuid4(),
        source_record_id="1-555-T-C",
        request_fingerprint="a" * 64,
    )
    first = evidence_fingerprint(**common, response_sha256="b" * 64)
    second = evidence_fingerprint(**common, response_sha256="c" * 64)
    assert first != second


def test_evidence_model_exposes_upstream_provenance_columns():
    columns = set(Evidence.__table__.columns.keys())
    assert {
        "resource_id",
        "source_record_id",
        "request_fingerprint",
        "response_sha256",
        "request_metadata",
        "observed_at",
    }.issubset(columns)


def test_metadata_model_can_build_after_provenance_extension():
    assert "evidence" in Base.metadata.tables
    assert "clingen_specifications" in Base.metadata.tables
