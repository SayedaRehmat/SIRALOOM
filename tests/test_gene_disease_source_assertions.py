from types import SimpleNamespace
from backend.app.domain.gene_disease_source_assertions import build_gene_disease_source_assertions
from backend.app.domain.gene_disease_reconciliation import ReconciliationStatus, reconcile_gene_disease_assertions


def test_provider_adapter_preserves_native_identifiers_and_raw_assertions():
    g2p = SimpleNamespace(source_record_id="G2P:1", gene_symbol="GENE1", disease_mondo="MONDO:0000001", raw={"Gene Symbol":"GENE1"}, allelic_requirement="biallelic_autosomal", inheritance_modes=("AUTOSOMAL_RECESSIVE",), molecular_mechanism="loss of function")
    clingen = SimpleNamespace(source_record_id="ClinGen-GDV:1", gene="GENE1", hgnc_id="HGNC:1", mondo_id="MONDO:0000001", payload={"GENE ID (HGNC)":"HGNC:1"}, classification="Definitive", moi="Autosomal recessive")
    items = build_gene_disease_source_assertions(g2p_models=[g2p], clingen_assertions=[clingen], g2p_resource_id="g2p", g2p_resource_name="G2P", g2p_resource_version="r1", g2p_resource_sha256="a"*64, clingen_resource_id="gdv", clingen_resource_name="ClinGen", clingen_resource_version="r2", clingen_resource_sha256="b"*64)
    assert items[0].hgnc_id is None and items[0].raw_assertion == g2p.raw
    assert items[1].hgnc_id == "HGNC:1" and items[1].raw_assertion == clingen.payload
    assert {x.status for x in reconcile_gene_disease_assertions(items)} == {ReconciliationStatus.G2P_ONLY, ReconciliationStatus.CLINGEN_ONLY}


def test_provider_adapter_retains_missing_mondo_g2p_assertion():
    g2p = SimpleNamespace(source_record_id="G2P:2", gene_symbol="GENE2", disease_mondo=None, raw={"Gene Symbol":"GENE2"}, allelic_requirement="biallelic_autosomal", inheritance_modes=("AUTOSOMAL_RECESSIVE",), molecular_mechanism="loss of function")
    items = build_gene_disease_source_assertions(g2p_models=[g2p], clingen_assertions=[], g2p_resource_id="g2p", g2p_resource_name="G2P", g2p_resource_version="r1", g2p_resource_sha256="a"*64, clingen_resource_id=None, clingen_resource_name=None, clingen_resource_version=None, clingen_resource_sha256=None)
    assert len(items) == 1 and items[0].mondo_id is None
    assert reconcile_gene_disease_assertions(items)[0].status == ReconciliationStatus.UNMATCHABLE_MISSING_MONDO
