from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.adapters.nomenclature.hgnc import (
    HGNCArchiveProvider,
    HGNCArchiveProviderError,
)
from backend.app.domain.hgnc_crosswalk import (
    HGNC_ARCHIVE_RELEASE,
    HGNC_COMPLETE_URL,
    HGNC_LICENSE,
    HGNC_PUBLISHER,
    HGNC_WITHDRAWN_URL,
)
from backend.app.domain.resource_source_contract import ResourceExecutionContract


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _qualified_resource(tmp_path: Path):
    complete = tmp_path / "hgnc_complete_set.txt"
    withdrawn = tmp_path / "withdrawn.txt"
    complete.write_text(
        "hgnc_id\tsymbol\talias_symbol\tprev_symbol\tensembl_gene_id\n"
        "HGNC:1\tGENE1\tALIAS1\tOLD1\tENSG00000000001.1\n",
        encoding="utf-8",
    )
    withdrawn.write_text(
        "hgnc_id\tstatus\twithdrawn_symbol\tmerged_into_report(S) i.e. HGNC_ID|SYMBOL|STATUS\n"
        "HGNC:90\tMerged/Split\tRETIRED1\tHGNC:1|GENE1|Approved\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "siraloom.hgnc-acquisition.v1",
        "publisher": HGNC_PUBLISHER,
        "release": HGNC_ARCHIVE_RELEASE,
        "release_kind": "HGNC_QUARTERLY_ARCHIVE",
        "license": HGNC_LICENSE,
        "license_url": "https://www.genenames.org/about/license/",
        "authority_url": "https://www.genenames.org/download/archive/",
        "checksum_semantics": "LOCAL_SHA256; HGNC_DOES_NOT_PUBLISH_FILE_CHECKSUMS",
        "files": [
            {
                "filename": "hgnc_complete_set.txt",
                "source_url": HGNC_COMPLETE_URL,
                "sha256": _sha256(complete),
                "size_bytes": complete.stat().st_size,
            },
            {
                "filename": "withdrawn.txt",
                "source_url": HGNC_WITHDRAWN_URL,
                "sha256": _sha256(withdrawn),
                "size_bytes": withdrawn.stat().st_size,
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha256 = _sha256(manifest_path)
    contract = ResourceExecutionContract(
        provider_id="HGNC",
        provider_version=HGNC_ARCHIVE_RELEASE,
        access_method="LOCAL",
        endpoint=None,
        location=str(manifest_path),
        dataset="HGNC_ARCHIVE",
        toolchain={"manifest_sha256": manifest_sha256},
    )
    resolved = SimpleNamespace(contract=contract, resource_version=HGNC_ARCHIVE_RELEASE)
    return resolved, manifest_sha256, complete, withdrawn


def test_hgnc_archive_provider_verifies_manifest_and_resolves_identifiers(tmp_path):
    resolved, manifest_sha256, _complete, _withdrawn = _qualified_resource(tmp_path)
    provider = HGNCArchiveProvider.from_execution_contract(
        resolved,
        expected_sha256=manifest_sha256,
    )
    assert provider.release == HGNC_ARCHIVE_RELEASE
    assert provider.sha256 == manifest_sha256
    assert provider.resolve("GENE1").hgnc_id == "HGNC:1"
    assert provider.resolve("HGNC:90").hgnc_id == "HGNC:1"


def test_hgnc_archive_provider_rejects_manifest_or_artifact_tampering(tmp_path):
    resolved, manifest_sha256, complete, _withdrawn = _qualified_resource(tmp_path)
    complete.write_text(complete.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    with pytest.raises(HGNCArchiveProviderError, match="artifact"):
        HGNCArchiveProvider.from_execution_contract(
            resolved,
            expected_sha256=manifest_sha256,
        )


def test_hgnc_archive_provider_uses_the_manifest_pin_from_approved_execution_contract(tmp_path):
    resolved, manifest_sha256, _complete, _withdrawn = _qualified_resource(tmp_path)
    provider = HGNCArchiveProvider.from_execution_contract(resolved, expected_sha256=None)
    assert provider.sha256 == manifest_sha256


def test_hgnc_archive_provider_rejects_execution_contract_without_manifest_pin(tmp_path):
    resolved, _manifest_sha256, _complete, _withdrawn = _qualified_resource(tmp_path)
    contract = ResourceExecutionContract(
        provider_id="HGNC",
        provider_version=HGNC_ARCHIVE_RELEASE,
        access_method="LOCAL",
        endpoint=None,
        location=resolved.contract.location,
        dataset="HGNC_ARCHIVE",
        toolchain={},
    )
    unpinned = SimpleNamespace(contract=contract, resource_version=HGNC_ARCHIVE_RELEASE)
    with pytest.raises(HGNCArchiveProviderError, match="manifest SHA-256 pin"):
        HGNCArchiveProvider.from_execution_contract(unpinned, expected_sha256=None)


def test_hgnc_archive_provider_rejects_unexpected_artifact_names(tmp_path):
    resolved, _manifest_sha256, _complete, _withdrawn = _qualified_resource(tmp_path)
    manifest_path = Path(resolved.contract.location)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["filename"] = "../untrusted.tsv"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    digest = _sha256(manifest_path)
    with pytest.raises(HGNCArchiveProviderError, match="manifest SHA-256"):
        HGNCArchiveProvider.from_execution_contract(resolved, expected_sha256="0" * 64)
    contract = ResourceExecutionContract(
        provider_id="HGNC",
        provider_version=HGNC_ARCHIVE_RELEASE,
        access_method="LOCAL",
        endpoint=None,
        location=str(manifest_path),
        dataset="HGNC_ARCHIVE",
        toolchain={"manifest_sha256": digest},
    )
    tampered_resolved = SimpleNamespace(contract=contract, resource_version=HGNC_ARCHIVE_RELEASE)
    with pytest.raises(HGNCArchiveProviderError, match="artifact set"):
        HGNCArchiveProvider.from_execution_contract(tampered_resolved, expected_sha256=digest)


def test_hgnc_archive_provider_is_registered_as_a_nomenclature_capability():
    from backend.app.domain.provider_registry import register_builtin_providers
    from backend.app.domain.resource_capabilities import (
        GENE_NOMENCLATURE,
        get_scientific_provider,
    )

    descriptor = register_builtin_providers().require(
        provider_id=HGNCArchiveProvider.provider_id,
        provider_version="2026-10-06",
    )
    assert descriptor.descriptor.capabilities == frozenset({GENE_NOMENCLATURE})
    assert get_scientific_provider("HGNC").resource_type == GENE_NOMENCLATURE



def test_builtin_provider_registration_does_not_skip_hgnc_when_registry_is_partially_populated(monkeypatch):
    import backend.app.domain.provider_registry as provider_registry_module
    from backend.app.domain.provider_registry import ProviderCapability, ProviderRegistry

    registry = ProviderRegistry()
    registry.register(
        provider_id="CUSTOM_TEST_PROVIDER",
        provider_version="1",
        factory=lambda resolved: resolved,
        descriptor=ProviderCapability(
            provider_id="CUSTOM_TEST_PROVIDER",
            capabilities=frozenset(),
            supported_builds=frozenset(),
        ),
    )
    monkeypatch.setattr(provider_registry_module, "registry", registry)
    provider_registry_module.register_builtin_providers()
    assert registry.resolve(provider_id="HGNC", provider_version=HGNC_ARCHIVE_RELEASE) is not None
