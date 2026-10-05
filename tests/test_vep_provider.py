import pytest

from backend.app.adapters.annotation.vep import VEPProvider, VEPError
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.schemas import CanonicalVariant


def _contract(**toolchain):
    return ResourceExecutionContract(
        provider_id="VEP",
        provider_version="112",
        access_method="LOCAL",
        endpoint=None,
        location="/resources/vep/112",
        dataset="vep-cache",
        execution_scope="ORGANIZATION_MANAGED",
        toolchain=toolchain or {"executable": "vep", "cache_version": "112"},
    )


def test_vep_provider_binds_exact_local_execution_contract():
    provider = VEPProvider.from_execution_contract(_contract(executable="vep-bin"))
    assert provider.executable == "vep-bin"
    assert provider.cache_dir == "/resources/vep/112"
    assert provider.provider_version == "112"


def test_vep_provider_preserves_all_transcript_consequences():
    payload = VEPProvider._record_to_payload(
        {
            "seq_region_name": "1",
            "start": 123,
            "allele_string": "A/T",
            "most_severe_consequence": "missense_variant",
            "transcript_consequences": [
                {
                    "gene_symbol": "GENE1",
                    "gene_id": "ENSG1",
                    "transcript_id": "ENST1",
                    "consequence": "missense_variant",
                    "canonical": 1,
                    "hgvsc": "c.123A>T",
                    "hgvsp": "p.Lys41Asn",
                },
                {
                    "gene_symbol": "GENE1",
                    "gene_id": "ENSG1",
                    "transcript_id": "ENST2",
                    "consequence": "synonymous_variant",
                },
            ],
        },
        build="GRCH38",
        provenance={"provider": "VEP"},
    )
    assert payload["chr"] == "1"
    assert payload["pos"] == 123
    assert payload["ref"] == "A"
    assert payload["alt"] == "T"
    assert payload["gene_symbol"] == "GENE1"
    assert payload["transcript"] == "ENST1"
    assert payload["effect"] == "missense_variant"
    assert len(payload["consequences"]) == 2


def test_vep_provider_rejects_cache_version_mismatch():
    with pytest.raises(VEPError, match="cache_version must exactly match"):
        VEPProvider.from_execution_contract(_contract(executable="vep", cache_version="111"))


def test_vep_provider_rejects_non_local_execution_contract():
    contract = ResourceExecutionContract(
        provider_id="VEP",
        provider_version="112",
        access_method="HTTPS",
        endpoint="https://example.invalid/vep",
        location=None,
        dataset=None,
        execution_scope="ORGANIZATION_MANAGED",
    )
    try:
        VEPProvider.from_execution_contract(contract)
    except VEPError:
        pass
    else:
        raise AssertionError("laboratory VEP must require a local execution contract")
