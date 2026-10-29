import pytest

from backend.app.domain.resource_capabilities import provider_allowed_in_deployment


def test_public_gnomad_graphql_is_trial_only():
    assert provider_allowed_in_deployment("gnomad-graphql", is_trial=True)
    assert not provider_allowed_in_deployment("gnomad-graphql", is_trial=False)


@pytest.mark.parametrize("provider", ["GeneBe", "GENEBE", "genebe", " GeneBe "])
def test_genebe_provider_aliases_remain_trial_only(provider):
    assert provider_allowed_in_deployment(provider, is_trial=True)
    assert not provider_allowed_in_deployment(provider, is_trial=False)


@pytest.mark.parametrize("provider", ["gnomad-graphql", "GNOMAD-GRAPHQL", " GnoMad-GraphQL "])
def test_gnomad_graphql_provider_aliases_remain_trial_only(provider):
    assert provider_allowed_in_deployment(provider, is_trial=True)
    assert not provider_allowed_in_deployment(provider, is_trial=False)


def test_local_gnomad_is_allowed_for_laboratory_execution():
    assert provider_allowed_in_deployment("gnomad-local-tabix", is_trial=False)
