from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.app.api.v1.review import review_queue
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisPartition,
    Annotation,
    Case,
    CaseAccessGrant,
    Classification,
    Evidence,
    Organization,
    OrganizationMembership,
    PopulationObservation,
    ReportabilityDecision,
    Resource,
    User,
    Variant,
)


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
    membership = OrganizationMembership(
        id=uuid4(), organization_id=org.id, user_id=user.id,
        role="reviewer", status="ACTIVE",
    )
    grant = CaseAccessGrant(
        id=uuid4(), case_id=case.id, user_id=user.id,
        can_read=True, can_write=False, can_review=True,
    )
    db.add_all([org, user, membership, case, grant, analysis, variant, annotation, resource, pop, evidence, classification, reportability]); db.commit()
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
    assert "priority" not in item
    assert "priority_band" not in item
    assert item["evidence_count"] == 1
    assert item["population_count"] == 1


def test_review_queue_reportability_filter_is_server_side():
    db, principal, analysis, _ = seed()
    unreviewed = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="17", position=43071078,
        reference="C", alternate="A", normalization_status="NORMALIZED",
        canonical_key="GRCh38:17:43071078:C:A", identifiers={},
    )
    db.add_all([
        unreviewed,
        Annotation(
            id=uuid4(), variant_id=unreviewed.id, analysis_id=analysis.id,
            provider_name="test", provider_version="1", resource_name="test",
            resource_version="1", payload={"normalized": {}},
        ),
        Classification(
            id=uuid4(), variant_id=unreviewed.id, analysis_id=analysis.id,
            framework_name="ACMG/AMP", framework_version="2015", result="VUS",
            criterion_ids=[], metadata_json={}, state="PROPOSED",
            review_status="IN_REVIEW", version=1, review_version=0,
        ),
    ])
    db.commit()
    assert review_queue(analysis.id, reportability="REPORT", db=db, principal=principal)["total"] == 0
    assert review_queue(analysis.id, reportability="REVIEW", db=db, principal=principal)["total"] == 1
    assert review_queue(analysis.id, reportability="NOT_DETERMINED", db=db, principal=principal)["total"] == 1


def test_review_queue_paginates_after_filtering_latest_reportability_decision():
    db, principal, analysis, _ = seed()
    for index in range(3):
        variant = Variant(
            id=uuid4(), genome_build="GRCh38", chromosome="17",
            position=43071078 + index, reference="C", alternate="A",
            normalization_status="NORMALIZED",
            canonical_key=f"GRCh38:17:{43071078 + index}:C:A", identifiers={},
        )
        annotation = Annotation(
            id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
            provider_name="test", provider_version="1", resource_name="test",
            resource_version="1", payload={"normalized": {"gene": "BRCA1"}},
        )
        classification = Classification(
            id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
            framework_name="ACMG/AMP", framework_version="2015", result="VUS",
            criterion_ids=[], metadata_json={}, state="PROPOSED",
            review_status="IN_REVIEW", version=1, review_version=0,
        )
        decision = ReportabilityDecision(
            id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
            classification_id=classification.id, version=1,
            policy_name="SIRALOOM_DEFAULT_GERMLINE_REPORTABILITY",
            policy_version="1.0.0", disposition="REPORT" if index == 1 else "REVIEW",
            priority_score=60, priority_band="REVIEW", reasons=[], status="PROPOSED",
            review_version=0,
        )
        db.add_all([variant, annotation, classification, decision])
        if index == 1:
            # The highest version must determine the filter; the previous
            # REPORT decision remains historical and must not match.
            db.add(
                ReportabilityDecision(
                    id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
                    classification_id=classification.id, version=2,
                    policy_name="SIRALOOM_DEFAULT_GERMLINE_REPORTABILITY",
                    policy_version="1.0.0", disposition="REVIEW",
                    priority_score=60, priority_band="REVIEW", reasons=[],
                    status="PROPOSED", review_version=0,
                )
            )
    db.commit()

    statements = []
    event.listen(
        db.get_bind(), "before_cursor_execute",
        lambda _conn, _cursor, statement, _parameters, _context, _many: statements.append(statement),
    )
    result = review_queue(
        analysis.id, reportability="REVIEW", limit=2, offset=1,
        db=db, principal=principal,
    )
    assert result["total"] == 4
    assert len(result["items"]) == 2
    assert result["items"][0]["position"] == 43071078
    assert result["items"][1]["position"] == 43071079
    assert review_queue(
        analysis.id, reportability="REPORT", db=db, principal=principal
    )["total"] == 0
    assert any(
        "LIMIT" in statement.upper()
        and "OFFSET" in statement.upper()
        and "REPORTABILITY_DECISIONS" in statement.upper()
        for statement in statements
    )


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


def test_review_queue_rejects_downstream_variant_absent_from_normalization_manifest():
    from fastapi import HTTPException

    db, principal, analysis, _ = seed()
    db.add(AnalysisPartition(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize",
        partition_key="0:0", ordinal=0, record_start=0, record_end=0,
        variant_count=0, status="SUCCEEDED", metadata_json={"variant_ids": []},
    ))
    db.commit()

    try:
        review_queue(analysis.id, db=db, principal=principal)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("review queue must reject downstream rows absent from the input manifest")
