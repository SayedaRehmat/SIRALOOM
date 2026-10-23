from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.domain.evidence import evidence_fingerprint
from backend.app.domain.reanalysis import _copy_rows
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    ACMGSourceAssertion,
    Analysis,
    Annotation,
    Case,
    Evidence,
    InheritanceAssessment,
    Organization,
    PedigreeMember,
    PopulationObservation,
    Resource,
    SegregationObservation,
    User,
    Variant,
)


@pytest.mark.parametrize(
    ("earliest", "expected_counts"),
    [
        ("population", (1, 0, 0, 0)),
        ("build_evidence", (1, 1, 0, 0)),
        ("acmg_assessment", (1, 1, 1, 0)),
        ("reportability", (1, 1, 1, 1)),
    ],
)
def test_reanalysis_reuses_only_upstream_observations_with_exact_provenance(
    tmp_path, earliest, expected_counts
):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / (earliest + '-reuse.db')}")
    Base.metadata.create_all(engine)
    (
        organization_id, user_id, case_id, variant_id, resource_id, parent_id,
        child_id, population_observation_id, evidence_id,
    ) = (
        uuid4() for _ in range(9)
    )
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name="Reanalysis Provenance Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Reanalysis Provenance", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"REUSE-{earliest}-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.add(Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1",
                position=555, reference="T", alternate="C",
                normalization_status="NORMALIZED",
                canonical_key="GRCh38:1:555:T:C", identifiers={},
            ))
            db.add(Resource(
                id=resource_id, organization_id=organization_id,
                name="Pinned gnomAD release", provider="gnomAD",
                resource_type="POPULATION", version="v4.1",
                genome_build="GRCh38", access_method="API", license_text=None,
                checksum="a" * 64, location="https://fixture.invalid/gnomad",
                status="ACTIVE", population_definition={}, metadata_json={},
            ))
            db.flush()
            db.add(Analysis(
                id=parent_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="2.1",
                status="SUCCEEDED", queue_task_id=None, reference_build="GRCh38",
                configuration={}, started_at=None, completed_at=datetime.now(UTC),
                created_by=user_id, analysis_version=1,
            ))
            db.flush()
            db.add(Analysis(
                id=child_id, case_id=case_id, parent_analysis_id=parent_id,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="2.1",
                status="CREATED", queue_task_id=None, reference_build="GRCh38",
                configuration={}, started_at=None, completed_at=None,
                created_by=user_id, analysis_version=2,
            ))
            db.flush()

            db.add(Annotation(
                id=uuid4(), variant_id=variant_id, analysis_id=parent_id,
                provider_name="VEP", provider_version="115", resource_id=resource_id,
                resource_name="VEP cache", resource_version="115",
                request_fingerprint="annotation-request-sha256",
                response_sha256="annotation-response-sha256",
                request_metadata={"assembly": "GRCh38", "cache": "115"},
                observed_at=datetime.now(UTC), retry_count=0,
                payload={"consequence": "missense_variant"},
            ))
            db.add(PopulationObservation(
                id=population_observation_id, analysis_id=parent_id, variant_id=variant_id,
                resource_id=resource_id, population_level="GLOBAL",
                population_code="ALL", population_label="Global",
                allele_count=5, allele_number=1000, allele_frequency=0.005,
                homozygote_count=0, availability="AVAILABLE", quality_status="PASS",
                source_record_id="gnomad-record-1",
                request_fingerprint="population-request-sha256",
                response_sha256="population-response-sha256",
                request_metadata={"dataset": "v4.1"},
                observed_at=datetime.now(UTC),
            ))
            evidence = Evidence(
                id=evidence_id, variant_id=variant_id, analysis_id=parent_id,
                evidence_type="POPULATION", statement="Population frequency observation",
                direction="BENIGN", source_name="gnomAD", source_version="v4.1",
                resource_id=resource_id, source_record_id="gnomad-record-1",
                request_fingerprint="evidence-request-sha256",
                response_sha256="evidence-response-sha256",
                request_metadata={"dataset": "v4.1"},
                observed_at=datetime.now(UTC),
                observation_ids=[str(population_observation_id)],
                payload={
                    "allele_frequency": 0.005,
                    "criterion_assertions": [{
                        "code": "PM2", "status": "MET", "strength": "SUPPORTING",
                        "source": "ClinGen", "rationale": "Fixture source assertion",
                    }],
                }, created_by_type="SYSTEM",
                created_by_id="evidence-engine",
                evidence_fingerprint="evidence-fingerprint-v4.1",
            )
            db.add(evidence)
            db.flush()
            from backend.app.acmg.source_assertions import persist_clingen_source_assertions

            persist_clingen_source_assertions(db, evidence=evidence)
            db.add(ACMGAssessment(
                id=uuid4(), variant_id=variant_id, analysis_id=parent_id,
                framework_name="ACMG/AMP", framework_version="2015",
                specification_provider="ClinGen", specification_id="test-spec",
                specification_version="1", criterion="PM2",
                automated_assessment={
                    "status": "PROPOSED", "evidence_ids": [str(evidence_id)],
                },
                reviewed_assessment=None, final_assessment=None,
                state="DRAFT", review_version=0,
            ))
            db.commit()

            _copy_rows(db, parent_id, child_id, earliest)
            db.commit()

            counts = tuple(
                db.scalar(select(func.count(model.id)).where(
                    model.analysis_id == child_id
                ))
                for model in (Annotation, PopulationObservation, Evidence, ACMGAssessment)
            )
            assert counts == expected_counts

            copied_annotation = db.scalar(select(Annotation).where(Annotation.analysis_id == child_id))
            assert copied_annotation is not None
            assert copied_annotation.provider_version == "115"
            assert copied_annotation.resource_version == "115"
            assert copied_annotation.request_fingerprint == "annotation-request-sha256"
            assert copied_annotation.response_sha256 == "annotation-response-sha256"
            assert copied_annotation.payload == {"consequence": "missense_variant"}

            if expected_counts[1]:
                copied_population = db.scalar(select(PopulationObservation).where(
                    PopulationObservation.analysis_id == child_id
                ))
                assert copied_population.request_fingerprint == "population-request-sha256"
                assert copied_population.response_sha256 == "population-response-sha256"
                assert copied_population.allele_frequency == 0.005
            if expected_counts[2]:
                copied_evidence = db.scalar(select(Evidence).where(Evidence.analysis_id == child_id))
                copied_population = db.scalar(select(PopulationObservation).where(
                    PopulationObservation.analysis_id == child_id
                ))
                assert copied_evidence.observation_ids == [str(copied_population.id)]
                assert copied_evidence.source_version == "v4.1"
                assert copied_evidence.request_fingerprint == "evidence-request-sha256"
                assert copied_evidence.evidence_fingerprint == evidence_fingerprint(
                    variant_id=variant_id,
                    analysis_id=child_id,
                    evidence_type=copied_evidence.evidence_type,
                    statement=copied_evidence.statement,
                    direction=copied_evidence.direction,
                    source_name=copied_evidence.source_name,
                    source_version=copied_evidence.source_version,
                    observation_ids=(copied_population.id,),
                    payload=copied_evidence.payload,
                    resource_id=copied_evidence.resource_id,
                    source_record_id=copied_evidence.source_record_id,
                    request_fingerprint=copied_evidence.request_fingerprint,
                    response_sha256=copied_evidence.response_sha256,
                )
                copied_assertion = db.scalar(select(ACMGSourceAssertion).where(
                    ACMGSourceAssertion.analysis_id == child_id
                ))
                assert copied_assertion is not None
                assert copied_assertion.evidence_id == copied_evidence.id
                assert copied_assertion.assertion_fingerprint != db.scalar(
                    select(ACMGSourceAssertion.assertion_fingerprint).where(
                        ACMGSourceAssertion.analysis_id == parent_id
                    )
                )
            if expected_counts[3]:
                copied_assessment = db.scalar(select(ACMGAssessment).where(
                    ACMGAssessment.analysis_id == child_id
                ))
                copied_evidence = db.scalar(select(Evidence).where(Evidence.analysis_id == child_id))
                assert copied_assessment.automated_assessment["evidence_ids"] == [
                    str(copied_evidence.id)
                ]
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid_reference", ["evidence", "observation"])
def test_reanalysis_reuse_rejects_references_outside_parent_analysis(
    tmp_path, invalid_reference
):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'unowned-evidence.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, variant_id, parent_id, child_id = (
        uuid4() for _ in range(6)
    )
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name="Lineage Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Lineage Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"LINEAGE-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            db.add_all([
                Analysis(
                    id=parent_id, case_id=case_id, parent_analysis_id=None,
                    assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                    workflow_id="variant-v1", workflow_version="2.1",
                    status="SUCCEEDED", queue_task_id=None,
                    reference_build="GRCh38", configuration={}, started_at=None,
                    completed_at=datetime.now(UTC), created_by=user_id,
                    analysis_version=1,
                ),
                Analysis(
                    id=child_id, case_id=case_id, parent_analysis_id=parent_id,
                    assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                    workflow_id="variant-v1", workflow_version="2.1",
                    status="CREATED", queue_task_id=None,
                    reference_build="GRCh38", configuration={}, started_at=None,
                    completed_at=None, created_by=user_id, analysis_version=2,
                ),
                Variant(
                    id=variant_id, genome_build="GRCh38", chromosome="1",
                    position=555, reference="T", alternate="C",
                    normalization_status="NORMALIZED",
                    canonical_key="GRCh38:1:555:T:C", identifiers={},
                ),
            ])
            db.flush()
            evidence_id = uuid4()
            db.add(Evidence(
                id=evidence_id, variant_id=variant_id, analysis_id=parent_id,
                evidence_type="POPULATION", statement="Frequency evidence",
                direction="NEUTRAL", source_name="gnomAD", source_version="v4.1",
                request_metadata={},
                observation_ids=[str(uuid4())] if invalid_reference == "observation" else [],
                payload={},
                created_by_type="SYSTEM", created_by_id="evidence-engine",
                evidence_fingerprint="parent-evidence-fingerprint",
            ))
            db.add(ACMGAssessment(
                id=uuid4(), variant_id=variant_id, analysis_id=parent_id,
                framework_name="ACMG/AMP", framework_version="2015",
                specification_provider="ClinGen", specification_id="test-spec",
                specification_version="1", criterion="PM2",
                automated_assessment={
                    "evidence_ids": [
                        str(uuid4()) if invalid_reference == "evidence" else str(evidence_id)
                    ]
                },
                reviewed_assessment=None, final_assessment=None,
                state="DRAFT", review_version=0,
            ))
            db.commit()

            message = "evidence outside its parent analysis" if invalid_reference == "evidence" else "observation outside its parent analysis"
            with pytest.raises(ValueError, match=message):
                _copy_rows(db, parent_id, child_id, "reportability")
            db.rollback()
            assert db.scalar(select(func.count(Evidence.id)).where(
                Evidence.analysis_id == child_id
            )) == 0
    finally:
        engine.dispose()


def test_reanalysis_reuse_preserves_segregation_lineage_for_copied_evidence(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'segregation-lineage.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, variant_id, member_id, parent_id, child_id = (
        uuid4() for _ in range(7)
    )
    parent_observation_id = uuid4()
    parent_evidence_id = uuid4()
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name="Segregation Lineage Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Segregation Lineage", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"SEG-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            db.add_all([
                Analysis(
                    id=parent_id, case_id=case_id, parent_analysis_id=None,
                    assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                    workflow_id="variant-v1", workflow_version="2.1",
                    status="SUCCEEDED", queue_task_id=None,
                    reference_build="GRCh38", configuration={}, started_at=None,
                    completed_at=datetime.now(UTC), created_by=user_id,
                    analysis_version=1,
                ),
                Analysis(
                    id=child_id, case_id=case_id, parent_analysis_id=parent_id,
                    assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                    workflow_id="variant-v1", workflow_version="2.1",
                    status="CREATED", queue_task_id=None,
                    reference_build="GRCh38", configuration={}, started_at=None,
                    completed_at=None, created_by=user_id, analysis_version=2,
                ),
                Variant(
                    id=variant_id, genome_build="GRCh38", chromosome="1",
                    position=555, reference="T", alternate="C",
                    normalization_status="NORMALIZED",
                    canonical_key="GRCh38:1:555:T:C", identifiers={},
                ),
            ])
            db.flush()
            db.add(PedigreeMember(
                id=member_id, case_id=case_id, member_identifier="parent-1",
                relationship_to_proband="parent", sex="FEMALE",
                affected_status="UNAFFECTED", is_proband=False, sampled=True,
            ))
            db.flush()
            db.add(SegregationObservation(
                id=parent_observation_id, analysis_id=parent_id,
                variant_id=variant_id, pedigree_member_id=member_id,
                genotype="0/1", zygosity="HETEROZYGOUS", phase="UNKNOWN",
                allele_observed=None, phenotype_status="UNAFFECTED",
                source="HUMAN_REVIEW", notes="Parent sample reviewed",
                metadata_json={"review_source": "fixture"},
            ))
            db.add(InheritanceAssessment(
                id=uuid4(), analysis_id=parent_id, variant_id=variant_id,
                model="AUTOSOMAL_DOMINANT", status="INCONSISTENT", score=0,
                rationale="Segregation observation does not support the model",
                observation_fingerprint="segregation-observation-fingerprint",
                reviewer_note="Reviewed family genotype",
                created_by=str(user_id),
            ))
            db.add(Evidence(
                id=parent_evidence_id, variant_id=variant_id,
                analysis_id=parent_id, evidence_type="SEGREGATION",
                statement="Inheritance model AUTOSOMAL_DOMINANT: INCONSISTENT",
                direction="CONTEXTUAL", source_name="SIRALOOM Inheritance Engine",
                source_version="M10", request_metadata={},
                observation_ids=[str(parent_observation_id)],
                payload={"observation_fingerprint": "segregation-observation-fingerprint"},
                created_by_type="SYSTEM", created_by_id="inheritance",
                evidence_fingerprint="segregation-evidence-fingerprint",
            ))
            db.commit()

            _copy_rows(db, parent_id, child_id, "reportability")
            db.commit()

            child_observation = db.scalar(select(SegregationObservation).where(
                SegregationObservation.analysis_id == child_id
            ))
            child_assessment = db.scalar(select(InheritanceAssessment).where(
                InheritanceAssessment.analysis_id == child_id
            ))
            child_evidence = db.scalar(select(Evidence).where(
                Evidence.analysis_id == child_id,
                Evidence.evidence_type == "SEGREGATION",
            ))
            assert child_observation is not None
            assert child_observation.id != parent_observation_id
            assert child_observation.genotype == "0/1"
            assert child_assessment is not None
            assert child_assessment.observation_fingerprint == "segregation-observation-fingerprint"
            assert child_assessment.reviewer_note == "Reviewed family genotype"
            assert child_evidence is not None
            assert child_evidence.observation_ids == [str(child_observation.id)]
            assert child_evidence.observation_ids != [str(parent_observation_id)]
            assert child_evidence.evidence_fingerprint == evidence_fingerprint(
                variant_id=variant_id,
                analysis_id=child_id,
                evidence_type=child_evidence.evidence_type,
                statement=child_evidence.statement,
                direction=child_evidence.direction,
                source_name=child_evidence.source_name,
                source_version=child_evidence.source_version,
                observation_ids=(child_observation.id,),
                payload=child_evidence.payload,
                resource_id=child_evidence.resource_id,
                source_record_id=child_evidence.source_record_id,
                request_fingerprint=child_evidence.request_fingerprint,
                response_sha256=child_evidence.response_sha256,
            )
    finally:
        engine.dispose()
