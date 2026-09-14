import httpx
import pytest

from backend.app.adapters.clingen.cspec import CSpecClient, CSpecClientError
from backend.app.acmg.clingen_registry import snapshot_ruleset


def make_client(handler):
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return CSpecClient(base_url="https://cspec.clinicalgenome.org/cspec", client=client)


def test_cspec_service_and_ruleset_are_parseable():
    def handler(request):
        if request.url.path.endswith("/srvc"):
            return httpx.Response(200, json={"data": {"version": "1.3.14", "entTypes": {"RuleSet": {"entCount": 250}}}})
        return httpx.Response(200, json={
            "data": {
                "entId": "RULESET-1",
                "entType": "RuleSet",
                "entIri": "https://cspec.example/RULESET-1",
                "modified": "2026-09-07T00:00:00Z",
                "entContent": {
                    "version": "2.0",
                    "framework": "ACMG/AMP",
                    "genes": [{"symbol": "TEST1"}],
                    "criteria": [
                        {"criterion": "PM2", "strength": "SUPPORTING"},
                        {"criterion": "PP3", "strength": "SUPPORTING"},
                        {"criterion": "NOT_AN_ACMG_CODE", "strength": "STRONG"},
                    ],
                },
            }
        })

    client = make_client(handler)
    assert client.service_metadata()["data"]["version"] == "1.3.14"
    snap = snapshot_ruleset(client.get_entity("RuleSet", "RULESET-1"))
    assert snap.specification_id == "RULESET-1"
    assert snap.version == "2.0"
    assert snap.gene_scope == ("TEST1",)
    assert set(snap.criteria) == {"PM2", "PP3"}
    assert snap.to_criterion_specification().provider == "ClinGen"


def test_cspec_rejects_unknown_entity_type():
    client = make_client(lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(ValueError):
        client.get_entity("NotARealType", "X")


def test_cspec_fails_closed_on_unknown_response_shape():
    client = make_client(lambda request: httpx.Response(200, json={"unexpected": {}}))
    with pytest.raises(CSpecClientError):
        client.get_entity("RuleSet", "X")
