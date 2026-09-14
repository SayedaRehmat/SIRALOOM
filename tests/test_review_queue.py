from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, User, Case, Analysis, Variant, Annotation, Classification, Evidence, PopulationObservation, Resource, ReportabilityDecision
from backend.app.auth.principal import Principal
from backend.app.api.v1.review import review_queue


def seed():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    org = Organization(id=uuid4(), name="Review Lab")
    user = User(id=uuid4(), organization_id=org.id, display_name="Reviewer", email="review@example.org", role="reviewer", status="ACTIVE")
    case = Case(id=uuid4(), organization_id=org.id, case_identifier="R-1", status="ACTIVE", clinical_context={"indication": "diagnostic"}, language="en", created_by=user.id)
    analysis = Analysis(id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="1.0", status="REQUIRES_REVIEW", reference_build="GRCh38", configuration={}, created_by=user.id)
    variant = Variant(id=uuid4(), genome_build="GRCh38", chromosome="17", position=43071077, reference="C", alternate="T", normalization_status="NORMALIZED", canonical_key="GRCh38:17:43071077:C:T", identifiers={})
    annotation = Annotation(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, provider_name="test", provider_version="1", resource_name="test", resource_version="1", payload={"normalized": {"gene": "BRCA1", "consequence": "missense_variant"}})
    resource = Resource(id=uuid4(), name="gnomAD", provider="test", resource_type="population", version="1", access_method="fixture", status="ACTIVE")
    pop = PopulationObservation(id=uuid4(), analysis_id=analysis.id, variant_id=variant.id, resource_id=resource.id, population_level="GLOBAL", population_code="GLOBAL", population_label="Global", allele_frequency=0.0001, availability="AVAILABLE")
    evidence = Evidence(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, evidence_type="POPULATION", statement="Rare", direction="PATHOGENIC", source_name="gnomAD", source_version="4", source_record_id="x", observation_ids=[str(pop.id)], payload={}, created_by_type="SYSTEM", created_by_id="test", evidence_fingerprint="fp-1")
    classification = Classification(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", result="VUS", criterion_ids=[], metadata_json={}, state="PROPOSED", review_status="IN_REVIEW", version=1, review_version=0)
    reportability = ReportabilityDecision(id=uuid4(), analysis_id=analysis.id, variant_id=variant.id, classification_id=classification.id, version=1, policy_name="SIRALOOM_DEFAULT_GERMLINE_REPORTABILITY", policy_version="1.0.0", disposition="REVIEW", priority_score=60, priority_band="REVIEW", reasons=["VUS requires explicit review"], status="PROPOSED", review_version=0)
    db.add_all([org, user, case, analysis, variant, annotation, resource, pop, evidence, classification, reportability]); db.commit()
    return db, Principal(user_id=user.id, organization_id=org.id, role="reviewer", subject="firebase-reviewer") , analysis, variant


def test_review_queue_returns_interpretation_context():
    db, principal, analysis, variant = seed()
    result = review_queue(analysis.id, db=db, principal=principal)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["variant_id"] == str(variant.id)
    assert item["gene"] == "BRCA1"
    assert item["consequence"] == "missense_variant"
    assert item["reportability"] == "REVIEW"
    assert item["evidence_count"] == 1
    assert item["population_count"] == 1


def test_review_queue_reportability_filter_is_server_side():
    db, principal, analysis, _ = seed()
    assert review_queue(analysis.id, reportability="REPORT", db=db, principal=principal)["total"] == 0
    assert review_queue(analysis.id, reportability="REVIEW", db=db, principal=principal)["total"] == 1


def test_review_queue_blocks_cross_tenant_access():
    db, principal, analysis, _ = seed()
    other_org = uuid4()
    other_principal = Principal(user_id=uuid4(), organization_id=other_org, role="reviewer", subject="other")
    from fastapi import HTTPException
    try:
        review_queue(analysis.id, db=db, principal=other_principal)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("cross-tenant review queue access must be rejected")
