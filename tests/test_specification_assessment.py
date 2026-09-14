from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.acmg.assessment_service import ACMGSpecificationAssessmentService
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Annotation,
    ClinGenSpecification,
    PopulationObservation,
    Resource,
    Variant,
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _analysis(case_id):
    return Analysis(
        id=uuid4(), case_id=case_id, analysis_type="VARIANT_INTERPRETATION",
        workflow_id="variant-v1", workflow_version="1.0", status="RUNNING",
        reference_build="GRCh38", configuration={}, created_at=datetime.now(timezone.utc)
    )


def _variant():
    return Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="1", position=100,
        reference="A", alternate="G", normalization_status="NORMALIZED",
        canonical_key="GRCh38:1:100:A:G", identifiers={}
    )


def test_selection_and_evaluation_use_selected_clingen_specification():
    engine = _db()
    with Session(engine) as db:
        case_id = uuid4(); analysis = _analysis(case_id); variant = _variant()
        db.add(analysis); db.add(variant)
        db.add(ClinGenSpecification(
            id=uuid4(), specification_id="SPEC-A", version="1.2", provider="ClinGen",
            framework="ACMG/AMP", gene_scope=["GENE1"], disease_scope=["Disease X"],
            criteria={
                "PM2": {
                    "max_allele_frequency": 0.0001,
                    "minimum_allele_number": 1000,
                    "population_level": "ANCESTRY",
                    "population_codes": ["MID"],
                    "strength": "MODERATE"
                }
            }, raw_payload={}, retrieved_at=datetime.now(timezone.utc),
            validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION"
        ))
        annotation = Annotation(
            id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
            provider_name="test", provider_version="1", resource_name="test",
            resource_version="1", payload={"normalized": {"gene": {"symbol": "GENE1"}, "computational": {}, "splice": {}}}
        )
        db.add(annotation)
        resource = Resource(
            id=uuid4(), name="gnomAD", provider="gnomAD", resource_type="POPULATION_FREQUENCY",
            version="4.x", genome_build="GRCh38", access_method="TEST", status="VALIDATED",
            population_definition={"level": "ANCESTRY", "code": "MID"}, metadata_json={}
        )
        db.add(resource); db.flush()
        db.add(PopulationObservation(
            id=uuid4(), analysis_id=analysis.id, variant_id=variant.id, resource_id=resource.id,
            population_level="ANCESTRY", population_code="MID", population_label="Middle Eastern",
            allele_count=0, allele_number=5000, allele_frequency=0.0, homozygote_count=0,
            availability="AVAILABLE", quality_status="PASS"
        ))
        db.commit()

        result = ACMGSpecificationAssessmentService().assess_variant(
            db, analysis=analysis, variant=variant, annotation=annotation,
            population_rows=db.query(PopulationObservation).all(),
            resource_rows={resource.id: resource}, gene="GENE1", disease="Disease X"
        )
        assert result.binding.status == "SELECTED"
        assert result.binding.specification_id == "SPEC-A"
        assert result.status == "PROPOSED"
        assert result.classification is not None
        assert result.classification.classification == "VUS"
        assert any(x.criterion == "PM2" and x.applicable for x in result.evaluator_results)


def test_ambiguous_specification_stops_before_automation():
    engine = _db()
    with Session(engine) as db:
        case_id = uuid4(); analysis = _analysis(case_id); variant = _variant()
        db.add(analysis); db.add(variant)
        for sid in ("SPEC-A", "SPEC-B"):
            db.add(ClinGenSpecification(
                id=uuid4(), specification_id=sid, version="1", provider="ClinGen",
                framework="ACMG/AMP", gene_scope=["GENE1"], disease_scope=["Disease X"],
                criteria={"PM2": {"max_allele_frequency": 0.0001, "minimum_allele_number": 1000}},
                raw_payload={}, retrieved_at=datetime.now(timezone.utc),
                validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION"
            ))
        db.commit()
        result = ACMGSpecificationAssessmentService().assess_variant(
            db, analysis=analysis, variant=variant,
            annotation=Annotation(
                id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
                provider_name="test", provider_version="1", resource_name="test", resource_version="1",
                payload={"normalized": {"gene": {"symbol": "GENE1"}, "computational": {}, "splice": {}}}
            ), population_rows=[], resource_rows={}, gene="GENE1", disease="Disease X"
        )
        assert result.binding.status == "AMBIGUOUS"
        assert result.classification is None
        assert result.status == "AMBIGUOUS"


def test_alternative_combination_method_fails_closed():
    engine = _db()
    with Session(engine) as db:
        case_id = uuid4(); analysis = _analysis(case_id); variant = _variant()
        db.add_all([analysis, variant])
        db.add(ClinGenSpecification(
            id=uuid4(), specification_id="SPEC-POINTS", version="1", provider="ClinGen",
            framework="ACMG/AMP", gene_scope=["GENE1"], disease_scope=["Disease X"],
            criteria={"combining_method": "POINT_BASED", "PM2": {"max_allele_frequency": 0.0001, "minimum_allele_number": 1000}},
            raw_payload={}, retrieved_at=datetime.now(timezone.utc),
            validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION"
        ))
        db.commit()
        ann = Annotation(
            id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
            provider_name="test", provider_version="1", resource_name="test", resource_version="1",
            payload={"normalized": {"gene": {"symbol": "GENE1"}, "computational": {}, "splice": {}}}
        )
        result = ACMGSpecificationAssessmentService().assess_variant(
            db, analysis=analysis, variant=variant, annotation=ann,
            population_rows=[], resource_rows={}, gene="GENE1", disease="Disease X"
        )
        assert result.status == "REQUIRES_REVIEW"
        assert result.classification is None
