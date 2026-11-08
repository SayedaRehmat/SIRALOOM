from uuid import uuid4

import pytest

from backend.app.domain.evidence import evidence_fingerprint
from backend.app.domain.population import qualified_allele_frequency
from backend.app.evidence.engine import EvidenceContext, EvidenceEngine


def test_evidence_engine_builds_traceable_facts_without_final_classification():
    variant_id = uuid4()
    analysis_id = uuid4()
    observation_id = uuid4()
    engine = EvidenceEngine()
    records = engine.build_from_annotation(
        variant_id=variant_id,
        annotation={
            "gene": {"symbol": "BRCA1"},
            "transcript": {"accession": "NM_007294.4"},
            "effect": "missense_variant",
            "population": {"reference_population_af": 0.00001},
            "clinical": {
                "clinvar_classification": "Pathogenic",
                "clinvar_disease": "Example condition",
                "clinvar_review_status": "reviewed",
            },
            "computational": {"revel": 0.91},
            "splice": {"spliceai_max_score": 0.02},
            "provider_acmg": {"classification": "Pathogenic", "criteria": ["PM2"]},
        },
        provider_name="GeneBe",
        provider_version="test",
        resource_name="GeneBe",
        resource_version="test-resource",
        context=EvidenceContext(analysis_id=analysis_id),
        population_observations=[
            {
                "observation_id": observation_id,
                "resource_name": "gnomAD",
                "resource_version": "4.x",
                "population_code": "MID",
                "population_label": "Middle Eastern",
                "allele_count": 1,
                "allele_number": 100000,
                "allele_frequency": 0.00001,
                "homozygote_count": 0,
                "availability": "AVAILABLE",
                "quality_status": "PASS",
            }
        ],
    )

    types = {r.evidence_type for r in records}
    assert {"POPULATION", "PROVIDER_ASSERTION", "COMPUTATIONAL", "SPLICING", "CONSEQUENCE"} <= types
    assert any(r.source_name == "gnomAD" and r.source_version == "4.x" for r in records)
    assert any(str(observation_id) in {str(x) for x in r.observation_ids} for r in records)
    assert all(r.direction in {"SUPPORTS", "REFUTES", "NEUTRAL", "UNKNOWN"} for r in records)
    assert all(r.payload for r in records)
    clinvar_records = [r for r in records if r.payload.get("upstream_source") == "ClinVar"]
    assert len(clinvar_records) == 1
    assert clinvar_records[0].evidence_type == "PROVIDER_ASSERTION"
    assert clinvar_records[0].source_name == "GeneBe"
    assert clinvar_records[0].payload["direct_resource_execution"] is False


def test_conflicting_clinvar_is_neutral():
    engine = EvidenceEngine()
    records = engine.build_from_annotation(
        variant_id=uuid4(),
        annotation={"clinical": {"clinvar_classification": "Conflicting classifications of pathogenicity"}},
        provider_name="GeneBe",
        provider_version="test",
        resource_name="ClinVar via GeneBe",
        resource_version="test",
        context=EvidenceContext(analysis_id=uuid4()),
    )
    assert len(records) == 1
    assert records[0].evidence_type == "PROVIDER_ASSERTION"
    assert records[0].source_name == "ClinVar via GeneBe"
    assert records[0].payload["upstream_source"] == "ClinVar"
    assert records[0].payload["direct_resource_execution"] is False
    assert records[0].direction == "NEUTRAL"


def test_evidence_fingerprint_is_deterministic():
    v = uuid4()
    a = uuid4()
    kwargs = dict(
        variant_id=v,
        analysis_id=a,
        evidence_type="POPULATION",
        statement="observation",
        direction="NEUTRAL",
        source_name="gnomAD",
        source_version="4.x",
        observation_ids=tuple(),
        payload={"af": 0.1, "population": "MID"},
    )
    assert evidence_fingerprint(**kwargs) == evidence_fingerprint(**kwargs)


def test_population_no_match_snapshot_does_not_become_frequency_evidence():
    engine = EvidenceEngine()
    records = engine.build_from_annotation(
        variant_id=uuid4(),
        annotation={},
        provider_name="gnomAD",
        provider_version="graphql",
        resource_name="gnomAD release",
        resource_version="test-release",
        context=EvidenceContext(analysis_id=uuid4()),
        population_observations=[
            {
                "observation_id": uuid4(),
                "population_code": "GLOBAL_EXOMES",
                "availability": "NOT_FOUND",
                "allele_count": None,
                "allele_number": None,
                "allele_frequency": None,
                "homozygote_count": None,
            }
        ],
    )
    assert not any(record.evidence_type == "POPULATION" for record in records)


def test_population_frequency_requires_positive_allele_number():
    engine = EvidenceEngine()
    records = engine.build_from_annotation(
        variant_id=uuid4(),
        annotation={"population": {"reference_population_af": 0.01, "reference_population_ac": 1}},
        provider_name="GeneBe", provider_version="test", resource_name="GeneBe",
        resource_version="test", context=EvidenceContext(analysis_id=uuid4()),
        population_observations=[
            {"population_code": "NO_AN", "availability": "AVAILABLE", "allele_frequency": 0.01, "allele_count": 1, "allele_number": None},
            {"population_code": "ZERO_AN", "availability": "AVAILABLE", "allele_frequency": 0.01, "allele_count": 1, "allele_number": 0},
        ],
    )
    population_records = [record for record in records if record.evidence_type == "POPULATION"]
    assert population_records
    assert all(record.payload["allele_frequency"] is None for record in population_records)


@pytest.mark.parametrize("invalid_allele_number", [10.5, True, "10"])
def test_population_evidence_does_not_coerce_invalid_allele_number(
    invalid_allele_number,
):
    engine = EvidenceEngine()
    records = engine.build_from_annotation(
        variant_id=uuid4(),
        annotation={},
        provider_name="test",
        provider_version="1",
        resource_name="test-population",
        resource_version="1",
        context=EvidenceContext(analysis_id=uuid4()),
        population_observations=[
            {
                "availability": "AVAILABLE",
                "allele_count": 1,
                "allele_number": invalid_allele_number,
                "allele_frequency": 0.1,
            }
        ],
    )

    population = next(record for record in records if record.evidence_type == "POPULATION")
    assert population.payload["allele_number"] is None
    assert population.payload["allele_frequency"] is None


@pytest.mark.parametrize("invalid_allele_number", [10.5, True, "10"])
def test_annotation_population_evidence_does_not_coerce_invalid_allele_number(
    invalid_allele_number,
):
    records = EvidenceEngine().build_from_annotation(
        variant_id=uuid4(),
        annotation={
            "population": {
                "reference_population_an": invalid_allele_number,
                "reference_population_ac": 1,
                "reference_population_af": 0.1,
            }
        },
        provider_name="test",
        provider_version="1",
        resource_name="test-population",
        resource_version="1",
        context=EvidenceContext(analysis_id=uuid4()),
    )

    population = next(record for record in records if record.evidence_type == "POPULATION")
    assert population.payload["allele_number"] is None
    assert population.payload["allele_frequency"] is None


def test_display_allele_frequency_requires_valid_positive_denominator():
    assert qualified_allele_frequency(0.0, 10) == 0.0
    assert qualified_allele_frequency(0.01, None) is None
    assert qualified_allele_frequency(0.01, 0) is None
    assert qualified_allele_frequency(0.01, -1) is None
    assert qualified_allele_frequency(0.01, 10.5) is None
    assert qualified_allele_frequency(0.01, True) is None
    assert qualified_allele_frequency("0.01", 10) is None
    assert qualified_allele_frequency(True, 10) is None
    assert qualified_allele_frequency(float("nan"), 10) is None


def test_direct_clinvar_evidence_preserves_release_scv_and_rcv_identity():
    from types import SimpleNamespace

    engine = EvidenceEngine()
    assertion = SimpleNamespace(
        record_type="SCV",
        accession="SCV000000001",
        version="4",
        variation_id="12345",
        rcv_accessions=("RCV000000001.2", "RCV000000002.7"),
        genome_build="GRCh38",
        chromosome="1",
        position=100,
        reference="A",
        alternate="G",
        classification="Pathogenic",
        review_status="criteria provided, single submitter",
        condition="Example disease",
        submitter="Example submitter",
        assertion_method="Example criteria",
        record_sha256="b" * 64,
        payload={"vcv": {"accession": "VCV000000001", "version": "3", "variation_id": "12345"}},
    )
    resource_id = uuid4()
    records = engine.build_from_clinvar_assertions(
        variant_id=uuid4(),
        assertions=[assertion],
        resource_id=resource_id,
        resource_name="ClinVar VCV Release",
        resource_version="2026-09",
        request_fingerprint="c" * 64,
        execution_metadata={"contract_hash": "d" * 64},
    )

    assert len(records) == 1
    record = records[0]
    assert record.evidence_type == "CLINICAL_DATABASE"
    assert record.source_name == "ClinVar VCV Release"
    assert record.source_version == "2026-09"
    assert record.resource_id == resource_id
    assert record.source_record_id == "SCV:SCV000000001.4"
    assert record.request_fingerprint == "c" * 64
    assert record.response_sha256 == "b" * 64
    assert record.payload["variation_id"] == "12345"
    assert record.payload["rcv_accessions"] == ["RCV000000001.2", "RCV000000002.7"]
    assert record.payload["vcv"]["accession"] == "VCV000000001"
    assert record.payload["interpretive_use"] == "DIRECT_CLINVAR_RELEASE_EVIDENCE_REQUIRES_REVIEW"


def test_phenotype_prioritization_becomes_neutral_reviewable_evidence():
    engine = EvidenceEngine()
    records = engine.build_from_phenotype_prioritization(
        variant_id=uuid4(),
        prioritization={
            "method": "HPOA_EXACT_AND_IS_A_CONTEXT_ORDER_V1",
            "clinical_prioritization_validated": False,
            "human_review_required": True,
            "candidates": [
                {
                    "gene": "GENE1",
                    "disease_id": "MONDO:0000001",
                    "disease_name": "Example disease",
                    "contextual_order": 1,
                    "matched_patient_term_count": 2,
                    "matched_terms": [{"patient_hpo_id": "HP:0000001", "patient_observation_ids": ["obs-1"]}],
                    "potential_discordances": [],
                    "unmatched_present_patient_terms": [],
                    "association_validity": "STRONG",
                    "molecular_mechanism": "loss_of_function",
                    "inheritance": {
                        "modes": ["AUTOSOMAL_RECESSIVE"],
                        "penetrance": {"status": "UNKNOWN"},
                        "qualification_status": "REQUIRES_INDEPENDENT_QUALIFICATION",
                    },
                    "association_provenance": {
                        "resource_id": "00000000-0000-0000-0000-000000000001",
                        "resource_version": "2026-10",
                        "source_record_id": "GENE1:MONDO:0000001",
                        "resource_sha256": "a" * 64,
                    },
                    "hpoa_provenance": {
                        "resource_id": "00000000-0000-0000-0000-000000000002",
                        "resource_release": "2026-09-02",
                        "resource_sha256": "b" * 64,
                        "ontology_release": "2026-09-01",
                        "ontology_sha256": "c" * 64,
                    },
                }
            ],
        },
    )
    assert [record.evidence_type for record in records] == ["PHENOTYPE", "GENE_DISEASE"]
    assert all(record.direction == "NEUTRAL" for record in records)
    assert records[0].payload["contextual_order"] == 1
    assert records[0].payload["clinical_prioritization_validated"] is False
    assert records[1].source_record_id == "GENE1:MONDO:0000001"
    assert records[1].payload["molecular_mechanism"] == "loss_of_function"


def test_phenotype_prioritization_evidence_rejects_unreviewed_or_classification_like_payload():
    engine = EvidenceEngine()
    with pytest.raises(Exception, match="explicitly unvalidated"):
        engine.build_from_phenotype_prioritization(
            variant_id=uuid4(),
            prioritization={
                "clinical_prioritization_validated": True,
                "human_review_required": True,
                "candidates": [],
            },
        )
