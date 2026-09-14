from uuid import uuid4
from backend.app.phenotype import match_hpo, normalize_hpo_id
from backend.app.evidence.engine import EvidenceEngine

def test_hpo_validation_and_exact_matching():
    assert normalize_hpo_id("hp:0001250") == "HP:0001250"
    result = match_hpo(["HP:0001250", "HP:0001263"], ["HP:0001250", "HP:0000707"])
    assert result.matched == ("HP:0001250",)
    assert result.score == 0.5

def test_hpo_gene_disease_context_produces_match_metadata_without_pathogenicity():
    engine = EvidenceEngine()
    records = engine.build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=[{"hpo_id":"HP:0001250", "label":"Seizure"}],
        gene="GENE1",
        gene_disease_records=[{"gene":"GENE1", "disease":"Example disorder", "source_name":"ClinGen", "hpo_terms":["HP:0001250", "HP:0000707"]}],
        literature_records=[{"gene":"GENE1", "disease":"Example disorder", "title":"Example paper", "evidence_summary":"Reported affected individuals with the variant.", "source_id":"PMID:123"}],
    )
    types={r.evidence_type for r in records}
    assert {"PHENOTYPE","GENE_DISEASE","LITERATURE"} == types
    gd=next(r for r in records if r.evidence_type=="GENE_DISEASE")
    assert gd.payload["phenotype_match"]["score"] == 1.0
    assert gd.direction == "NEUTRAL"
    lit=next(r for r in records if r.evidence_type=="LITERATURE")
    assert lit.payload["source_id"] == "PMID:123"

def test_nonmatching_gene_disease_record_is_not_attached():
    records=EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(), case_hpo_terms=["HP:0001250"], gene="GENE1",
        gene_disease_records=[{"gene":"GENE2","disease":"Other"}],
        literature_records=[{"gene":"GENE2","title":"Other","evidence_summary":"Other"}],
    )
    assert records == [] or all(r.payload.get("gene") != "GENE2" for r in records)
