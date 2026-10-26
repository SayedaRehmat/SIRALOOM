import pytest

from backend.app.adapters.annotation.vep import VEPProvider, VEPProviderError
from backend.app.adapters.annotation.normalizer import normalize_annotation_payload
from backend.app.domain.provider_contract import ProviderRawResult
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.schemas import CanonicalVariant


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


def _normalize_consequences(transcripts):
    provider = VEPProvider.from_execution_contract(_contract())
    variant = CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=100, reference="A", alternate="G"
    )
    record = {
        "start": 100,
        "seq_region_name": "1",
        "allele_string": "A/G",
        "transcript_consequences": transcripts,
    }
    result = ProviderRawResult("annotate", [record], "fixture-sha256", {})
    return provider.normalize_result(
        result,
        inputs={"variants": [variant], "genome_build": "GRCh38"},
    ).observations[0]


def test_vep_prefers_one_mane_select_transcript_over_canonical():
    consequence = _normalize_consequences([
        {"transcript_id": "ENST_CANONICAL", "canonical": 1, "gene_symbol": "GENE1"},
        {
            "transcript_id": "ENST_MANE",
            "mane_select": "NM_000001.1",
            "gene_symbol": "GENE1",
            "consequence_terms": ["missense_variant"],
        },
    ])

    assert consequence["transcript"] == "ENST_MANE"
    assert consequence["transcript_selection"] == {
        "status": "SELECTED_MANE_SELECT",
        "policy": "UNIQUE_MANE_SELECT_THEN_UNIQUE_CANONICAL",
        "selected_transcript_id": "ENST_MANE",
    }
    assert normalize_annotation_payload("VEP", consequence)["transcript_selection"] == consequence[
        "transcript_selection"
    ]


@pytest.mark.parametrize(
    ("transcripts", "expected_status"),
    [
        ([{"transcript_id": "ENST_FIRST", "gene_symbol": "GENE1"}], "NO_PREFERRED_TRANSCRIPT"),
        (
            [
                {"transcript_id": "ENST_CANONICAL_1", "canonical": 1},
                {"transcript_id": "ENST_CANONICAL_2", "canonical": 1},
            ],
            "AMBIGUOUS_CANONICAL",
        ),
        (
            [
                {"transcript_id": "ENST_MANE_1", "mane_select": "NM_1"},
                {"transcript_id": "ENST_MANE_2", "mane_select": "NM_2"},
            ],
            "AMBIGUOUS_MANE_SELECT",
        ),
    ],
)
def test_vep_does_not_select_first_or_ambiguous_transcript(transcripts, expected_status):
    consequence = _normalize_consequences(transcripts)

    assert consequence["transcript"] is None
    assert consequence["gene_symbol"] is None
    assert consequence["effect"] == ""
    assert consequence["consequences"] == transcripts
    assert consequence["transcript_selection"]["status"] == expected_status


def test_vep_rejects_malformed_transcript_consequence_response():
    provider = VEPProvider.from_execution_contract(_contract())
    result = ProviderRawResult(
        "annotate",
        [{"transcript_consequences": {"transcript_id": "ENST1"}}],
        "fixture-sha256",
        {},
    )

    with pytest.raises(VEPProviderError, match="list of objects"):
        provider.validate_response(result)
