from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain.normalization_provider import (
    NormalizationProviderError,
    normalize_with_selected_provider,
    resolve_normalization_provider,
)


def _resource(*, status="ACTIVE", provider="bcftools", version="1.25"):
    return SimpleNamespace(
        id=uuid4(),
        resource_type="NORMALIZATION",
        status=status,
        provider=provider,
        version=version,
        name=f"{provider} {version}",
        checksum="a" * 64,
        metadata_json={
            "capabilities": ["NORMALIZATION"],
            "execution": {"executable": "bcftools"},
        },
    )


def test_selected_release_is_exact_version_not_latest_lookup():
    selection = resolve_normalization_provider(_resource(version="1.25"))

    assert selection.provider == "bcftools"
    assert selection.version == "1.25"
    assert selection.executable == "bcftools"


def test_qualified_release_can_be_selected_after_approval_resolution():
    selection = resolve_normalization_provider(_resource(status="QUALIFIED", version="1.26"))

    assert selection.version == "1.26"


def test_provider_requires_explicit_normalization_capability():
    resource = _resource(version="1.25")
    resource.metadata_json["capabilities"] = []

    with pytest.raises(NormalizationProviderError) as exc:
        resolve_normalization_provider(resource)

    assert exc.value.code == "NORMALIZATION_CAPABILITY_MISSING"


def test_unknown_normalization_provider_fails_closed():
    with pytest.raises(NormalizationProviderError, match="adapter is registered"):
        resolve_normalization_provider(_resource(provider="future-normalizer", version="2.0"))


def test_unqualified_candidate_cannot_execute():
    resource = _resource(status="CANDIDATE", version="1.26")
    with pytest.raises(NormalizationProviderError, match="not technically qualified"):
        resolve_normalization_provider(resource)


def test_execution_requires_explicit_lab_approval(monkeypatch, tmp_path):
    resource = _resource(version="1.25")
    with pytest.raises(NormalizationProviderError, match="organization-approved"):
        normalize_with_selected_provider(
            resource,
            tmp_path / "input.vcf",
            tmp_path / "output.vcf.gz",
            reference_fasta=tmp_path / "GRCh38.fa",
            approved=False,
        )


def test_execution_uses_selected_resource_version_not_global_settings(monkeypatch, tmp_path):
    resource = _resource(version="1.25")
    observed = {}

    def fake_normalize(*args, **kwargs):
        observed.update(kwargs)
        return {
            "tool": "bcftools",
            "tool_version": "bcftools 1.25",
        }

    monkeypatch.setattr(
        "backend.app.domain.normalization_provider.normalize_vcf_with_bcftools",
        fake_normalize,
    )

    result, selection = normalize_with_selected_provider(
        resource,
        tmp_path / "input.vcf",
        tmp_path / "output.vcf.gz",
        reference_fasta=tmp_path / "GRCh38.fa",
        approved=True,
    )

    assert observed["expected_bcftools_version"] == "1.25"
    assert observed["bcftools_executable"] == "bcftools"
    assert result["provider_version"] == "1.25"
    assert selection.version == "1.25"

def test_provider_uses_the_exact_executable_that_was_qualified():
    resource = _resource(version="1.25")
    resource.metadata_json["execution"]["toolchain"] = {
        "bcftools": {
            "version": "1.25",
            "executable": "/opt/siraloom/tools/bcftools/1.25/bin/bcftools",
        }
    }

    selection = resolve_normalization_provider(resource)

    assert selection.executable == "/opt/siraloom/tools/bcftools/1.25/bin/bcftools"


def test_provider_blocks_execution_contract_version_drift():
    resource = _resource(version="1.25")
    resource.metadata_json["execution"]["toolchain"] = {
        "bcftools": {
            "version": "1.26",
            "executable": "/opt/siraloom/tools/bcftools/1.26/bin/bcftools",
        }
    }

    with pytest.raises(NormalizationProviderError) as exc:
        resolve_normalization_provider(resource)

    assert exc.value.code == "NORMALIZATION_EXECUTION_VERSION_CONTRACT_MISMATCH"

