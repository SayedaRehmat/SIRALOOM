import pytest

from backend.app.domain.resource_source_contract import (
    ResourceSourceContractError,
    validate_execution_contract,
    validate_source_contract,
)


def valid_contract():
    return {
        "publisher": "Example Publisher",
        "canonical_source_url": "https://example.org/source",
        "artifact_url": "https://example.org/source/release.gz",
        "release_identity": "2026.10",
        "access_mode": "PUBLIC",
        "license_status": "NOT_REQUIRED",
        "checksum_status": "PUBLISHED_AND_VERIFIED",
        "authority_evidence_url": "https://example.org/docs/releases",
    }


def test_source_contract_requires_authoritative_urls():
    value = valid_contract()
    value["artifact_url"] = "https://example.org/source/release.gz"
    result = validate_source_contract(value)
    assert result.publisher == "Example Publisher"
    assert result.release_identity == "2026.10"


@pytest.mark.parametrize("field", ["canonical_source_url", "artifact_url", "authority_evidence_url"])
def test_source_contract_rejects_non_https_urls(field):
    value = valid_contract()
    value[field] = "ftp://example.org/file"
    with pytest.raises(ResourceSourceContractError, match="HTTPS"):
        validate_source_contract(value)


def test_verified_license_requires_license_or_terms_url():
    value = valid_contract()
    value["license_status"] = "VERIFIED"
    with pytest.raises(ResourceSourceContractError, match="verified license"):
        validate_source_contract(value)


def test_license_required_cannot_bypass_license_review():
    value = valid_contract()
    value["access_mode"] = "LICENSE_REQUIRED"
    value["license_status"] = "REVIEW_REQUIRED"
    with pytest.raises(ResourceSourceContractError, match="verified license"):
        validate_source_contract(value)


def test_restricted_source_can_be_discovered_but_not_misrepresented():
    value = valid_contract()
    value["access_mode"] = "AUTHENTICATED"
    value["license_status"] = "RESTRICTED"
    result = validate_source_contract(value)
    assert result.license_status == "RESTRICTED"


def test_execution_contract_requires_runtime_identity():
    execution = {
        "provider_id": "Example Publisher", "provider_version": "v1",
        "access_method": "HTTPS", "endpoint": "https://example.org/source/release.gz",
    }
    result = validate_execution_contract(
        execution, resource_provider="Example Publisher",
        resource_access_method="HTTPS", resource_location=None,
    )
    assert result.provider_version == "v1"


def test_execution_contract_rejects_provider_mismatch():
    with pytest.raises(ResourceSourceContractError, match="provider_id"):
        validate_execution_contract(
            {"provider_id": "Other", "provider_version": "v1",
             "access_method": "HTTPS", "endpoint": "https://example.org/x"},
            resource_provider="Example Publisher",
            resource_access_method="HTTPS", resource_location=None,
        )


def test_execution_contract_rejects_missing_remote_endpoint():
    with pytest.raises(ResourceSourceContractError, match="requires endpoint"):
        validate_execution_contract(
            {"provider_id": "Example Publisher", "provider_version": "v1",
             "access_method": "HTTPS"},
            resource_provider="Example Publisher",
            resource_access_method="HTTPS", resource_location=None,
        )
