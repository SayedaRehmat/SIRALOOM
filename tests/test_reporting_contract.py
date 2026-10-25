from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Assay,
    Artifact,
    Case,
    Classification,
    AnalysisPartition,
    Organization,
    Report,
    ReportabilityDecision,
    QCAssessment,
    TechnicalQCObservation,
    User,
    Variant,
)
from backend.app.reporting.finalization import finalize_report
from backend.app.reporting.service import build_report_content, final_report_eligibility


def db():
    e=create_engine('sqlite+pysqlite:///:memory:'); Base.metadata.create_all(e); return Session(e)

def seed(approved=True):
    d=db(); o=Organization(id=uuid4(), name='Lab'); u=User(id=uuid4(),organization_id=o.id,display_name='Reviewer',role='MEDICAL_REVIEWER',status='ACTIVE')
    c=Case(id=uuid4(),organization_id=o.id,case_identifier='CASE-1',status='ACTIVE',clinical_context={'test':'Panel','indication':'Example'},language='en',created_by=u.id)
    assay=Assay(id=uuid4(),organization_id=o.id,name='Assay',version='1',assay_type='WGS',configuration={'rules':[{'metric':'mean_depth','direction':'MIN','threshold':20}]},status='ACTIVE')
    a=Analysis(id=uuid4(),case_id=c.id,assay_id=assay.id,analysis_type='VARIANT_INTERPRETATION',workflow_id='variant-v1',workflow_version='1.0',status='REQUIRES_REVIEW',reference_build='GRCh38',configuration={})
    v=Variant(id=uuid4(),genome_build='GRCh38',chromosome='1',position=1,reference='A',alternate='G',normalization_status='NORMALIZED',canonical_key='GRCh38:1:1:A:G',identifiers={})
    partition=AnalysisPartition(id=uuid4(),analysis_id=a.id,step_id='normalize',partition_key='0:1',ordinal=0,record_start=0,record_end=1,variant_count=1,status='SUCCEEDED',metadata_json={'variant_ids':[str(v.id)],'sample_calls':[{'variant_id':str(v.id),'status':'AVAILABLE','sample_name':'SAMPLE-1','genotype':'0/1','zygosity':'HETEROZYGOUS','phase':'UNPHASED','phase_set':None,'format_values':{}}]})
    cl=Classification(id=uuid4(),variant_id=v.id,analysis_id=a.id,framework_name='ACMG/AMP',framework_version='2015',result='VUS',criterion_ids=[],metadata_json={},state='FINAL' if approved else 'PROPOSED',review_status='APPROVED' if approved else 'IN_REVIEW',version=1,review_version=1)
    qc_observation=TechnicalQCObservation(id=uuid4(),analysis_id=a.id,metric_name='mean_depth',metric_value=40,status='AVAILABLE',source='LAB_QC')
    qc=QCAssessment(id=uuid4(),analysis_id=a.id,assay_id=assay.id,status='PASS',profile_name=assay.name,profile_version=assay.version,metrics_json={'mean_depth':40},evaluated_rules=[{'metric':'mean_depth','value':40,'status':'PASS','direction':'MIN','threshold':20,'minimum':None,'maximum':None,'severity':'FAIL'}],observation_snapshot=[],gate_status='PASS',reviewed_by=str(u.id),reviewed_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc))
    d.add_all([o,u,assay,c,a,v,cl,partition,qc_observation,qc])
    d.flush()
    from backend.app.domain.quality_provenance import qc_observation_snapshot
    qc.observation_snapshot=qc_observation_snapshot(d,a,[qc_observation])
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

def test_report_finalization_creates_approval_lineage(monkeypatch):
    monkeypatch.setattr("backend.app.reporting.finalization.render_pdf", lambda _content: b"%PDF-test%")
    d,_,u,c,a,_=seed(True)
    content = build_report_content(d, a, "en", report_type="CLINICAL_INTERPRETATION")
    r=Report(id=uuid4(),case_id=c.id,analysis_id=a.id,report_version=1,language='en',report_type='CLINICAL_INTERPRETATION',status='DRAFT',artifact_id=d.query(Artifact).first().id,content_json=content); d.add(r); d.commit()
    out=finalize_report(d,report_id=r.id,approver_id=u.id,reason='Approved after review'); d.commit(); assert out.status=='FINAL' and out.approved_by==u.id
