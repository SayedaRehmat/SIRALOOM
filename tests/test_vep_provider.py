import pytest

from backend.app.adapters.annotation.vep import VEPProvider, VEPProviderError
from backend.app.domain.resource_source_contract import ResourceExecutionContract


def _contract(*, access_method="LOCAL", toolchain=None):
    return ResourceExecutionContract(
        provider_id="VEP",
        provider_version="115",
        access_method=access_method,
        endpoint=None,
        location="/resources/vep/115",
        dataset="vep-cache",
        execution_scope="ORGANIZATION_MANAGED",
        toolchain=toolchain if toolchain is not None else {
            "vep_binary": "/opt/vep/vep",
            "cache_dir": "/resources/vep/115",
            "cache_version": "115",
            "assembly": "GRCh38",
            "fasta": "/resources/GRCh38.fa",
        },
    )


def test_vep_provider_uses_only_the_governed_local_toolchain():
    provider = VEPProvider.from_execution_contract(_contract())

    assert provider.binary == "/opt/vep/vep"
    assert provider.cache_dir == "/resources/vep/115"
    assert provider.cache_version == "115"
    assert provider.assembly == "GRCh38"
    assert provider.fasta == "/resources/GRCh38.fa"
    assert provider.contract.provider_version == "115"


def test_vep_provider_rejects_nonlocal_execution():
    with pytest.raises(VEPProviderError, match="requires LOCAL/FILE/LOCAL_ONLY"):
        VEPProvider.from_execution_contract(
            _contract(access_method="HTTPS")
        )


def test_vep_provider_requires_explicit_cache_version():
    toolchain = {
        "vep_binary": "/opt/vep/vep",
        "cache_dir": "/resources/vep/115",
        "assembly": "GRCh38",
    }
    with pytest.raises(VEPProviderError, match="must declare cache_version"):
        VEPProvider.from_execution_contract(_contract(toolchain=toolchain))


def test_vep_provider_rejects_extra_args_that_override_governed_paths():
    toolchain = {
        "vep_binary": "/opt/vep/vep",
        "cache_dir": "/resources/vep/115",
        "cache_version": "115",
        "extra_args": ["--input_file=/tmp/unapproved.vcf"],
    }
    with pytest.raises(VEPProviderError, match="may not override governed"):
        VEPProvider.from_execution_contract(_contract(toolchain=toolchain))
