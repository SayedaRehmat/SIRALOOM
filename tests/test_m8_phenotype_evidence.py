from uuid import uuid4
from backend.app.adapters.phenotype.hpoa import HPOADiseaseAnnotation
from backend.app.evidence.engine import EvidenceEngine
from backend.app.phenotype import match_hpo, normalize_hpo_id

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
    assert gd.payload["phenotype_match"]["status"] == "REQUIRES_REVIEW"
    assert gd.payload["phenotype_match"]["exact_overlap_score"] == 1.0
    assert "score" not in gd.payload["phenotype_match"]
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


def test_hpoa_assertions_are_provenance_bearing_context_not_a_score():
    variant_id = uuid4()
    resource_id = uuid4()
    annotation = HPOADiseaseAnnotation(
        disease_id="MONDO:0000001", disease_name="Example disease", qualifier="NOT",
        hpo_id="HP:0001250", reference="PMID:123", evidence="TAS", onset=None,
        frequency="0/2", sex=None, modifiers=(), aspect="P",
        biocuration=("HPO:curator[2026-01-01]",),
    )
    provenance = {
        "resource_id": str(resource_id), "resource_version": "2026-09-02",
        "request_fingerprint": "a" * 64, "response_sha256": "b" * 64,
    }
    records = EvidenceEngine().build_hpoa_disease_phenotype_evidence(
        variant_id=variant_id, gene="GENE1",
        gene_disease_records=[{"gene": "GENE1", "disease_id": "MONDO:0000001"}],
        annotations_by_disease={"MONDO:0000001": (annotation,)},
        provenance=provenance,
    )

    assert len(records) == 1
    record = records[0]
    assert record.variant_id == variant_id
    assert record.resource_id == resource_id
    assert record.source_name == "HPOA"
    assert record.source_version == "2026-09-02"
    assert record.direction == "NEUTRAL"
    assert record.payload["assertions"][0]["qualifier"] == "NOT"
    assert record.payload["assertions"][0]["frequency"] == "0/2"
    assert record.payload["score"] is None
    assert record.payload["clinical_prioritization_validated"] is False


def test_hpoa_assertions_are_scoped_to_matching_disease_gene():
    annotation = HPOADiseaseAnnotation(
        disease_id="MONDO:0000001", disease_name="Example disease", qualifier="",
        hpo_id="HP:0001250", reference="PMID:123", evidence="PCS", onset=None,
        frequency=None, sex=None, modifiers=(), aspect="P",
        biocuration=("HPO:curator[2026-01-01]",),
    )
    records = EvidenceEngine().build_hpoa_disease_phenotype_evidence(
        variant_id=uuid4(), gene="GENE1",
        gene_disease_records=[{"gene": "GENE2", "disease_id": "MONDO:0000001"}],
        annotations_by_disease={"MONDO:0000001": (annotation,)}, provenance={},
    )
    assert records == []
