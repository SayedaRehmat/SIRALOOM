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


def test_new_qualified_release_does_not_execute_until_active_binding_selects_it():
    with pytest.raises(NormalizationProviderError, match="not ACTIVE"):
        resolve_normalization_provider(_resource(status="QUALIFIED", version="1.26"))


def test_unknown_normalization_provider_fails_closed():
    with pytest.raises(NormalizationProviderError, match="not registered"):
        resolve_normalization_provider(_resource(provider="future-normalizer", version="2.0"))


def test_execution_uses_resource_version_and_does_not_read_global_settings(monkeypatch, tmp_path):
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
    )

    assert observed["expected_bcftools_version"] == "1.25"
    assert observed["bcftools_executable"] == "bcftools"
    assert result["provider_version"] == "1.25"
    assert selection.version == "1.25"
