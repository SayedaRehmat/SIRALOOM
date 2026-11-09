from backend.app.domain.gene_disease_reconciliation import (
    DimensionStatus, GeneDiseaseSource, GeneDiseaseSourceAssertion,
    GeneIdentifierNamespace, ReconciliationStatus, reconcile_gene_disease_assertions,
)

SHA = "a" * 64

def assertion(source, record, *, symbol="GENE1", hgnc=None, mondo="MONDO:0000001",
              validity=None, allelic=None, modes=(), mechanism=None, penetrance=None):
    return GeneDiseaseSourceAssertion(
        source=source, source_record_id=record, gene_symbol=symbol, hgnc_id=hgnc,
        mondo_id=mondo, resource_id="resource-1", resource_name=source.value,
        resource_version="2026-11-08", resource_sha256=SHA,
        raw_assertion={"untouched": [1, 2]}, validity=validity,
        allelic_requirement=allelic, inheritance_modes=tuple(modes),
        molecular_mechanism=mechanism, penetrance=penetrance,
    )

def test_exact_hgnc_and_mondo_pair_reconciles_and_preserves_raw_assertions():
    g = assertion(GeneDiseaseSource.G2P, "g2p:1", hgnc="HGNC:34", validity="Definitive",
                  allelic="biallelic_autosomal", modes=("AUTOSOMAL_RECESSIVE",), mechanism="loss_of_function")
    c = assertion(GeneDiseaseSource.CLINGEN_GDV, "clingen:1", hgnc="HGNC:34", validity="Definitive",
                  modes=("AUTOSOMAL_RECESSIVE",))
    result, = reconcile_gene_disease_assertions([c, g])
    assert result.status == ReconciliationStatus.MATCHED
    assert result.gene_identifier_namespace == GeneIdentifierNamespace.HGNC
    assert result.dimensions["validity"].status == DimensionStatus.AGREE
    assert result.dimensions["inheritance_mode"].status == DimensionStatus.AGREE
    assert result.dimensions["molecular_mechanism"].status == DimensionStatus.G2P_ONLY
    assert result.g2p_assertions[0].raw_assertion == {"untouched": [1, 2]}

def test_g2p_symbol_only_does_not_falsely_match_clingen_hgnc_identifier():
    g = assertion(GeneDiseaseSource.G2P, "g2p:1", symbol="ABCA4")
    c = assertion(GeneDiseaseSource.CLINGEN_GDV, "clingen:1", symbol="ABCA4", hgnc="HGNC:34")
    results = reconcile_gene_disease_assertions([g, c])
    assert {x.status for x in results} == {ReconciliationStatus.G2P_ONLY, ReconciliationStatus.CLINGEN_ONLY}
    assert all(x.requires_human_review for x in results)

def test_symbol_only_pair_is_explicitly_symbol_namespace_not_hgnc_match():
    g = assertion(GeneDiseaseSource.G2P, "g2p:1")
    c = assertion(GeneDiseaseSource.CLINGEN_GDV, "clingen:1")
    result, = reconcile_gene_disease_assertions([g, c])
    assert result.status == ReconciliationStatus.MATCHED
    assert result.gene_identifier_namespace == GeneIdentifierNamespace.SYMBOL
    assert "CANONICAL_HGNC_IDENTIFIER_INCOMPLETE" in result.review_reasons

def test_g2p_only_and_clingen_only_assertions_are_not_dropped():
    g = assertion(GeneDiseaseSource.G2P, "g2p:1", hgnc="HGNC:34", mondo="MONDO:0000001")
    c = assertion(GeneDiseaseSource.CLINGEN_GDV, "clingen:1", hgnc="HGNC:35", mondo="MONDO:0000002")
    results = reconcile_gene_disease_assertions([g, c])
    assert {x.status for x in results} == {ReconciliationStatus.G2P_ONLY, ReconciliationStatus.CLINGEN_ONLY}
    assert sum(len(x.g2p_assertions) + len(x.clingen_assertions) for x in results) == 2

def test_missing_mondo_and_missing_gene_identifier_are_retained_as_unmatchable():
    missing_mondo = assertion(GeneDiseaseSource.G2P, "g2p:no-mondo", mondo=None)
    missing_gene = assertion(GeneDiseaseSource.CLINGEN_GDV, "clingen:no-gene", symbol=None, hgnc=None)
    results = reconcile_gene_disease_assertions([missing_mondo, missing_gene])
    assert {x.status for x in results} == {
        ReconciliationStatus.UNMATCHABLE_MISSING_MONDO,
        ReconciliationStatus.UNMATCHABLE_IDENTIFIER_NAMESPACE,
    }

def test_conflicts_are_reported_independently_per_dimension():
    g = assertion(GeneDiseaseSource.G2P, "g2p:1", hgnc="HGNC:34", validity="Definitive",
                  modes=("AUTOSOMAL_RECESSIVE",), mechanism="loss_of_function")
    c = assertion(GeneDiseaseSource.CLINGEN_GDV, "clingen:1", hgnc="HGNC:34", validity="Limited",
                  modes=("AUTOSOMAL_DOMINANT",))
    result, = reconcile_gene_disease_assertions([g, c])
    assert result.dimensions["validity"].status == DimensionStatus.CONFLICT
    assert result.dimensions["inheritance_mode"].status == DimensionStatus.CONFLICT
    assert result.dimensions["molecular_mechanism"].status == DimensionStatus.G2P_ONLY
    assert "SOURCE_DIMENSION_CONFLICT" in result.review_reasons

def test_multiple_assertions_are_all_preserved_and_conflicting_values_not_collapsed():
    rows = [
        assertion(GeneDiseaseSource.CLINGEN_GDV, "c1", hgnc="HGNC:34", validity="Definitive"),
        assertion(GeneDiseaseSource.CLINGEN_GDV, "c2", hgnc="HGNC:34", validity="Limited"),
        assertion(GeneDiseaseSource.G2P, "g1", hgnc="HGNC:34", validity="Definitive"),
    ]
    result, = reconcile_gene_disease_assertions(rows)
    assert len(result.clingen_assertions) == 2
    assert result.dimensions["validity"].status == DimensionStatus.CONFLICT
    assert result.dimensions["validity"].clingen_values == ("definitive", "limited")

def test_penetrance_is_not_inferred_and_forces_separate_review():
    g = assertion(GeneDiseaseSource.G2P, "g1", hgnc="HGNC:34", penetrance="high")
    result, = reconcile_gene_disease_assertions([g])
    assert result.requires_human_review
    assert "PENETRANCE_REQUIRES_SEPARATE_SOURCE_POLICY" in result.review_reasons

def test_reconciliation_is_deterministic_and_input_order_independent():
    rows = [
        assertion(GeneDiseaseSource.G2P, "g1", hgnc="HGNC:34"),
        assertion(GeneDiseaseSource.CLINGEN_GDV, "c1", hgnc="HGNC:34"),
    ]
    a = reconcile_gene_disease_assertions(rows)
    b = reconcile_gene_disease_assertions(list(reversed(rows)))
    assert a == b
    assert a[0].reconciliation_id == b[0].reconciliation_id

def test_source_provenance_is_required():
    import pytest
    with pytest.raises(ValueError, match="SHA-256"):
        GeneDiseaseSourceAssertion(
            source=GeneDiseaseSource.G2P, source_record_id="g1", gene_symbol="G",
            hgnc_id=None, mondo_id="MONDO:0000001", resource_id=None,
            resource_name="G2P", resource_version="r1", resource_sha256="bad",
            raw_assertion={},
        )
