from backend.app.adapters.annotation.genebe_normalizer import normalize_gene_be_variant

def test_gene_be_normalization_preserves_provider_acmg():
    raw = {"chr":"17","pos":43000000,"ref":"C","alt":"T","gene_symbol":"BRCA1","frequency_reference_population":0.0001,"clinvar_classification":"Pathogenic","acmg_criteria":"PM2,PP3","acmg_classification":"Likely pathogenic"}
    out = normalize_gene_be_variant(raw)
    assert out["gene"]["symbol"] == "BRCA1"
    assert out["population"]["reference_population_af"] == 0.0001
    assert out["provider_acmg"]["classification"] == "Likely pathogenic"
