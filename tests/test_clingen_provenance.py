from backend.app.adapters.clingen.cspec import CSpecClient


def test_cspec_entity_captures_request_and_response_provenance(monkeypatch):
    body = {
        "data": {
            "entId": "SPEC-1",
            "entType": "RuleSet",
            "entContent": {
                "version": "1.0",
                "framework": "ACMG/AMP",
                "genes": ["GENE1"],
                "criteria": [{"criterion": "PM2", "max_allele_frequency": 0.0001}],
            },
            "modified": "2026-01-01T00:00:00Z",
        }
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    class FakeClient:
        def get(self, *args, **kwargs):
            return FakeResponse()

        def close(self):
            pass

    client = CSpecClient(base_url="https://example.test/cspec", client=FakeClient())
    entity = client.get_entity("RuleSet", "SPEC-1", detail="high")

    assert entity.request_fingerprint is not None
    assert len(entity.request_fingerprint) == 64
    assert entity.response_sha256 is not None
    assert len(entity.response_sha256) == 64
    assert entity.request_metadata == {
        "provider": "ClinGen",
        "endpoint": "https://example.test/cspec",
        "entity_type": "RuleSet",
        "entity_id": "SPEC-1",
        "detail": "high",
    }
