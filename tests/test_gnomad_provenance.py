from backend.app.adapters.population.gnomad import GnomADGraphQLProvider
from backend.app.domain.schemas import CanonicalVariant
import httpx


def test_gnomad_graphql_observation_has_stable_provenance(monkeypatch):
    posted = {}
    body = {
        "data": {
            "variant": {
                "joint": {
                    "ac": 2, "an": 1000, "homozygote_count": 0,
                    "populations": [{"id": "mid", "ac": 1, "an": 100, "homozygote_count": 0}],
                },
                "exome": {
                    "ac": 2, "an": 500, "homozygote_count": 0,
                    "populations": [{"id": "mid", "ac": 1, "an": 100, "homozygote_count": 0}],
                },
                "genome": {"ac": 0, "an": 500, "homozygote_count": 0, "populations": []},
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
            posted.update(kwargs["json"])
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

    assert len(observations) == 6
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
    exomes = next(x for x in observations if x.population_code == "GLOBAL_EXOMES")
    genomes = next(x for x in observations if x.population_code == "GLOBAL_GENOMES")
    mid_genomes = next(x for x in observations if x.population_code == "MID_GENOMES")
    joint = next(x for x in observations if x.population_code == "GLOBAL")
    assert (joint.allele_count, joint.allele_number, joint.allele_frequency) == (2, 1000, 0.002)
    assert (exomes.allele_count, exomes.allele_number, exomes.allele_frequency) == (2, 500, 0.004)
    assert (genomes.allele_count, genomes.allele_number, genomes.allele_frequency) == (0, 500, 0.0)
    assert mid_genomes.availability == "NOT_AVAILABLE"
    assert mid_genomes.quality_status == "NO_ANCESTRY_OBSERVATION"
    assert mid_genomes.allele_frequency is None
    query_body = posted["query"]
    assert "variant(variantId: $variantId, dataset: $dataset)" in query_body
    assert "variantId: String!" in query_body
    assert "variant_id" not in query_body
    assert "ac\n              an" in query_body
    assert "joint {" in query_body
    assert "populations { id ac an homozygote_count }" in query_body
    assert "ac_hom" not in query_body

def test_gnomad_dataset_selector_is_not_presented_as_release():
    provider = GnomADGraphQLProvider(dataset_id="gnomad_r4")
    assert provider.dataset_id == "gnomad_r4"


def test_gnomad_graphql_not_found_is_durable_non_frequency_observation(monkeypatch):
    body = {"errors": [{"message": "Variant not found"}], "data": {"variant": None}}

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
            self.payload = kwargs["json"]
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    provider = GnomADGraphQLProvider(endpoint="https://example.test/api", dataset_id="gnomad_r4")
    observations = provider.query_variant(CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=555, reference="T", alternate="C"
    ))

    assert len(observations) == 6
    assert {item.availability for item in observations} == {"NOT_FOUND"}
    assert all(item.quality_status == "NO_MATCH" for item in observations)
    assert all(item.allele_count is None and item.allele_number is None and item.allele_frequency is None for item in observations)
    assert all(len(item.request_fingerprint) == 64 and len(item.response_sha256) == 64 for item in observations)
    assert all(item.request_metadata["dataset_selector"] == "gnomad_r4" for item in observations)


def test_gnomad_unexpected_graphql_errors_remain_provider_failures(monkeypatch):
    from backend.app.adapters.population.gnomad import GnomADProviderError
    import pytest

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"errors": [{"message": "Unknown field ac"}], "data": {"variant": None}}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, *args, **kwargs): return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    provider = GnomADGraphQLProvider(endpoint="https://example.test/api", dataset_id="gnomad_r4")
    with pytest.raises(GnomADProviderError, match="GraphQL errors"):
        provider.query_variant(CanonicalVariant(
            genome_build="GRCh38", chromosome="1", position=555, reference="T", alternate="C"
        ))


def test_gnomad_malformed_success_response_is_not_recorded_as_variant_absence(monkeypatch):
    from backend.app.adapters.population.gnomad import GnomADProviderError
    import pytest

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {}}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, *args, **kwargs): return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    provider = GnomADGraphQLProvider(endpoint="https://example.test/api", dataset_id="gnomad_r4")
    with pytest.raises(GnomADProviderError, match="missing data.variant"):
        provider.query_variant(CanonicalVariant(
            genome_build="GRCh38", chromosome="1", position=555, reference="T", alternate="C"
        ))
