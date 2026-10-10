from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.case_change import create_case_change_candidates
from backend.app.domain.reanalysis import _copy_rows
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Annotation,
    Case,
    Evidence,
    Notification,
    Organization,
    OrganizationMembership,
    PopulationObservation,
    ReanalysisCandidate,
    ReanalysisChangeEvent,
    User,
    Variant,
)


def _engine():
    return create_engine("sqlite+pysqlite:///:memory:")


def test_case_change_creates_one_candidate_and_notification_per_completed_parent():
    engine = _engine()
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, User.__table__, OrganizationMembership.__table__,
            Case.__table__, Analysis.__table__, ReanalysisChangeEvent.__table__,
            ReanalysisCandidate.__table__, Notification.__table__,
        ],
    )
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    parent_one, parent_two = uuid4(), uuid4()
    phenotype_id = uuid4()
    change_metadata = {"hpo_id": "HP:0001250", "phenotype_id": str(phenotype_id)}

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Case Change Lab", external_identifier=None))
        db.add(User(
            id=user_id, organization_id=organization_id, external_subject=None,
            email="reviewer@test.local", display_name="Reviewer", role="REVIEWER", status="ACTIVE",
        ))
        db.add(OrganizationMembership(
            id=uuid4(), organization_id=organization_id, user_id=user_id,
            role="REVIEWER", status="ACTIVE",
        ))
        case = Case(
            id=case_id, organization_id=organization_id, case_identifier="CASE-CHANGE-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        )
        db.add(case)
        for analysis_id in (parent_one, parent_two):
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
                analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
                workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
                reference_build="GRCh38", configuration={}, started_at=None,
                completed_at=None, created_by=user_id, analysis_version=1,
            ))
        db.commit()

        candidates = create_case_change_candidates(
            db, case=case, trigger_type="PHENOTYPE_UPDATE",
            reason="A new phenotype was recorded.", metadata=change_metadata,
        )
        db.commit()

        assert len(candidates) == 2
        assert {c.parent_analysis_id for c in candidates} == {parent_one, parent_two}
        assert all(c.earliest_affected_step == "build_evidence" for c in candidates)
        assert db.query(ReanalysisChangeEvent).count() == 1
        assert db.query(Notification).count() == 2

        again = create_case_change_candidates(
            db, case=case, trigger_type="PHENOTYPE_UPDATE",
            reason="A new phenotype was recorded.", metadata=change_metadata,
        )
        assert {c.id for c in again} == {c.id for c in candidates}
        assert db.query(ReanalysisChangeEvent).count() == 1
        assert db.query(ReanalysisCandidate).count() == 2
        assert db.query(Notification).count() == 2

        # The same request payload is idempotent, but a later transition with
        # a distinct prior case version must create a new event and candidates.
        later = create_case_change_candidates(
            db, case=case, trigger_type="CLINICAL_CONTEXT_UPDATE",
            reason="Clinical context changed again.",
            metadata={"before": {"diagnosis": "A"}, "after": {"diagnosis": "B"},
                      "previous_updated_at": "2026-10-10T09:00:00+00:00"},
        )
        db.commit()
        assert len(later) == 2
        assert db.query(ReanalysisChangeEvent).count() == 2
        assert db.query(ReanalysisCandidate).count() == 4
        assert db.query(Notification).count() == 4


def test_reanalysis_copy_preserves_annotation_population_and_evidence_provenance():
    engine = _engine()
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, Case.__table__, Analysis.__table__, Variant.__table__,
            Annotation.__table__, Evidence.__table__, PopulationObservation.__table__,
        ],
    )
    organization_id, case_id, parent_id, child_id, user_id, variant_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Provenance Lab", external_identifier=None))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="PROV-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        ))
        db.add(Analysis(
            id=parent_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="2.1",
            status="SUCCEEDED", queue_task_id=None, reference_build="GRCh38", configuration={},
            started_at=None, completed_at=None, created_by=user_id, analysis_version=1,
        ))
        db.add(Analysis(
            id=child_id, case_id=case_id, parent_analysis_id=parent_id, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="2.1",
            status="CREATED", queue_task_id=None, reference_build="GRCh38", configuration={},
            started_at=None, completed_at=None, created_by=user_id, analysis_version=2,
        ))
        db.add(Variant(
            id=variant_id, genome_build="GRCh38", chromosome="1", position=100,
            reference="A", alternate="G", normalization_status="NORMALIZED",
            canonical_key="GRCh38:1-100-A-G", identifiers={},
        ))
        annotation = Annotation(
            id=uuid4(), variant_id=variant_id, analysis_id=parent_id,
            provider_name="GeneBe", provider_version="2026.10", resource_id=None,
            resource_name="GeneBe", resource_version="release-1",
            request_fingerprint="request-fp", response_sha256="response-sha",
            request_metadata={"endpoint": "approved"}, observed_at=None, retry_count=2,
            payload={"gene": "TEST"},
        )
        population = PopulationObservation(
            id=uuid4(), analysis_id=parent_id, variant_id=variant_id,
            resource_id=uuid4(), population_level="GLOBAL", population_code="NFE",
            population_label="Non-Finnish European", allele_count=2, allele_number=100,
            allele_frequency=0.02, homozygote_count=0, availability="AVAILABLE",
            quality_status="PASS", source_record_id="gnomad-record",
            request_fingerprint="population-request", response_sha256="population-response",
            request_metadata={"dataset": "qualified"}, observed_at=None,
        )
        evidence = Evidence(
            id=uuid4(), variant_id=variant_id, analysis_id=parent_id,
            evidence_type="ANNOTATION", statement="Observed annotation.", direction="SUPPORTING",
            source_name="GeneBe", source_version="2026.10", resource_id=None,
            source_record_id="record-1", request_fingerprint="evidence-request",
            response_sha256="evidence-response", request_metadata={"endpoint": "approved"},
            observed_at=None, observation_ids=[], payload={"x": 1},
            created_by_type="SYSTEM", created_by_id="annotation", evidence_fingerprint="evidence-fp",
        )
        db.add_all([annotation, population, evidence])
        db.commit()

        # Starting at ACMG means annotation, population, and evidence are all
        # upstream of the affected stage and must be reused exactly.
        _copy_rows(db, parent_id, child_id, "acmg_assessment")
        db.commit()

        copied_annotation = db.scalar(select(Annotation).where(Annotation.analysis_id == child_id))
        copied_population = db.scalar(select(PopulationObservation).where(PopulationObservation.analysis_id == child_id))
        copied_evidence = db.scalar(select(Evidence).where(Evidence.analysis_id == child_id))

        assert copied_annotation is not None
        assert copied_annotation.request_fingerprint == "request-fp"
        assert copied_annotation.response_sha256 == "response-sha"
        assert copied_annotation.request_metadata == {"endpoint": "approved"}
        assert copied_annotation.retry_count == 2

        assert copied_population is not None
        assert copied_population.source_record_id == "gnomad-record"
        assert copied_population.request_fingerprint == "population-request"
        assert copied_population.response_sha256 == "population-response"
        assert copied_population.request_metadata == {"dataset": "qualified"}

        assert copied_evidence is not None
        assert copied_evidence.resource_id is None
        assert copied_evidence.request_fingerprint == "evidence-request"
        assert copied_evidence.response_sha256 == "evidence-response"
        assert copied_evidence.request_metadata == {"endpoint": "approved"}
