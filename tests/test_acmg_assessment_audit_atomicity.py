from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.api.v1 import acmg
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    Annotation,
    Case,
    Classification,
    Organization,
    User,
    Variant,
)


def test_auto_assessment_rolls_back_results_if_audit_persistence_fails(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)

    organization = Organization(id=uuid4(), name="Audit rollback lab")
    user = User(
        id=uuid4(),
        organization_id=organization.id,
        display_name="Reviewer",
        role="reviewer",
        status="ACTIVE",
    )
    case = Case(
        id=uuid4(),
        organization_id=organization.id,
        case_identifier="ACMG-AUDIT-ROLLBACK",
        status="ACTIVE",
        clinical_context={},
        language="en",
        created_by=user.id,
    )
    analysis = Analysis(
        id=uuid4(),
        case_id=case.id,
        analysis_type="VARIANT_INTERPRETATION",
        workflow_id="variant-v1",
        workflow_version="1",
        status="REQUIRES_REVIEW",
        reference_build="GRCh38",
        configuration={},
        created_by=user.id,
    )
    variant = Variant(
        id=uuid4(),
        genome_build="GRCh38",
        chromosome="1",
        position=1,
        reference="A",
        alternate="G",
        normalization_status="NORMALIZED",
        canonical_key=f"GRCh38:1:1:A:G:{uuid4()}",
        identifiers={},
    )
    annotation = Annotation(
        id=uuid4(),
        variant_id=variant.id,
        analysis_id=analysis.id,
        provider_name="test-provider",
        provider_version="1",
        payload={},
    )
    db.add_all([organization, user, case, analysis, variant, annotation])
    db.commit()

    class _Result:
        status = "REQUIRES_REVIEW"
        binding = type(
            "Binding",
            (),
            {
                "status": "SELECTED",
                "specification_id": "TEST-VCEP",
                "specification_version": "1.0",
                "reason": "Exact test specification selected",
            },
        )()
        classification = None

    class _AssessmentService:
        def assess_variant(self, *_args, **_kwargs):
            return _Result()

        def persist(self, session, *, analysis, variant, result):
            session.add(
                ACMGAssessment(
                    id=uuid4(),
                    variant_id=variant.id,
                    analysis_id=analysis.id,
                    framework_name="ACMG/AMP",
                    framework_version="2015",
                    specification_provider="ClinGen",
                    specification_id=result.binding.specification_id,
                    specification_version=result.binding.specification_version,
                    criterion="PP3",
                    state="REQUIRES_REVIEW",
                )
            )
            session.add(
                Classification(
                    id=uuid4(),
                    variant_id=variant.id,
                    analysis_id=analysis.id,
                    framework_name="ACMG/AMP",
                    framework_version="2015",
                    specification_provider="ClinGen",
                    specification_id=result.binding.specification_id,
                    specification_version=result.binding.specification_version,
                    result="VUS",
                    criterion_ids=[],
                    state="PROPOSED",
                    review_status="PENDING",
                    version=1,
                )
            )
            session.flush()

    class _FailingAudit:
        def __init__(self, _session):
            pass

        def record(self, **_kwargs):
            raise RuntimeError("injected ACMG audit persistence failure")

    principal = Principal(
        user_id=user.id,
        organization_id=organization.id,
        role="reviewer",
        subject="test-reviewer",
    )
    monkeypatch.setattr(acmg, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(acmg, "get_analysis_variant", lambda *_args: variant)
    monkeypatch.setattr(acmg, "require_role", lambda *_args: None)
    monkeypatch.setattr(acmg, "ACMGSpecificationAssessmentService", _AssessmentService)
    monkeypatch.setattr(acmg, "AuditService", _FailingAudit)

    try:
        with pytest.raises(RuntimeError, match="injected ACMG audit persistence failure"):
            acmg.auto_assess(
                analysis.id,
                variant.id,
                acmg.ACMGAutoAssessRequest(gene="TEST1"),
                db,
                principal,
            )

        assert db.scalar(
            select(ACMGAssessment.id).where(ACMGAssessment.analysis_id == analysis.id)
        ) is None
        assert db.scalar(
            select(Classification.id).where(Classification.analysis_id == analysis.id)
        ) is None
    finally:
        db.close()
        engine.dispose()
