import httpx
import pytest

from backend.app.adapters.clingen.cspec import CSpecClient, CSpecClientError
from backend.app.acmg.clingen_registry import snapshot_ruleset, snapshot_sequence_variant_interpretation, select_current_released_version



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


def test_cspec_svi_version_selection_is_released_and_fail_closed():
    from backend.app.adapters.clingen.cspec import CSpecEntity

    def entity(ent_id, version, state="Released", legacy_replaced=False, legacy_fully_superseded=None):
        content = {"version": version, "state": state, "legacyReplaced": legacy_replaced}
        if legacy_fully_superseded is not None:
            content["legacyFullySuperseded"] = legacy_fully_superseded
        return CSpecEntity(
            ent_id=ent_id,
            ent_type="SequenceVariantInterpretation",
            ldh_id=None,
            ent_iri=None,
            content=content,
            modified=None,
            raw={"entId": ent_id, "entType": "SequenceVariantInterpretation", "entContent": content},
        )

    selected = select_current_released_version([
        entity("OLD", "1.0"),
        entity("REPLACED", "3.0", legacy_replaced=True),
        entity("NOT_RELEASED", "4.0", state="Classification Rules In Prep"),
        entity("CURRENT", "2.2"),
    ])
    assert selected is not None
    assert selected.ent_id == "CURRENT"


def test_cspec_svi_snapshot_preserves_provenance_and_structured_criteria():
    from backend.app.adapters.clingen.cspec import CSpecEntity

    entity = CSpecEntity(
        ent_id="GN123",
        ent_type="SequenceVariantInterpretation",
        ldh_id="LDH:123",
        ent_iri="https://cspec.clinicalgenome.org/cspec/SequenceVariantInterpretation/id/GN123/version/2.2",
        content={
            "version": "2.2",
            "framework": "ACMG/AMP",
            "gene": [{"symbol": "RAG1", "id": "HGNC:9831"}],
            "disease": [{"label": "Example disease", "id": "MONDO:0000572"}],
            "criteria": {"PM2": {"strength": "SUPPORTING"}, "PP3": {"strength": "MODERATE"}},
        },
        modified="2026-09-01T00:00:00Z",
        raw={"entId": "GN123", "entType": "SequenceVariantInterpretation"},
        request_fingerprint="request-sha",
        response_sha256="response-sha",
        request_metadata={"path": "/SequenceVariantInterpretation/id/GN123/version/2.2"},
    )
    snapshot = snapshot_sequence_variant_interpretation(entity)
    assert snapshot.version == "2.2"
    assert snapshot.gene_scope == ("RAG1", "HGNC:9831")
    assert snapshot.disease_scope == ("Example disease", "MONDO:0000572")
    assert snapshot.criteria["PM2"]["strength"] == "SUPPORTING"
    assert snapshot.request_fingerprint == "request-sha"
    assert snapshot.response_sha256 == "response-sha"
