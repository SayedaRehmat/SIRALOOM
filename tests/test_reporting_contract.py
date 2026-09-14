import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from uuid import uuid4
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, User, Case, Analysis, Variant, Classification, ReportabilityDecision, Artifact, Report
from backend.app.reporting.service import build_report_content, final_report_eligibility
from backend.app.reporting.finalization import finalize_report, ReportFinalizationError


def db():
    e=create_engine('sqlite+pysqlite:///:memory:'); Base.metadata.create_all(e); return Session(e)

def seed(approved=True):
    d=db(); o=Organization(id=uuid4(), name='Lab'); u=User(id=uuid4(),organization_id=o.id,display_name='Reviewer',role='MEDICAL_REVIEWER',status='ACTIVE')
    c=Case(id=uuid4(),organization_id=o.id,case_identifier='CASE-1',status='ACTIVE',clinical_context={'test':'Panel','indication':'Example'},language='en',created_by=u.id)
    a=Analysis(id=uuid4(),case_id=c.id,analysis_type='VARIANT_INTERPRETATION',workflow_id='variant-v1',workflow_version='1.0',status='REQUIRES_REVIEW',reference_build='GRCh38',configuration={})
    v=Variant(id=uuid4(),genome_build='GRCh38',chromosome='1',position=1,reference='A',alternate='G',normalization_status='NORMALIZED',canonical_key='GRCh38:1:1:A:G',identifiers={})
    cl=Classification(id=uuid4(),variant_id=v.id,analysis_id=a.id,framework_name='ACMG/AMP',framework_version='2015',result='VUS',criterion_ids=[],metadata_json={},state='FINAL' if approved else 'PROPOSED',review_status='APPROVED' if approved else 'IN_REVIEW',version=1,review_version=1)
    d.add_all([o,u,c,a,v,cl])
    d.flush()
    rd=ReportabilityDecision(id=uuid4(),analysis_id=a.id,variant_id=v.id,classification_id=cl.id,version=1,policy_name="SIRALOOM_DEFAULT_GERMLINE_REPORTABILITY",policy_version="1.0.0",disposition="REPORT",priority_score=100,priority_band="HIGH",reasons=["Test fixture"],status="FINAL",review_version=1,reviewed_by=u.id)
    art=Artifact(id=uuid4(),case_id=c.id,analysis_id=a.id,artifact_type="REPORT_PDF",filename="fixture.pdf",media_type="application/pdf",size_bytes=100,sha256="a"*64,storage_uri="file:///tmp/fixture.pdf",genome_build="GRCh38")
    d.add_all([rd,art]); d.commit(); return d,o,u,c,a,v

def test_report_content_contract_has_required_fields():
    d,_,_,_,a,_=seed(True); content=build_report_content(d,a,'en');
    for key in ['report_schema_version','report_version','case_id','analysis_id','findings','methodology','limitations','final_result']: assert key in content

def test_report_finalization_requires_reviewed_classifications():
    d,_,_,_,a,_=seed(False)
    ok, errors=final_report_eligibility(d,analysis_id=a.id); assert not ok and errors

def test_report_finalization_creates_approval_lineage():
    d,_,u,c,a,_=seed(True); r=Report(id=uuid4(),case_id=c.id,analysis_id=a.id,report_version=1,language='en',report_type='CLINICAL_INTERPRETATION',status='DRAFT',artifact_id=d.query(Artifact).first().id,content_json={'report_schema_version':'1.0.0'}); d.add(r); d.commit()
    out=finalize_report(d,report_id=r.id,approver_id=u.id,reason='Approved after review'); d.commit(); assert out.status=='FINAL' and out.approved_by==u.id
