from backend.app.domain.resource_capabilities import provider_allowed_in_deployment


def test_public_gnomad_graphql_is_trial_only():
    assert provider_allowed_in_deployment("gnomad-graphql", is_trial=True)
    assert not provider_allowed_in_deployment("gnomad-graphql", is_trial=False)


def test_local_gnomad_is_allowed_for_laboratory_execution():
    assert provider_allowed_in_deployment("gnomad-local-tabix", is_trial=False)
