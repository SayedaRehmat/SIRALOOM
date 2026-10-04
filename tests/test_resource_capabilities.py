from backend.app.domain.resource_capabilities import (
    ACMG_RULE_SPECIFICATION,
    ANNOTATION_ENGINE,
    CLINICAL_DATABASE,
    GENE_DISEASE,
    LITERATURE_PROVIDER,
    POPULATION,
    REFERENCE_PACKAGE,
    SPLICING_PREDICTOR,
    get_resource_capability,
    get_scientific_provider,
    supported_resource_types,
    supported_scientific_providers,
)


def test_catalog_contains_core_laboratory_resource_types():
    supported = set(supported_resource_types())
    assert {
        REFERENCE_PACKAGE,
        ANNOTATION_ENGINE,
        POPULATION,
        CLINICAL_DATABASE,
        GENE_DISEASE,
        LITERATURE_PROVIDER,
        ACMG_RULE_SPECIFICATION,
        SPLICING_PREDICTOR,
    } <= supported


def test_annotation_capability_declares_reference_dependency_and_outputs():
    capability = get_resource_capability(ANNOTATION_ENGINE)
    assert REFERENCE_PACKAGE in capability.required_dependency_types
    assert {"gene", "transcript", "consequence", "hgvs"} <= set(capability.produced_outputs)
    assert "LOCAL" in capability.supported_execution_modes
    assert "REMOTE_API" in capability.supported_execution_modes


def test_literature_is_modelled_as_remote_provider_not_bulk_reference_data():
    capability = get_resource_capability(LITERATURE_PROVIDER)
    assert capability.online_service_supported is True
    assert capability.bulk_local_preferred is False
    assert "REMOTE_API" in capability.supported_execution_modes
    assert "LITERATURE" in capability.evidence_types


def test_known_scientific_provider_catalog_maps_resources_correctly():
    assert get_scientific_provider("VEP").resource_type == ANNOTATION_ENGINE
    assert get_scientific_provider("ClinVar").resource_type == CLINICAL_DATABASE
    assert get_scientific_provider("gnomAD").resource_type == POPULATION
    assert get_scientific_provider("ClinGen").resource_type == ACMG_RULE_SPECIFICATION
    assert get_scientific_provider("PubMed").resource_type == LITERATURE_PROVIDER
    assert get_scientific_provider("OMIM").requires_organization_license is True
    assert get_scientific_provider("SpliceAI").requires_organization_license is True


def test_unknown_resource_and_provider_are_rejected():
    import pytest
    from backend.app.domain.resource_capabilities import ResourceCapabilityError

    with pytest.raises(ResourceCapabilityError):
        get_resource_capability("NOT_A_RESOURCE")

    with pytest.raises(ResourceCapabilityError):
        get_scientific_provider("NOT_A_PROVIDER")
