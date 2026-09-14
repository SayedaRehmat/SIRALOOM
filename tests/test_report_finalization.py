from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, User, Case, Analysis, Variant, Classification, ReportabilityDecision, Artifact
from backend.app.reporting.service import final_report_eligibility
from backend.app.reporting.finalization import finalize_report, ReportFinalizationError
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
    db,u,c,a,v=seed(True); r=Report(id=uuid4(),case_id=c.id,analysis_id=a.id,report_version=1,language='en',report_type='CLINICAL_INTERPRETATION',status='DRAFT',artifact_id=db.query(Artifact).first().id,content_json={}); db.add(r); db.commit()
    out=finalize_report(db,report_id=r.id,approver_id=u.id,reason='Reviewed and approved'); db.commit()
    assert out.status=='FINAL'; assert out.approved_by==u.id
