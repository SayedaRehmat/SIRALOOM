from __future__ import annotations

import json
from types import SimpleNamespace

from backend.app.adapters.population import gnomad


def test_successful_graphql_population_observations_preserve_exact_response_bytes(monkeypatch):
    raw = (
        b'{ "data" : { "variant" : {'
        b'"joint":{"ac":10,"an":100,"homozygote_count":1,"populations":[]},'
        b'"exome":{"ac":5,"an":50,"homozygote_count":0,"populations":[]},'
        b'"genome":{"ac":5,"an":50,"homozygote_count":1,"populations":[]}'
        b'} } }'
    )

    class Response:
        content = raw

        def raise_for_status(self):
            return None

        def json(self):
            return json.loads(raw.decode("utf-8"))

    class Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(gnomad.httpx, "Client", Client)
    variant = SimpleNamespace(
        chromosome="1", position=12345, reference="A",
        alternate="G", genome_build="GRCh38",
    )

    observations = gnomad.GnomADGraphQLProvider().query_variant(variant)

    assert len(observations) == 6
    assert {item.population_code for item in observations} == {
        "GLOBAL", "MID", "GLOBAL_EXOMES", "MID_EXOMES",
        "GLOBAL_GENOMES", "MID_GENOMES",
    }
    assert all(item.raw_response_bytes == raw for item in observations)
