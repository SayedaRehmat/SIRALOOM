from backend.app.adapters.annotation.genebe_normalizer import gene_be_display_payload, normalize_gene_be_variant

def test_gene_be_normalization_preserves_provider_acmg():
    raw = {"chr":"17","pos":43000000,"ref":"C","alt":"T","gene_symbol":"BRCA1","frequency_reference_population":0.0001,"clinvar_classification":"Pathogenic","acmg_criteria":"PM2,PP3","acmg_classification":"Likely pathogenic"}
    out = normalize_gene_be_variant(raw)
    assert out["gene"]["symbol"] == "BRCA1"
    assert out["population"]["reference_population_af"] is None
    assert out["population"]["reference_population_af_status"] == "DENOMINATOR_UNAVAILABLE"
    assert out["provider_acmg"]["classification"] == "Likely pathogenic"


def test_gene_be_af_without_denominator_is_not_normalized_or_displayed():
    raw = {
        "frequency_reference_population": 0.0001,
        "gnomad_exomes_af": 0.0002,
        "gnomad_genomes_af": 0.0003,
        "allele_count_reference_population": 2,
    }
    normalized = normalize_gene_be_variant(raw)
    persisted = {"raw": raw, "normalized": normalized}
    shown = gene_be_display_payload(persisted)
    assert persisted["raw"]["frequency_reference_population"] == 0.0001
    assert shown["raw"]["frequency_reference_population"] is None
    assert shown["raw"]["gnomad_exomes_af"] is None
    assert shown["raw"]["gnomad_genomes_af"] is None
    assert shown["normalized"]["population"]["reference_population_af"] is None
    assert shown["normalized"]["population"]["reference_population_ac"] == 2
