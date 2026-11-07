from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.acmg.assessment_service import ACMGSpecificationAssessmentService
from backend.app.acmg.evaluators import EvaluatorConfigurationError, evaluate_pp3_bp4
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    ACMGSourceAssertion,
    Analysis,
    Annotation,
    Classification,
    ClinGenSpecification,
    Evidence,
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
        reference_build="GRCh38", configuration={}, created_at=datetime.now(UTC)
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
                },
                "PP3": {
                    "predictor": "REVEL",
                    "minimum_score": 0.9,
                    "strength": "SUPPORTING",
                    "calibration": {
                        "calibration_id": "TEST-REVEL-CAL-1",
                        "model_version": "fixture-1",
                        "validation_dataset": "synthetic-unit-test-fixture",
                        "calibration_reference": "test-fixture"
                    }
                }
            }, raw_payload={}, retrieved_at=datetime.now(UTC),
            validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION"
        ))
        annotation = Annotation(
            id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
            provider_name="test", provider_version="1", resource_name="test",
            resource_version="1", payload={"normalized": {"gene": {"symbol": "GENE1"}, "computational": {"revel": 0.95}, "splice": {}}}
        )
        db.add(annotation)
        resource = Resource(
            id=uuid4(), name="gnomAD", provider="gnomAD", resource_type="POPULATION_FREQUENCY",
            version="4.x", genome_build="GRCh38", access_method="TEST", status="VALIDATED",
            population_definition={"level": "ANCESTRY", "code": "MID"}, metadata_json={}
        )
        db.add(resource); db.flush()
        observation_id = uuid4()
        db.add(PopulationObservation(
            id=observation_id, analysis_id=analysis.id, variant_id=variant.id, resource_id=resource.id,
            population_level="ANCESTRY", population_code="MID", population_label="Middle Eastern",
            allele_count=0, allele_number=5000, allele_frequency=0.0, homozygote_count=0,
            availability="AVAILABLE", quality_status="PASS"
        ))
        db.add(Evidence(
            id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
            evidence_type="POPULATION_FREQUENCY",
            statement="Configured population observation supports PM2 rarity assessment.",
            direction="PATHOGENIC", source_name="gnomAD", source_version="4.x",
            resource_id=resource.id, source_record_id="test-observation",
            observation_ids=[str(observation_id)], payload={},
            created_by_type="TEST", created_by_id="test",
            evidence_fingerprint=str(uuid4()),
        ))
        predictor_evidence_id = uuid4()
        db.add(Evidence(
            id=predictor_evidence_id, analysis_id=analysis.id, variant_id=variant.id,
            evidence_type="COMPUTATIONAL",
            statement="REVEL predictor observation from the same annotation run.",
            direction="NEUTRAL", source_name="test", source_version="1",
            resource_id=None, source_record_id="revel-test",
            observation_ids=[], payload={"predictors": {"revel": 0.95}},
            created_by_type="TEST", created_by_id="test",
            evidence_fingerprint=str(uuid4()),
        ))
        db.commit()

        service = ACMGSpecificationAssessmentService()
        result = service.assess_variant(
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
        pp3 = next(x for x in result.evaluator_results if x.criterion == "PP3")
        assert pp3.status == "PROPOSED"
        assert pp3.evidence_ids == (str(predictor_evidence_id),)
        pp3_assessment = next(x for x in result.criterion_assessments if x.criterion == "PP3")
        assert pp3_assessment.evidence_ids == (str(predictor_evidence_id),)


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
                raw_payload={}, retrieved_at=datetime.now(UTC),
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
            raw_payload={}, retrieved_at=datetime.now(UTC),
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


def test_review_required_criterion_blocks_combination_and_persists_no_classification():
    engine = _db()
    with Session(engine) as db:
        case_id = uuid4()
        analysis = _analysis(case_id)
        variant = _variant()
        db.add_all([analysis, variant])
        db.add(ClinGenSpecification(
            id=uuid4(), specification_id="SPEC-MIXED", version="1.0", provider="ClinGen",
            framework="ACMG/AMP", gene_scope=["GENE1"], disease_scope=["Disease X"],
            criteria={
                "PM2": {
                    "max_allele_frequency": 0.0001,
                    "minimum_allele_number": 1000,
                    "population_level": "ANCESTRY",
                    "population_codes": ["MID"],
                    "strength": "SUPPORTING",
                },
                "PP3": {
                    "predictor": "REVEL",
                    "minimum_score": 0.9,
                    "strength": "SUPPORTING",
                },
            },
            raw_payload={}, retrieved_at=datetime.now(UTC),
            validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION",
        ))
        annotation = Annotation(
            id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
            provider_name="test", provider_version="1", resource_name="test",
            resource_version="1",
            payload={"normalized": {
                "gene": {"symbol": "GENE1"}, "computational": {}, "splice": {},
            }},
        )
        resource = Resource(
            id=uuid4(), name="Population fixture", provider="fixture",
            resource_type="POPULATION_FREQUENCY", version="test",
            genome_build="GRCh38", access_method="TEST", status="VALIDATED",
            population_definition={"level": "ANCESTRY", "code": "MID"},
            metadata_json={},
        )
        db.add_all([annotation, resource])
        db.flush()
        observation_id = uuid4()
        db.add(PopulationObservation(
            id=observation_id, analysis_id=analysis.id, variant_id=variant.id,
            resource_id=resource.id, population_level="ANCESTRY", population_code="MID",
            population_label="Middle Eastern", allele_count=0, allele_number=5000,
            allele_frequency=0.0, homozygote_count=0, availability="AVAILABLE",
            quality_status="PASS",
        ))
        db.add(Evidence(
            id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
            evidence_type="POPULATION_FREQUENCY", statement="Population observation",
            direction="NEUTRAL", source_name="fixture", source_version="test",
            resource_id=resource.id, source_record_id="fixture-record",
            observation_ids=[str(observation_id)], payload={},
            created_by_type="TEST", created_by_id="test", evidence_fingerprint=str(uuid4()),
        ))
        db.flush()

        service = ACMGSpecificationAssessmentService()
        result = service.assess_variant(
            db, analysis=analysis, variant=variant, annotation=annotation,
            population_rows=db.query(PopulationObservation).all(),
            resource_rows={resource.id: resource}, gene="GENE1", disease="Disease X",
        )

        assert result.status == "REQUIRES_REVIEW"
        assert result.classification is None
        assert [row.criterion for row in result.criterion_assessments] == ["PM2"]
        assert result.combination_metadata["review_reason"] == "CRITERION_EVIDENCE_REQUIRES_REVIEW"
        assert result.combination_metadata["criteria_requiring_review"][0]["criterion"] == "PP3"

        service.persist(db, analysis=analysis, variant=variant, result=result)
        db.commit()
        assert db.query(Classification).filter_by(
            analysis_id=analysis.id, variant_id=variant.id
        ).count() == 0
        persisted = {
            row.criterion: row.state
            for row in db.query(ACMGAssessment).filter_by(
                analysis_id=analysis.id, variant_id=variant.id
            ).all()
        }
        assert persisted == {"PM2": "PROPOSED", "PP3": "REQUIRES_REVIEW"}


def test_pvs1_candidate_requires_review_and_never_enters_automated_classification():
    engine = _db()
    with Session(engine) as db:
        analysis = _analysis(uuid4())
        variant = _variant()
        db.add_all([analysis, variant])
        db.add(ClinGenSpecification(
            id=uuid4(), specification_id="SPEC-PVS1", version="1.0",
            provider="ClinGen", framework="ACMG/AMP", gene_scope=["GENE1"],
            disease_scope=["Disease X"],
            criteria={"PVS1": {
                "lof_mechanism_established": True,
                "allowed_consequences": ["frameshift_variant"],
                "strength": "VERY_STRONG",
            }},
            raw_payload={}, retrieved_at=datetime.now(UTC),
            validated_for_automation=True,
            validation_status="APPROVED_FOR_AUTOMATION",
        ))
        annotation = Annotation(
            id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
            provider_name="fixture", provider_version="1", resource_name="fixture",
            resource_version="1", payload={"normalized": {
                "gene": {"symbol": "GENE1"},
                "effect": "frameshift_variant",
                "computational": {}, "splice": {},
            }},
        )
        db.add(annotation)
        db.commit()

        service = ACMGSpecificationAssessmentService()
        result = service.assess_variant(
            db, analysis=analysis, variant=variant, annotation=annotation,
            population_rows=[], resource_rows={}, gene="GENE1", disease="Disease X",
        )

        assert result.status == "REQUIRES_REVIEW"
        assert result.classification is None
        assert result.evaluator_results[0].criterion == "PVS1"
        assert result.evaluator_results[0].status == "REQUIRES_REVIEW"
        assert result.evaluator_results[0].strength is None
        assert result.combination_metadata["review_reason"] == "CRITERION_EVIDENCE_REQUIRES_REVIEW"

        service.persist(db, analysis=analysis, variant=variant, result=result)
        db.commit()
        assert db.query(Classification).filter_by(
            analysis_id=analysis.id, variant_id=variant.id
        ).count() == 0
        assessment = db.query(ACMGAssessment).filter_by(
            analysis_id=analysis.id, variant_id=variant.id, criterion="PVS1"
        ).one()
        assert assessment.state == "REQUIRES_REVIEW"
        assert assessment.automated_assessment["status"] == "REQUIRES_REVIEW"
        assert "decision tree" in assessment.automated_assessment["reason"]
        assert assessment.automated_assessment["metadata"]["review_reason"] == (
            "PVS1_DECISION_TREE_NOT_IMPLEMENTED"
        )


def test_same_persisted_evidence_cannot_be_counted_for_multiple_criteria():
    engine = _db()
    with Session(engine) as db:
        analysis = _analysis(uuid4())
        variant = _variant()
        specification = ClinGenSpecification(
            id=uuid4(), specification_id="SPEC-NO-DOUBLE-COUNT", version="1.0",
            provider="ClinGen", framework="ACMG/AMP", gene_scope=["GENE1"],
            disease_scope=["Disease X"],
            criteria={"PS1": {"strength": "STRONG"}, "PM5": {"strength": "MODERATE"}},
            raw_payload={}, retrieved_at=datetime.now(UTC),
            validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION",
        )
        annotation = Annotation(
            id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
            provider_name="fixture", provider_version="1", resource_name="fixture",
            resource_version="1", payload={"normalized": {"gene": {"symbol": "GENE1"}}},
        )
        evidence = Evidence(
            id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
            evidence_type="CLINICAL_ASSERTION", statement="One assertion source record",
            direction="PATHOGENIC", source_name="ClinGen", source_version="fixture",
            source_record_id="single-source-record", payload={},
            created_by_type="TEST", created_by_id="test", evidence_fingerprint=str(uuid4()),
        )
        db.add_all([analysis, variant, specification, annotation, evidence])
        db.flush()
        for criterion, strength in (("PS1", "STRONG"), ("PM5", "MODERATE")):
            db.add(ACMGSourceAssertion(
                id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
                evidence_id=evidence.id, criterion=criterion, status="MET", strength=strength,
                source_name="ClinGen", source_version="fixture", source_record_id="single-source-record",
                source_classification="PATHOGENIC", condition="Disease X", gene="GENE1",
                rationale="Both assertions point to the same persisted evidence record.",
                source_payload={}, assertion_fingerprint=str(uuid4()),
            ))
        db.commit()

        service = ACMGSpecificationAssessmentService()
        result = service.assess_variant(
            db, analysis=analysis, variant=variant, annotation=annotation,
            population_rows=[], resource_rows={}, gene="GENE1", disease="Disease X",
        )

        assert result.status == "REQUIRES_REVIEW"
        assert result.classification is None
        assert result.combination_metadata["review_reason"] == "EVIDENCE_REUSED_ACROSS_CRITERIA"
        assert result.combination_metadata["reused_evidence"] == [
            {"evidence_id": str(evidence.id), "criteria": ["PM5", "PS1"]}
        ]
        service.persist(db, analysis=analysis, variant=variant, result=result)
        db.commit()
        assert db.query(Classification).filter_by(
            analysis_id=analysis.id, variant_id=variant.id
        ).count() == 0
        assert {
            row.criterion for row in db.query(ACMGAssessment).filter_by(
                analysis_id=analysis.id, variant_id=variant.id
            ).all()
        } == {"PS1", "PM5"}


def test_retired_source_assertions_persist_review_disposition_without_classification():
    engine = _db()
    with Session(engine) as db:
        analysis = _analysis(uuid4())
        variant = _variant()
        specification = ClinGenSpecification(
            id=uuid4(), specification_id="SPEC-RETIRED", version="1.0",
            provider="ClinGen", framework="ACMG/AMP", gene_scope=["GENE1"],
            disease_scope=["Disease X"],
            criteria={
                "PP5": {"strength": "SUPPORTING"},
                "BP6": {"strength": "SUPPORTING"},
            },
            raw_payload={}, retrieved_at=datetime.now(UTC),
            validated_for_automation=True, validation_status="APPROVED_FOR_AUTOMATION",
        )
        annotation = Annotation(
            id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
            provider_name="fixture", provider_version="1", resource_name="fixture",
            resource_version="1", payload={"normalized": {"gene": {"symbol": "GENE1"}}},
        )
        db.add_all([analysis, variant, specification, annotation])
        db.flush()
        for criterion, classification in (("PP5", "PATHOGENIC"), ("BP6", "BENIGN")):
            evidence = Evidence(
                id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
                evidence_type="CLINICAL_ASSERTION", statement=f"Source assertion {criterion}",
                direction="NEUTRAL", source_name="ClinVar", source_version="fixture",
                source_record_id=f"record-{criterion}", payload={},
                created_by_type="TEST", created_by_id="test",
                evidence_fingerprint=str(uuid4()),
            )
            db.add(evidence)
            db.flush()
            db.add(ACMGSourceAssertion(
                id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
                evidence_id=evidence.id, criterion=criterion, status="MET",
                strength="SUPPORTING", source_name="ClinVar", source_version="fixture",
                source_record_id=f"record-{criterion}", source_classification=classification,
                condition="Disease X", gene="GENE1", rationale="Imported source criterion",
                source_payload={}, assertion_fingerprint=str(uuid4()),
            ))
        db.commit()

        service = ACMGSpecificationAssessmentService()
        result = service.assess_variant(
            db, analysis=analysis, variant=variant, annotation=annotation,
            population_rows=[], resource_rows={}, gene="GENE1", disease="Disease X",
        )
        assert result.status == "REQUIRES_REVIEW"
        assert result.classification is None
        assert {item.criterion for item in result.source_assessments} == {"PP5", "BP6"}
        assert all(item.status == "REQUIRES_REVIEW" for item in result.source_assessments)
        assert all(item.strength is None for item in result.source_assessments)

        service.persist(db, analysis=analysis, variant=variant, result=result)
        db.commit()
        service.persist(db, analysis=analysis, variant=variant, result=result)
        db.commit()

        rows = {
            row.criterion: row
            for row in db.query(ACMGAssessment).filter_by(
                analysis_id=analysis.id, variant_id=variant.id
            ).all()
        }
        assert set(rows) == {"PP5", "BP6"}
        for criterion, row in rows.items():
            assert row.state == "REQUIRES_REVIEW"
            assert row.automated_assessment["source_assessments"][0]["status"] == "REQUIRES_REVIEW"
            assert row.automated_assessment["source_assessments"][0]["metadata"][
                "retired_criterion"
            ] == criterion
            assert len(row.automated_assessment["source_assessments"]) == 1
        assert db.query(Classification).filter_by(
            analysis_id=analysis.id, variant_id=variant.id
        ).count() == 0



def test_pp3_requires_explicit_calibration_provenance():
    import pytest

    with pytest.raises(EvaluatorConfigurationError, match="calibration provenance"):
        evaluate_pp3_bp4(
            {"revel": 0.95},
            criterion="PP3",
            profile={
                "PP3": {
                    "predictor": "REVEL",
                    "minimum_score": 0.9,
                    "strength": "SUPPORTING",
                }
            },
            evidence_ids=("evidence-1",),
        )


def test_pp3_persists_calibration_provenance_in_result_metadata():
    result = evaluate_pp3_bp4(
        {"revel": 0.95},
        criterion="PP3",
        profile={
            "PP3": {
                "predictor": "REVEL",
                "minimum_score": 0.9,
                "strength": "SUPPORTING",
                "calibration": {
                    "calibration_id": "CAL-1",
                    "model_version": "1.2.3",
                    "validation_dataset": "known-answer-set-v1",
                    "calibration_reference": "DOI:10.0000/example",
                },
            }
        },
        evidence_ids=("evidence-1",),
    )
    assert result.status == "PROPOSED"
    assert result.metadata["calibration"] == {
        "calibration_id": "CAL-1",
        "model_version": "1.2.3",
        "validation_dataset": "known-answer-set-v1",
        "calibration_reference": "DOI:10.0000/example",
    }
