from uuid import uuid4

from backend.app.domain.evidence import evidence_fingerprint
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
    assert {"POPULATION", "CLINICAL_DATABASE", "COMPUTATIONAL", "SPLICING", "CONSEQUENCE", "PROVIDER_ASSERTION"} <= types
    assert any(r.source_name == "gnomAD" and r.source_version == "4.x" for r in records)
    assert any(str(observation_id) in {str(x) for x in r.observation_ids} for r in records)
    assert all(r.direction in {"SUPPORTS", "REFUTES", "NEUTRAL", "UNKNOWN"} for r in records)
    assert all(r.payload for r in records)


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
    assert records[0].evidence_type == "CLINICAL_DATABASE"
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
