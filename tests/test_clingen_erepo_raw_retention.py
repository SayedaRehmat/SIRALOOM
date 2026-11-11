import hashlib
import json

from backend.app.adapters.clingen.variant_pathogenicity import ClinGenVariantPathogenicityProvider
from backend.app.evidence.engine import EvidenceEngine


def test_erepo_classification_responses_keep_exact_bytes_and_distinct_stable_identities(monkeypatch):
    provider = ClinGenVariantPathogenicityProvider(api_base_url="https://erepo.example")
    monkeypatch.setattr(
        provider, "_api_get_json",
        lambda path, params: {"classifications": [{"uuid": "classification-1"}, {"uuid": "classification-2"}]},
    )
    bodies = {
        "classification-1": b'{ "uuid" : "classification-1", "classification": "Pathogenic", "gene": "GENE1", "hgvs": ["NM_000001.1:c.1A>G"], "caid": "CA123", "condition": "Disease A" }',
        "classification-2": b'{"uuid":"classification-2","classification":"Benign","gene":"GENE1","hgvs":["NM_000001.1:c.1A>G"],"caid":"CA123","condition":"Disease B"}',
    }

    def get_detail(path, params):
        identifier = path.rsplit("/", 1)[-1]
        body = bodies[identifier]
        return json.loads(body.decode("utf-8")), body

    monkeypatch.setattr(provider, "_api_get_json_with_bytes", get_detail)
    results = provider.query_variant(
        gene="GENE1", hgvs=["NM_000001.1:c.1A>G"],
        request_fingerprint="a" * 64,
    )

    assert len(results) == 2
    assert results[0].raw_response_bytes == bodies["classification-1"]
    assert results[1].raw_response_bytes == bodies["classification-2"]
    assert hashlib.sha256(results[0].raw_response_bytes).hexdigest() != results[0].record_sha256
    assert results[0].response_request_fingerprint != results[1].response_request_fingerprint
    assert all(len(item.response_request_fingerprint) == 64 for item in results)


def test_erepo_per_classification_request_identity_is_retry_stable(monkeypatch):
    provider = ClinGenVariantPathogenicityProvider(api_base_url="https://erepo.example")
    monkeypatch.setattr(
        provider, "_api_get_json",
        lambda path, params: {"classifications": [{"uuid": "classification-1"}]},
    )
    body = b'{"uuid":"classification-1","classification":"Pathogenic","gene":"GENE1","hgvs":["NM_000001.1:c.1A>G"],"caid":"CA123"}'
    monkeypatch.setattr(
        provider, "_api_get_json_with_bytes",
        lambda path, params: (json.loads(body.decode("utf-8")), body),
    )
    first = provider.query_variant(
        gene="GENE1", hgvs=["NM_000001.1:c.1A>G"], request_fingerprint="b" * 64,
    )[0]
    retry = provider.query_variant(
        gene="GENE1", hgvs=["NM_000001.1:c.1A>G"], request_fingerprint="b" * 64,
    )[0]
    assert first.response_request_fingerprint == retry.response_request_fingerprint
    assert first.raw_response_bytes == retry.raw_response_bytes == body



def test_clingen_exact_response_bytes_reach_persistable_evidence_record(monkeypatch):
    provider = ClinGenVariantPathogenicityProvider(api_base_url="https://erepo.example")
    monkeypatch.setattr(
        provider, "_api_get_json",
        lambda path, params: {"classifications": [{"uuid": "classification-1"}]},
    )
    body = b'{ "uuid" : "classification-1", "classification" : "Pathogenic", "gene" : "GENE1", "hgvs" : ["NM_000001.1:c.1A>G"], "caid" : "CA123" }'
    monkeypatch.setattr(
        provider, "_api_get_json_with_bytes",
        lambda path, params: (json.loads(body.decode("utf-8")), body),
    )
    assertion = provider.query_variant(
        gene="GENE1", hgvs=["NM_000001.1:c.1A>G"],
        request_fingerprint="c" * 64,
    )[0]
    records = EvidenceEngine().build_from_clingen_variant_assertions(
        variant_id=__import__("uuid").uuid4(), assertions=[assertion],
        resource_id=__import__("uuid").uuid4(), resource_name="ClinGen ERepo",
        resource_version="2026-01", request_fingerprint="c" * 64,
        execution_metadata={"provider": "ClinGen ERepo"},
    )
    assert len(records) == 1
    assert records[0].raw_response_bytes == body
    assert records[0].request_fingerprint == assertion.response_request_fingerprint
    assert records[0].response_media_type == "application/json"
