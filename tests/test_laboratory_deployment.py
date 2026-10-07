from backend.app.domain.laboratory_deployment import (
    LABORATORY_DEPLOYMENT_CONTRACT_VERSION,
    LaboratoryDeploymentContract,
    DeploymentServiceRequirement,
    DeploymentStorageRequirement,
    laboratory_deployment_contract,
)


def test_canonical_laboratory_contract_has_no_application_quotas():
    contract = laboratory_deployment_contract()

    contract.validate()

    assert contract.contract_version == LABORATORY_DEPLOYMENT_CONTRACT_VERSION
    assert contract.deployment_profile_type == "LABORATORY"
    assert contract.application_file_size_limit is None
    assert contract.application_analysis_count_limit is None
    assert contract.requires_tls_at_user_boundary is True
    assert contract.requires_durable_database is True
    assert contract.requires_durable_artifact_storage is True


def test_laboratory_contract_requires_core_runtime_and_scientific_capabilities():
    contract = laboratory_deployment_contract()

    assert {service.name for service in contract.services} == {
        "siraloom-api",
        "siraloom-worker",
        "postgresql",
        "redis",
    }
    assert contract.required_resource_capabilities == (
        "REFERENCE_PACKAGE",
        "ANNOTATION_ENGINE",
        "POPULATION",
        "ACMG_RULE_SPECIFICATION",
    )


def test_laboratory_contract_snapshot_and_hash_are_deterministic():
    first = laboratory_deployment_contract()
    second = laboratory_deployment_contract()

    assert first.snapshot() == second.snapshot()
    assert first.contract_hash == second.contract_hash
    assert len(first.contract_hash) == 64


def test_laboratory_contract_rejects_an_application_file_ceiling():
    contract = LaboratoryDeploymentContract(
        contract_version="1",
        deployment_profile_type="LABORATORY",
        services=(DeploymentServiceRequirement("api", "API"),),
        storage=(DeploymentStorageRequirement("artifacts", "Artifacts", "LOCAL"),),
        required_resource_capabilities=("REFERENCE_PACKAGE",),
        application_file_size_limit=512 * 1024 * 1024,
        application_analysis_count_limit=None,
        requires_tls_at_user_boundary=True,
        requires_durable_database=True,
        requires_durable_artifact_storage=True,
    )

    try:
        contract.validate()
    except ValueError as exc:
        assert "file-size ceiling" in str(exc)
    else:
        raise AssertionError("laboratory deployment must not define an application file-size ceiling")


def test_laboratory_contract_rejects_non_tls_user_boundary():
    contract = LaboratoryDeploymentContract(
        contract_version="1",
        deployment_profile_type="LABORATORY",
        services=(DeploymentServiceRequirement("api", "API"),),
        storage=(DeploymentStorageRequirement("artifacts", "Artifacts", "LOCAL"),),
        required_resource_capabilities=("REFERENCE_PACKAGE",),
        application_file_size_limit=None,
        application_analysis_count_limit=None,
        requires_tls_at_user_boundary=False,
        requires_durable_database=True,
        requires_durable_artifact_storage=True,
    )

    try:
        contract.validate()
    except ValueError as exc:
        assert "TLS" in str(exc)
    else:
        raise AssertionError("laboratory deployment must require TLS")
