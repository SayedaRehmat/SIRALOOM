from types import SimpleNamespace

import pytest

from backend.app.adapters.population.secondary import (
    LocalTabixSecondaryPopulationProvider,
    SecondaryPopulationProviderError,
)


def test_secondary_local_population_provider_refuses_host_tabix_execution():
    provider = LocalTabixSecondaryPopulationProvider(
        "1000GENOMES",
        "/resources/1000genomes.vcf.gz",
        {"AF": "AF", "AC": "AC", "AN": "AN"},
        "GLOBAL",
        "1000 Genomes",
    )
    variant = SimpleNamespace(
        chromosome="1",
        position=12345,
        reference="A",
        alternate="G",
        genome_build="GRCh38",
    )

    with pytest.raises(
        SecondaryPopulationProviderError,
        match="LOCAL_POPULATION_GOVERNED_EXECUTION_UNAVAILABLE",
    ):
        provider.query_variant_with_provenance(variant)
