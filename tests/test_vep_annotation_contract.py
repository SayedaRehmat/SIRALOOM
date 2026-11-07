from __future__ import annotations

import pytest

from backend.app.adapters.annotation.normalizer import normalize_annotation_payload
from backend.app.adapters.annotation.vep import VEPProvider, VEPProviderError
from backend.app.domain.provider_contract import ProviderRawResult
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.tool_execution import current_platform_id
from backend.app.config import settings


def _provider() -> VEPProvider:
    return VEPProvider.from_execution_contract(
        ResourceExecutionContract(
            provider_id="VEP",
            provider_version="115",
            access_method="LOCAL",
            endpoint=None,
            location="/resources/vep/115",
            dataset="vep-cache",
            execution_scope="ORGANIZATION_MANAGED",
            toolchain={
                "vep_binary": "/opt/vep/vep",
                "cache_dir": "/resources/vep/115",
                "cache_version": "115",
                "assembly": "GRCh38",
                "cache_manifest": "/resources/vep/115.manifest.json",
                "cache_manifest_sha256": "a" * 64,
                "cache_artifact_sha256": "b" * 64,
                "vep_binary_sha256": "c" * 64,
                "fasta": "/resources/GRCh38.fa",
                "fasta_sha256": "e" * 64,
                "vep_version": "115.2",
                "tool_profile_id": "vep-115.2-contract-test",
                "platform": current_platform_id(),
                "qualification_status": "SOFTWARE_QUALIFIED",
                "runtime_image_digest": "sha256:" + "d" * 64,
                "runtime_path": ["/usr/bin", "/bin"],
                "runtime_environment": {"PERL5LIB": "/opt/vep/modules", "PERL_HASH_SEED": "0", "PERL_PERTURB_KEYS": "0"},
                "execution_timeout_seconds": 1800,
                "max_output_bytes": 65536,
                "scratch_root": str(settings.worker_scratch_root),
            },
        )
    )


def test_vep_normalization_preserves_transcript_and_variant_level_consequences():
    variant = CanonicalVariant(
        genome_build="GRCh38",
        chromosome="1",
        position=100,
        reference="A",
        alternate="G",
    )
    transcript = {
        "transcript_id": "ENST000001.1",
        "gene_id": "ENSG000001",
        "gene_symbol": "GENE1",
        "consequence_terms": ["missense_variant"],
        "mane_select": "NM_000001.1",
        "canonical": 1,
        "hgvsc": "ENST000001.1:c.100A>G",
        "hgvsp": "ENSP000001.1:p.Lys34Arg",
        "biotype": "protein_coding",
        "protein_id": "ENSP000001.1",
    }
    record = {
        "input": "1 100 SIRALOOM_0 A G . PASS .",
        "start": 100,
        "seq_region_name": "1",
        "allele_string": "A/G",
        "assembly_name": "GRCh38",
        "variant_class": "SNV",
        "most_severe_consequence": "missense_variant",
        "transcript_consequences": [transcript],
        "intergenic_consequences": [],
        "regulatory_feature_consequences": [{"regulatory_feature_id": "ENSR000001"}],
        "motif_feature_consequences": [{"motif_feature_id": "ENSM000001"}],
        "colocated_variants": [{"id": "rs123", "allele_string": "A/G"}],
    }
    result = _provider().normalize_result(
        ProviderRawResult("annotate", [record], "d" * 64, {}),
        inputs={"variants": [variant], "genome_build": "GRCh38"},
    )
    raw = result.observations[0]
    normalized = normalize_annotation_payload("VEP", raw)

    assert raw["selected_transcript"] == transcript
    assert normalized["transcript_details"] == transcript
    assert normalized["transcript_consequences"] == [transcript]
    assert normalized["hgvs_consequences"] == [transcript]
    assert normalized["most_severe_consequence"] == "missense_variant"
    assert normalized["genomic"]["assembly_name"] == "GRCh38"
    assert normalized["genomic"]["variant_class"] == "SNV"
    assert normalized["noncoding_consequences"]["regulatory_features"] == [
        {"regulatory_feature_id": "ENSR000001"}
    ]
    assert normalized["noncoding_consequences"]["motif_features"] == [
        {"motif_feature_id": "ENSM000001"}
    ]
    assert normalized["colocated_variants"] == [
        {"id": "rs123", "allele_string": "A/G"}
    ]
    assert normalized["annotation_completeness"] == {
        "transcript_selection_status": "SELECTED_MANE_SELECT",
        "transcript_consequence_count": 1,
        "intergenic_consequence_count": 0,
        "regulatory_feature_consequence_count": 1,
        "motif_feature_consequence_count": 1,
    }
    assert normalized["provenance"]["provider_field_schema"] == (
        "vep-json-variant-consequence-v2"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("consequences", [None]),
        ("intergenic_consequences", "missense_variant"),
        ("regulatory_feature_consequences", [{} , None]),
        ("motif_feature_consequences", {"feature": "invalid"}),
        ("colocated_variants", ["rs123"]),
    ],
)
def test_vep_normalizer_rejects_malformed_consequence_collections(field, value):
    with pytest.raises(ValueError, match="VEP"):
        normalize_annotation_payload("VEP", {field: value})


def test_vep_normalizer_preserves_unresolved_transcript_selection_without_guessing():
    normalized = normalize_annotation_payload(
        "VEP",
        {
            "consequences": [
                {"transcript_id": "ENST000001.1", "consequence_terms": ["missense_variant"]}
            ],
            "transcript": None,
            "selected_transcript": None,
            "transcript_selection": {
                "status": "AMBIGUOUS_CANONICAL",
                "policy": "UNIQUE_MANE_SELECT_THEN_UNIQUE_CANONICAL",
                "selected_transcript_id": None,
            },
        },
    )

    assert normalized["transcript"] is None
    assert normalized["transcript_details"] is None
    assert normalized["transcript_selection"]["status"] == "AMBIGUOUS_CANONICAL"
    assert normalized["annotation_completeness"]["transcript_selection_status"] == (
        "AMBIGUOUS_CANONICAL"
    )
    assert normalized["transcript_consequences"][0]["transcript_id"] == "ENST000001.1"



def test_vep_rejects_duplicate_annotation_records_for_one_requested_allele():
    variant = CanonicalVariant(
        genome_build="GRCh38",
        chromosome="1",
        position=100,
        reference="A",
        alternate="G",
    )
    record = {
        "input": "1 100 SIRALOOM_0 A G . PASS .",
        "start": 100,
        "seq_region_name": "1",
        "allele_string": "A/G",
        "transcript_consequences": [],
    }

    with pytest.raises(VEPProviderError, match="more than one annotation record"):
        _provider().normalize_result(
            ProviderRawResult("annotate", [record, record], "d" * 64, {}),
            inputs={"variants": [variant], "genome_build": "GRCh38"},
        )


def test_vep_rejects_unrequested_annotation_records_instead_of_dropping_them():
    variant = CanonicalVariant(
        genome_build="GRCh38",
        chromosome="1",
        position=100,
        reference="A",
        alternate="G",
    )
    requested_record = {
        "input": "1 100 SIRALOOM_0 A G . PASS .",
        "start": 100,
        "seq_region_name": "1",
        "allele_string": "A/G",
        "transcript_consequences": [],
    }
    unrequested_record = {
        "input": "1 200 SIRALOOM_1 C T . PASS .",
        "start": 200,
        "seq_region_name": "1",
        "allele_string": "C/T",
        "transcript_consequences": [],
    }

    with pytest.raises(VEPProviderError, match="outside the requested batch"):
        _provider().normalize_result(
            ProviderRawResult(
                "annotate",
                [requested_record, unrequested_record],
                "d" * 64,
                {},
            ),
            inputs={"variants": [variant], "genome_build": "GRCh38"},
        )


def test_vep_rejects_duplicate_normalized_alleles_in_the_input_batch():
    variant = CanonicalVariant(
        genome_build="GRCh38",
        chromosome="1",
        position=100,
        reference="A",
        alternate="G",
    )
    record = {
        "start": 100,
        "seq_region_name": "1",
        "allele_string": "A/G",
        "transcript_consequences": [],
    }

    with pytest.raises(VEPProviderError, match="input batch contains duplicate"):
        _provider().normalize_result(
            ProviderRawResult("annotate", [record], "d" * 64, {}),
            inputs={"variants": [variant, variant], "genome_build": "GRCh38"},
        )


def test_vep_reconciliation_uses_original_vcf_input_for_indel_identity():
    variant = CanonicalVariant(
        genome_build="GRCh38",
        chromosome="1",
        position=100,
        reference="A",
        alternate="AT",
    )
    shifted_provider_record = {
        # VEP consequence coordinates/allele representation can differ from
        # the exact normalized VCF input for indels; the input field is lineage.
        "input": "1 100 SIRALOOM_0 A AT . PASS .",
        "start": 101,
        "seq_region_name": "1",
        "allele_string": "-/T",
        "transcript_consequences": [],
    }

    result = _provider().normalize_result(
        ProviderRawResult("annotate", [shifted_provider_record], "d" * 64, {}),
        inputs={"variants": [variant], "genome_build": "GRCh38"},
    )

    assert result.observations[0]["pos"] == 100
    assert result.observations[0]["ref"] == "A"
    assert result.observations[0]["alt"] == "AT"
