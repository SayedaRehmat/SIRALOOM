from backend.app.domain.provider_registry import register_builtin_providers


def test_builtin_registry_contains_only_real_implementations():
    registry = register_builtin_providers()
    ids = {(item.provider_id, item.provider_version) for item in registry.list()}
    assert ("VEP", "*") in ids
    assert ("GeneBe", "api-public-v1") in ids
    assert ("gnomad-graphql", "graphql") in ids
    assert ("gnomad-local-tabix", "vcf-tabix") in ids


def test_unknown_provider_is_not_executable():
    registry = register_builtin_providers()
    assert registry.resolve(
        provider_id="FutureProvider",
        provider_version="1",
    ) is None


def test_specialized_clinvar_provider_is_known_to_orchestrator():
    from backend.app.domain.provider_registry import provider_implementation_exists
    assert provider_implementation_exists("NCBI ClinVar", "release-xml-v1")
