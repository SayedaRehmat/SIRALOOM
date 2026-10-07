"""Central executable provider registry.

The registry is intentionally explicit. A catalog entry without a registered
implementation can be displayed/managed, but it can never enter an execution
plan as executable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.app.domain.resource_capabilities import ProviderCapability


class ProviderRegistryError(RuntimeError):
    pass


ProviderFactory = Callable[[Any], Any]


@dataclass(frozen=True)
class RegisteredProvider:
    provider_id: str
    provider_version: str
    factory: ProviderFactory
    descriptor: ProviderCapability


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[tuple[str, str], RegisteredProvider] = {}

    def register(
        self,
        *,
        provider_id: str,
        provider_version: str,
        factory: ProviderFactory,
        descriptor: ProviderCapability,
    ) -> None:
        key = (provider_id, provider_version)
        if key in self._providers:
            raise ProviderRegistryError(
                f"provider implementation already registered: {provider_id}@{provider_version}"
            )
        self._providers[key] = RegisteredProvider(
            provider_id=provider_id,
            provider_version=provider_version,
            factory=factory,
            descriptor=descriptor,
        )

    def resolve(self, *, provider_id: str, provider_version: str) -> RegisteredProvider | None:
        return self._providers.get((provider_id, provider_version)) or self._providers.get((provider_id, "*"))

    def require(self, *, provider_id: str, provider_version: str) -> RegisteredProvider:
        result = self.resolve(provider_id=provider_id, provider_version=provider_version)
        if result is None:
            raise ProviderRegistryError(
                f"no executable provider implementation registered for "
                f"{provider_id}@{provider_version}"
            )
        return result

    def list(self) -> tuple[RegisteredProvider, ...]:
        return tuple(
            self._providers[key]
            for key in sorted(self._providers)
        )


registry = ProviderRegistry()

# Some providers require governed resource identity/qualification metadata in addition
# to the execution contract, so their workflow adapter constructs them directly.
SPECIALIZED_PROVIDER_IMPLEMENTATIONS = frozenset({"NCBI ClinVar"})

def provider_implementation_exists(provider_id: str, provider_version: str) -> bool:
    return registry.resolve(provider_id=provider_id, provider_version=provider_version) is not None or provider_id in SPECIALIZED_PROVIDER_IMPLEMENTATIONS


def register_builtin_providers() -> ProviderRegistry:
    """Register providers that are actually implemented in this repository.

    This function deliberately does not fabricate implementations for the
    future 50+ resource catalog.
    """
    if registry.list():
        return registry

    from backend.app.adapters.annotation.genebe import GeneBeProvider
    from backend.app.adapters.population.gnomad import (
        GnomADGraphQLProvider,
        LocalGnomADTabixProvider,
    )
    from backend.app.adapters.annotation.vep import VEPProvider
    from backend.app.adapters.clingen.variant_pathogenicity import ClinGenVariantPathogenicityProvider
    from backend.app.adapters.clingen.gene_disease_validity import ClinGenGeneDiseaseValidityProvider
    from backend.app.adapters.clingen.cspec_provider import ClinGenCSpecProvider

    from backend.app.domain.resource_capabilities import ResourceCapability

    registry.register(
        provider_id=VEPProvider.provider_id,
        provider_version="*",
        factory=VEPProvider.from_execution_contract,
        descriptor=ProviderCapability(
            provider_id=VEPProvider.provider_id,
            capabilities=frozenset({ResourceCapability.ANNOTATION}),
            supported_builds=frozenset({"GRCh37", "GRCh38"}),
        ),
    )
    registry.register(
        provider_id=GeneBeProvider.provider_id,
        provider_version=GeneBeProvider.provider_version,
        factory=GeneBeProvider.from_execution_contract,
        descriptor=ProviderCapability(
            provider_id=GeneBeProvider.provider_id,
            capabilities=frozenset({
                ResourceCapability.ANNOTATION,
                ResourceCapability.POPULATION_FREQUENCY,
            }),
            supported_builds=frozenset(GeneBeProvider.supported_builds),
            trial_only=True,
        ),
    )
    registry.register(
        provider_id=GnomADGraphQLProvider.provider_id,
        provider_version=GnomADGraphQLProvider.provider_version,
        factory=GnomADGraphQLProvider.from_execution_contract,
        descriptor=ProviderCapability(
            provider_id=GnomADGraphQLProvider.provider_id,
            capabilities=frozenset({ResourceCapability.POPULATION_FREQUENCY}),
            supported_builds=frozenset({"GRCh38"}),
        ),
    )
    registry.register(
        provider_id=ClinGenVariantPathogenicityProvider.provider_id,
        provider_version="*",
        factory=ClinGenVariantPathogenicityProvider.from_execution_contract,
        descriptor=ProviderCapability(
            provider_id=ClinGenVariantPathogenicityProvider.provider_id,
            capabilities=frozenset({ResourceCapability.CLINICAL_VARIANT}),
            supported_builds=frozenset({"GRCh37", "GRCh38"}),
        ),
    )
    registry.register(
        provider_id=ClinGenGeneDiseaseValidityProvider.provider_id,
        provider_version="*",
        factory=ClinGenGeneDiseaseValidityProvider.from_execution_contract,
        descriptor=ProviderCapability(
            provider_id=ClinGenGeneDiseaseValidityProvider.provider_id,
            capabilities=frozenset({ResourceCapability.GENE_DISEASE}),
            supported_builds=frozenset({"GRCh37", "GRCh38"}),
        ),
    )
    registry.register(
        provider_id=ClinGenCSpecProvider.provider_id,
        provider_version="*",
        factory=ClinGenCSpecProvider.from_execution_contract,
        descriptor=ProviderCapability(
            provider_id=ClinGenCSpecProvider.provider_id,
            capabilities=frozenset({ResourceCapability.ACMG_SPECIFICATION}),
            supported_builds=frozenset({"GRCh37", "GRCh38"}),
        ),
    )
    registry.register(
        provider_id=LocalGnomADTabixProvider.provider_id,
        provider_version=LocalGnomADTabixProvider.provider_version,
        factory=LocalGnomADTabixProvider.from_execution_contract,
        descriptor=ProviderCapability(
            provider_id=LocalGnomADTabixProvider.provider_id,
            capabilities=frozenset({ResourceCapability.POPULATION_FREQUENCY}),
            supported_builds=frozenset({"GRCh37", "GRCh38"}),
        ),
    )
    return registry
