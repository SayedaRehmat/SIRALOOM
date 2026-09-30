from backend.app.adapters.population.gnomad import GnomADGraphQLProvider
from backend.app.domain.schemas import CanonicalVariant
import httpx


def test_gnomad_graphql_observation_has_stable_provenance(monkeypatch):
    body = {
        "data": {
            "variant": {
                "variantId": "1-555-T-C",
                "ac": 2,
                "an": 1000,
                "populations": [
                    {"id": "mid", "ac": 1, "an": 100, "ac_hom": 0, "ac_hemi": 0}
                ],
                "exome": {"ac": 2, "an": 500, "populations": []},
                "genome": {"ac": 0, "an": 500, "populations": []},
            }
        }
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    provider = GnomADGraphQLProvider(
        endpoint="https://example.test/api",
        dataset_id="gnomad_r4",
    )
    variant = CanonicalVariant(
        genome_build="GRCh38",
        chromosome="1",
        position=555,
        reference="T",
        alternate="C",
    )
    observations = provider.query_variant(variant)

    assert len(observations) == 2
    mid = next(x for x in observations if x.population_code == "MID")
    assert mid.source_record_id == "1-555-T-C"
    assert len(mid.request_fingerprint) == 64
    assert len(mid.response_sha256) == 64
    assert mid.request_metadata["dataset_selector"] == "gnomad_r4"
    assert mid.request_metadata["genome_build"] == "GRCh38"
    assert mid.observed_at.endswith("+00:00")
    assert mid.allele_count == 1
    assert mid.allele_number == 100
    assert mid.allele_frequency == 0.01


def test_gnomad_dataset_selector_is_not_presented_as_release():
    provider = GnomADGraphQLProvider(dataset_id="gnomad_r4")
    assert provider.dataset_id == "gnomad_r4"
