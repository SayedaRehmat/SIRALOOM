import hashlib
from uuid import uuid4

from backend.app.adapters.phenotype.hpo_obo import HPOOboProvider
from backend.app.adapters.phenotype.hpoa import HPOADiseaseAnnotation
from backend.app.evidence.engine import EvidenceEngine
from backend.app.phenotype import match_hpo, normalize_hpo_id


def test_hpo_validation_and_exact_matching():
    assert normalize_hpo_id("hp:0001250") == "HP:0001250"
    result = match_hpo(["HP:0001250", "HP:0001263"], ["HP:0001250", "HP:0000707"])
    assert result.matched == ("HP:0001250",)
    assert result.query_count == 2
    assert result.target_count == 2
    assert not hasattr(result, "score")

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
    assert gd.payload["phenotype_match"]["matched_terms"] == ["HP:0001250"]
    assert "score" not in gd.payload["phenotype_match"]
    assert "exact_overlap_score" not in gd.payload["phenotype_match"]
    assert gd.direction == "NEUTRAL"
    lit=next(r for r in records if r.evidence_type=="LITERATURE")
    assert lit.payload["source_id"] == "PMID:123"


def test_hpo_case_context_marks_terms_unverified_without_pinned_ontology():
    records = EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=[
            {"hpo_id": "HP:0001250", "label": "Seizure"},
            {"hpo_id": "HP:0001263", "phenotype_status": "UNKNOWN"},
        ],
        gene="GENE1",
    )

    phenotype = next(record for record in records if record.evidence_type == "PHENOTYPE")
    assert phenotype.payload["term_validation_status"] == "REQUIRES_REVIEW"
    assert phenotype.payload["term_validation_reason"] == "PINNED_HPO_ONTOLOGY_UNAVAILABLE"
    assert phenotype.payload["unresolved_terms_require_review"] == [
        {"hpo_id": "HP:0001250", "status": "ONTOLOGY_UNAVAILABLE"},
        {"hpo_id": "HP:0001263", "status": "ONTOLOGY_UNAVAILABLE"},
    ]

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


def test_hpoa_patient_comparison_surfaces_limited_discordance_context(tmp_path):
    ontology_path = tmp_path / "hp.obo"
    ontology_path.write_text(
        "format-version: 1.2\n"
        "data-version: hp/releases/2026-09-01/hp.obo\n\n"
        "ontology: hp.obo\n\n"
        "[Term]\nid: HP:0000001\nname: Root\n\n"
        "[Term]\nid: HP:0000002\nname: Parent\nis_a: HP:0000001 ! Root\n\n"
        "[Term]\nid: HP:0000003\nname: Child\nis_a: HP:0000002 ! Parent\n\n"
        "[Term]\nid: HP:0000004\nname: Other finding\n\n"
        "[Term]\nid: HP:0000005\nname: Unknown finding\n",
        encoding="utf-8",
    )
    ontology = HPOOboProvider(
        ontology_path,
        expected_sha256=hashlib.sha256(ontology_path.read_bytes()).hexdigest(),
        expected_release="2026-09-01",
    )
    annotations = (
        HPOADiseaseAnnotation(
            disease_id="MONDO:0000001", disease_name="Example disease", qualifier="NOT",
            hpo_id="HP:0000002", reference="PMID:1", evidence="TAS", onset=None,
            frequency=None, sex=None, modifiers=(), aspect="P", biocuration=(),
        ),
        HPOADiseaseAnnotation(
            disease_id="MONDO:0000001", disease_name="Example disease", qualifier="",
            hpo_id="HP:0000003", reference="PMID:2", evidence="PCS", onset=None,
            frequency="0/3", sex=None, modifiers=(), aspect="P", biocuration=(),
        ),
        HPOADiseaseAnnotation(
            disease_id="MONDO:0000001", disease_name="Example disease", qualifier="",
            hpo_id="HP:0000003", reference="PMID:5", evidence="PCS", onset=None,
            frequency="HP:0040285", sex=None, modifiers=(), aspect="P", biocuration=(),
        ),
        HPOADiseaseAnnotation(
            disease_id="MONDO:0000001", disease_name="Example disease", qualifier="",
            hpo_id="HP:0000003", reference="PMID:6", evidence="PCS", onset=None,
            frequency="0%", sex=None, modifiers=(), aspect="P", biocuration=(),
        ),
        HPOADiseaseAnnotation(
            disease_id="MONDO:0000001", disease_name="Example disease", qualifier="",
            hpo_id="HP:0000004", reference="PMID:3", evidence="PCS", onset=None,
            frequency="1/2", sex=None, modifiers=(), aspect="P", biocuration=(),
        ),
        HPOADiseaseAnnotation(
            disease_id="MONDO:0000001", disease_name="Example disease", qualifier="",
            hpo_id="HP:0000003", reference="PMID:4", evidence="TAS", onset=None,
            frequency=None, sex=None, modifiers=(), aspect="I", biocuration=(),
        ),
    )
    records = EvidenceEngine().build_hpoa_disease_phenotype_evidence(
        variant_id=uuid4(),
        gene="GENE1",
        gene_disease_records=[{"gene": "GENE1", "disease_id": "MONDO:0000001"}],
        annotations_by_disease={"MONDO:0000001": annotations},
        provenance={"resource_version": "2026-09-02"},
        patient_hpo_terms=[
            {"hpo_id": "HP:0000003", "phenotype_status": "PRESENT"},
            {"hpo_id": "HP:0000004", "phenotype_status": "ABSENT"},
            {"hpo_id": "HP:0000005", "phenotype_status": "UNKNOWN"},
        ],
        hpo_ontology=ontology,
    )

    comparison = records[0].payload["patient_comparison"]
    assert comparison["method"] == "HPOA_ASSERTION_COMPARISON_V1"
    assert comparison["status"] == "REQUIRES_REVIEW"
    assert comparison["review_required"] is True
    assert comparison["ontology_release"] == "2026-09-01"
    assert comparison["non_phenotypic_assertions_skipped"] == 1
    assert comparison["score"] is None
    assert comparison["clinical_prioritization_validated"] is False
    assert comparison["classification_criterion"] is None
    assert [item["source_negative_semantics"] for item in comparison["potential_discordances"][:2]] == [
        ["SOURCE_NOT"], ["ZERO_OF_N_COHORT_OBSERVATION"]
    ]
    assert comparison["potential_discordances"][0]["type"] == "PATIENT_PRESENT_VS_SOURCE_NOT_ASSERTION"
    assert comparison["potential_discordances"][1]["type"] == "PATIENT_PRESENT_VS_ZERO_OF_N_FREQUENCY"
    assert comparison["potential_discordances"][1]["frequency"] == "0/3"
    assert comparison["potential_discordances"][2]["source_negative_semantics"] == [
        "HPO_FREQUENCY_EXCLUDED_0_PERCENT"
    ]
    assert comparison["potential_discordances"][2]["type"] == "PATIENT_PRESENT_VS_HPO_EXCLUDED_FREQUENCY"
    assert comparison["potential_discordances"][3]["source_negative_semantics"] == ["ZERO_PERCENT_FREQUENCY"]
    assert comparison["potential_discordances"][3]["type"] == "PATIENT_PRESENT_VS_ZERO_PERCENT_FREQUENCY"
    assert comparison["potential_discordances"][4]["type"] == "PATIENT_ABSENT_VS_DISEASE_ANNOTATED_FEATURE"
    assert comparison["patient_status_counts"]["UNKNOWN"] == 1


def test_hpoa_comparison_does_not_expand_a_broad_patient_term_to_a_specific_negative():
    class Ontology:
        release = "2026-09-01"
        sha256 = "a" * 64

        @staticmethod
        def resolve(hpo_id):
            from types import SimpleNamespace

            return SimpleNamespace(status="CURRENT", canonical_id=hpo_id)

        @staticmethod
        def ancestors(hpo_id):
            return {"HP:0000003": {"HP:0000002"}}.get(hpo_id, set())

    record = EvidenceEngine().build_hpoa_disease_phenotype_evidence(
        variant_id=uuid4(),
        gene="GENE1",
        gene_disease_records=[{"gene": "GENE1", "disease_id": "MONDO:0000001"}],
        annotations_by_disease={"MONDO:0000001": [{
            "hpo_id": "HP:0000003", "qualifier": "NOT", "aspect": "P",
            "reference": "PMID:1",
        }]},
        provenance={},
        patient_hpo_terms=[{"hpo_id": "HP:0000002", "phenotype_status": "PRESENT"}],
        hpo_ontology=Ontology(),
    )[0]

    comparison = record.payload["patient_comparison"]
    assert comparison["status"] == "COMPARISON_COMPLETE"
    assert comparison["potential_discordances"] == []


def test_hpoa_patient_comparison_requires_ontology_for_semantic_resolution():
    records = EvidenceEngine().build_hpoa_disease_phenotype_evidence(
        variant_id=uuid4(),
        gene="GENE1",
        gene_disease_records=[{"gene": "GENE1", "disease_id": "MONDO:0000001"}],
        annotations_by_disease={
            "MONDO:0000001": [{
                "hpo_id": "HP:0000001", "qualifier": "NOT", "aspect": "P",
                "reference": "PMID:1",
            }]
        },
        provenance={},
        patient_hpo_terms=[{"hpo_id": "HP:0000001", "phenotype_status": "PRESENT"}],
    )

    comparison = records[0].payload["patient_comparison"]
    assert comparison["status"] == "REQUIRES_REVIEW"
    assert comparison["reason"] == "PINNED_HPO_ONTOLOGY_UNAVAILABLE"
    assert comparison["potential_discordances"] == []


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
