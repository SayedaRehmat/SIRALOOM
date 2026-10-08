import pytest
from uuid import uuid4, uuid5
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, User, Case, Analysis, Variant, Classification, ReportabilityDecision, Artifact, ConfirmationRecord
from backend.app.reporting.service import build_report_content, final_report_eligibility
from backend.app.reporting.finalization import finalize_report, ReportFinalizationError, _persist_pdf_artifact
from backend.app.infrastructure.db.models import Report


def make_db():
    engine=create_engine('sqlite+pysqlite:///:memory:'); Base.metadata.create_all(engine); return Session(engine)

def seed(approved=True):
    db=make_db(); org=Organization(id=uuid4(),name='Lab'); u=User(id=uuid4(),organization_id=org.id,display_name='Dr X',role='MEDICAL_REVIEWER',status='ACTIVE')
    c=Case(id=uuid4(),organization_id=org.id,case_identifier='C1',status='ACTIVE',clinical_context={'test':'Panel','indication':'Example'},language='en',created_by=u.id)
    a=Analysis(id=uuid4(),case_id=c.id,analysis_type='VARIANT_INTERPRETATION',workflow_id='variant-v1',workflow_version='1.0',status='REQUIRES_REVIEW',reference_build='GRCh38',configuration={})
    v=Variant(id=uuid4(),genome_build='GRCh38',chromosome='1',position=10,reference='A',alternate='G',normalization_status='NORMALIZED',canonical_key='GRCh38:1:10:A:G',identifiers={})
    cl=Classification(id=uuid4(),variant_id=v.id,analysis_id=a.id,framework_name='ACMG/AMP',framework_version='2015',result='VUS',criterion_ids=[],metadata_json={},state='FINAL' if approved else 'PROPOSED',review_status='APPROVED' if approved else 'IN_REVIEW',version=1,review_version=1)
    db.add_all([org,u,c,a,v,cl])
    db.flush()
    rd=ReportabilityDecision(id=uuid4(),analysis_id=a.id,variant_id=v.id,classification_id=cl.id,version=1,policy_name="SIRALOOM_DEFAULT_GERMLINE_REPORTABILITY",policy_version="1.0.0",disposition="REPORT",priority_score=100,priority_band="HIGH",reasons=["Test fixture"],status="FINAL",review_version=1,reviewed_by=u.id)
    art=Artifact(id=uuid4(),case_id=c.id,analysis_id=a.id,artifact_type="REPORT_PDF",filename="fixture.pdf",media_type="application/pdf",size_bytes=100,sha256="a"*64,storage_uri="file:///tmp/fixture.pdf",genome_build="GRCh38")
    db.add_all([rd,art]); db.commit(); return db, u, c, a, v

def test_final_report_requires_approved_classification():
    db, _, _, a, _=seed(False); ok, errs=final_report_eligibility(db,analysis_id=a.id); assert not ok and errs

def test_finalize_report_sets_final_and_supersedes():
    db,u,c,a,v=seed(True)
    content = build_report_content(db, a, "en", report_type="CLINICAL_INTERPRETATION")
    r=Report(id=uuid4(),case_id=c.id,analysis_id=a.id,report_version=1,language='en',report_type='CLINICAL_INTERPRETATION',status='DRAFT',artifact_id=db.query(Artifact).first().id,content_json=content)
    db.add(r); db.commit()
    out=finalize_report(db,report_id=r.id,approver_id=u.id,reason='Reviewed and approved'); db.commit()
    assert out.status=='FINAL'; assert out.approved_by==u.id

def test_finalize_report_rejects_stale_classification_snapshot():
    db,u,c,a,v=seed(True)
    classification = db.query(Classification).filter_by(analysis_id=a.id, variant_id=v.id).one()
    decision = db.query(ReportabilityDecision).filter_by(analysis_id=a.id, variant_id=v.id).one()
    content = build_report_content(db, a, "en", report_type="CLINICAL_INTERPRETATION")
    newer = Classification(
        id=uuid4(), variant_id=v.id, analysis_id=a.id, framework_name=classification.framework_name,
        framework_version=classification.framework_version, result="PATHOGENIC", criterion_ids=[],
        metadata_json={}, state="FINAL", review_status="APPROVED", version=2, review_version=1,
        supersedes_classification_id=classification.id,
    )
    db.add(newer); db.commit()
    # The draft snapshot intentionally remains the version-1 content built before version 2 existed.
    r=Report(id=uuid4(),case_id=c.id,analysis_id=a.id,report_version=1,language='en',report_type='CLINICAL_INTERPRETATION',status='DRAFT',artifact_id=db.query(Artifact).first().id,content_json=content)
    db.add(r); db.commit()
    with pytest.raises(ReportFinalizationError, match="stale classification"):
        finalize_report(db,report_id=r.id,approver_id=u.id,reason='Reviewed and approved')


def test_signed_report_artifact_identity_survives_transaction_retry(tmp_path, monkeypatch):
    db, u, c, a, _ = seed(True)
    r = Report(
        id=uuid4(), case_id=c.id, analysis_id=a.id, report_version=1,
        language="en", report_type="CLINICAL_INTERPRETATION", status="DRAFT",
        artifact_id=db.query(Artifact).first().id, content_json={},
    )
    db.add(r)
    db.commit()

    monkeypatch.setattr(
        "backend.app.reporting.finalization.settings.artifact_root",
        str(tmp_path),
    )
    content = {
        "report_schema_version": "1.1.0",
        "report_version": 1,
        "language": "en",
        "report_type": "CLINICAL_INTERPRETATION",
        "case_id": str(c.id),
        "analysis_id": str(a.id),
        "reference_build": "GRCh38",
        "findings": [],
        "methodology": "Test methodology.",
        "limitations": "Test limitations.",
        "recommendations": "None.",
        "references": [],
        "final_result": {"status": "FINAL"},
    }

    first = _persist_pdf_artifact(
        db, report=r, content=content, filename="report_v1_signed.pdf"
    )
    first_id = first.id
    db.rollback()

    second = _persist_pdf_artifact(
        db, report=r, content=content, filename="report_v1_signed.pdf"
    )
    db.commit()

    assert first_id == second.id == uuid5(r.id, "siraloom:signed-report-pdf")
    assert db.get(Artifact, second.id) is not None


def test_report_content_persists_exact_confirmation_identity():
    db, _, _, a, v = seed(True)
    confirmation = ConfirmationRecord(
        id=uuid4(),
        analysis_id=a.id,
        variant_id=v.id,
        version=1,
        required=True,
        status="COMPLETED",
        method="ORTHOGONAL_TEST",
        result="CONFIRMED",
    )
    db.add(confirmation)
    db.commit()

    content = build_report_content(db, a, "en", report_type="CLINICAL_INTERPRETATION")
    snapshot = content["findings"][0]["confirmation_context"]

    assert snapshot["record_id"] == str(confirmation.id)
    assert snapshot["version"] == 1
    assert snapshot["required"] is True
    assert snapshot["status"] == "COMPLETED"


def test_finalize_report_rejects_changed_confirmation_snapshot():
    db, u, c, a, v = seed(True)
    confirmation_v1 = ConfirmationRecord(
        id=uuid4(),
        analysis_id=a.id,
        variant_id=v.id,
        version=1,
        required=True,
        status="COMPLETED",
        method="ORTHOGONAL_TEST",
        result="CONFIRMED",
    )
    db.add(confirmation_v1)
    db.commit()

    content = build_report_content(db, a, "en", report_type="CLINICAL_INTERPRETATION")

    confirmation_v2 = ConfirmationRecord(
        id=uuid4(),
        analysis_id=a.id,
        variant_id=v.id,
        version=2,
        supersedes_record_id=confirmation_v1.id,
        required=True,
        status="COMPLETED",
        method="ORTHOGONAL_TEST_REPEAT",
        result="CONFIRMED",
    )
    db.add(confirmation_v2)
    db.commit()

    r = Report(
        id=uuid4(),
        case_id=c.id,
        analysis_id=a.id,
        report_version=1,
        language="en",
        report_type="CLINICAL_INTERPRETATION",
        status="DRAFT",
        artifact_id=db.query(Artifact).first().id,
        content_json=content,
    )
    db.add(r)
    db.commit()

    with pytest.raises(ReportFinalizationError, match="confirmation.*stale"):
        finalize_report(
            db,
            report_id=r.id,
            approver_id=u.id,
            reason="Reviewed and approved",
        )


def test_confirmation_record_version_identity_is_database_enforced():
    db, _, _, a, v = seed(True)
    first = ConfirmationRecord(
        id=uuid4(),
        analysis_id=a.id,
        variant_id=v.id,
        version=1,
        required=True,
        status="COMPLETED",
    )
    second = ConfirmationRecord(
        id=uuid4(),
        analysis_id=a.id,
        variant_id=v.id,
        version=1,
        required=True,
        status="WAIVED",
    )
    db.add(first)
    db.commit()
    db.add(second)
    with pytest.raises(IntegrityError):
        db.commit()
