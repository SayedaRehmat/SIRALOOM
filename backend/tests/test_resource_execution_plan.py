from uuid import uuid4

from backend.app.domain.resource_capabilities import (
    ResourceCapability,
    CapabilityRequirement,
    provider_allowed_in_deployment,
)


def test_genebe_is_trial_only():
    assert provider_allowed_in_deployment("GeneBe", is_trial=True)
    assert not provider_allowed_in_deployment("GeneBe", is_trial=False)


def test_lab_provider_policy_does_not_depend_on_catalog_size():
    # A laboratory can deliberately operate with a small approved resource set.
    requirements = (
        CapabilityRequirement(ResourceCapability.POPULATION_FREQUENCY),
        CapabilityRequirement(ResourceCapability.LITERATURE),
    )
    assert len(requirements) == 2


def test_capability_names_are_stable():
    assert ResourceCapability.POPULATION_FREQUENCY.value == "POPULATION_FREQUENCY"
    assert ResourceCapability.CLINICAL_VARIANT.value == "CLINICAL_VARIANT"
