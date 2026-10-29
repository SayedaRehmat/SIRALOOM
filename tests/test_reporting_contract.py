from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisPartition,
    Artifact,
    Assay,
    Case,
    Classification,
    ConfirmationRecord,
    Organization,
    PedigreeMember,
    PedigreeRelationship,
    PhenotypeObservation,
    QCAssessment,
    Report,
    ReportabilityDecision,
    SegregationObservation,
    Specimen,
    TechnicalQCObservation,
    User,
    Variant,
    WorkflowStep,
)
from backend.app.reporting.finalization import finalize_report
from backend.app.reporting.service import (
    build_report_content,
    final_report_eligibility,
    render_html,
)


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
    confirmation=ConfirmationRecord(id=uuid4(),analysis_id=a.id,variant_id=v.id,version=1,required=False,status="NOT_REQUIRED",reviewed_by=u.id,reviewed_at=datetime.now(UTC),notes="Fixture explicitly records that orthogonal confirmation is not required.")
    d.add_all([o,u,assay,c,a,v,cl,partition,qc_observation,qc,confirmation])
    d.flush()
    from backend.app.domain.quality_provenance import qc_observation_snapshot
    qc.observation_snapshot=qc_observation_snapshot(d,a,[qc_observation])
    d.flush()
    rd=ReportabilityDecision(id=uuid4(),analysis_id=a.id,variant_id=v.id,classification_id=cl.id,version=1,policy_name="SIRALOOM_DEFAULT_GERMLINE_REPORTABILITY",policy_version="1.0.0",disposition="REPORT",priority_score=100,priority_band="HIGH",reasons=["Test fixture"],status="FINAL",review_version=1,reviewed_by=u.id)
    art=Artifact(id=uuid4(),case_id=c.id,analysis_id=a.id,artifact_type="REPORT_PDF",filename="fixture.pdf",media_type="application/pdf",size_bytes=100,sha256="a"*64,storage_uri="file:///tmp/fixture.pdf",genome_build="GRCh38",validation_status="VALID")
    d.add_all([rd,art]); d.commit(); return d,o,u,c,a,v

def test_report_content_contract_has_required_fields():
    d,_,_,_,a,_=seed(True); content=build_report_content(d,a,'en');
    for key in ['report_schema_version','report_version','case_id','analysis_id','findings','methodology','limitations','final_result']: assert key in content


def test_report_preserves_and_renders_descriptive_family_observations():
    d, _, _, case, analysis, variant = seed(True)
    proband = PedigreeMember(
        id=uuid4(), case_id=case.id, member_identifier="PROBAND-01",
        relationship_to_proband="PROBAND", sex="FEMALE", affected_status="AFFECTED",
        is_proband=True, sampled=True, metadata_json={},
    )
    parent = PedigreeMember(
        id=uuid4(), case_id=case.id, member_identifier="PARENT-01",
        relationship_to_proband="MOTHER", sex="FEMALE", affected_status="UNAFFECTED",
        is_proband=False, sampled=True, metadata_json={},
    )
    relationship = PedigreeRelationship(
        id=uuid4(), case_id=case.id, parent_member_id=parent.id,
        child_member_id=proband.id, relationship_type="PARENT_CHILD", metadata_json={},
    )
    observation = SegregationObservation(
        id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
        pedigree_member_id=parent.id, genotype="0/1", zygosity="HET",
        phase="UNPHASED", allele_observed="ALT", phenotype_status="UNAFFECTED",
        source="LAB_CONFIRMATION", notes="Recorded family observation", metadata_json={},
    )
    d.add_all([proband, parent, relationship, observation])
    d.commit()

    content = build_report_content(d, analysis, "en", report_type="ANALYTICAL")
    finding = content["findings"][0]
    report_observation = finding["inheritance_context"]["segregation_observations"][0]
    html_content = render_html(content).decode("utf-8")

    assert content["report_schema_version"] == "1.3.0"
    assert next(member for member in content["pedigree_context"]["members"] if member["id"] == str(parent.id))["member_identifier"] == "PARENT-01"
    assert content["pedigree_context"]["relationships"][0]["parent_member_identifier"] == "PARENT-01"
    assert report_observation["observation_id"] == str(observation.id)
    assert report_observation["member_identifier"] == "PARENT-01"
    assert report_observation["allele_observed"] == "ALT"
    assert "PARENT-01" in html_content
    assert "Allele observed" in html_content
    assert "do not by themselves establish inheritance" in html_content


def test_report_uses_specimen_bound_to_analysis_input_not_newest_case_specimen():
    d, _, _, case, analysis, _ = seed(True)
    selected = Specimen(
        id=uuid4(), case_id=case.id, specimen_identifier="PROBAND",
        specimen_type="BLOOD", metadata_json={},
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    newer_relative = Specimen(
        id=uuid4(), case_id=case.id, specimen_identifier="FATHER",
        specimen_type="BLOOD", metadata_json={},
        created_at=datetime(2024, 2, 1, tzinfo=UTC),
    )
    input_vcf = Artifact(
        id=uuid4(), case_id=case.id, artifact_type="VCF", filename="proband.vcf",
        media_type="text/vcf", size_bytes=10, sha256="c" * 64,
        storage_uri="file:///tmp/proband.vcf", genome_build="GRCh38",
        specimen_id=selected.id, validation_status="VALID",
    )
    d.add_all([selected, newer_relative, input_vcf])
    analysis.configuration = {
        "input_artifact_id": str(input_vcf.id),
        "specimen_id": str(selected.id),
    }
    d.commit()

    content = build_report_content(d, analysis, "en")

    assert content["specimen"]["specimen_id"] == str(selected.id)
    assert content["specimen"]["specimen_identifier"] == "PROBAND"


def test_report_blocks_ambiguous_legacy_analysis_with_multiple_specimens():
    d, _, _, case, analysis, _ = seed(True)
    d.add_all([
        Specimen(
            id=uuid4(), case_id=case.id, specimen_identifier="SAMPLE-A",
            specimen_type="BLOOD", metadata_json={},
        ),
        Specimen(
            id=uuid4(), case_id=case.id, specimen_identifier="SAMPLE-B",
            specimen_type="BLOOD", metadata_json={},
        ),
    ])
    d.commit()

    eligible, errors = final_report_eligibility(
        d, analysis_id=analysis.id, report_type="ANALYTICAL"
    )

    assert not eligible
    assert any("multiple case specimens" in error for error in errors)
    with pytest.raises(ValueError, match="multiple case specimens"):
        build_report_content(d, analysis, "en", report_type="ANALYTICAL")


def test_reportability_preflight_rejects_specimen_that_disagrees_with_input_vcf():
    d, _, _, case, analysis, _ = seed(True)
    selected = Specimen(
        id=uuid4(), case_id=case.id, specimen_identifier="VCF-SAMPLE",
        specimen_type="BLOOD", metadata_json={},
    )
    conflicting = Specimen(
        id=uuid4(), case_id=case.id, specimen_identifier="OTHER-SAMPLE",
        specimen_type="BLOOD", metadata_json={},
    )
    input_vcf = Artifact(
        id=uuid4(), case_id=case.id, artifact_type="VCF", filename="sample.vcf",
        media_type="text/vcf", size_bytes=10, sha256="d" * 64,
        storage_uri="file:///tmp/sample.vcf", genome_build="GRCh38",
        specimen_id=selected.id, validation_status="VALID",
    )
    d.add_all([selected, conflicting, input_vcf])
    analysis.configuration = {
        "input_artifact_id": str(input_vcf.id),
        "specimen_id": str(conflicting.id),
    }
    d.commit()

    eligible, errors = final_report_eligibility(
        d, analysis_id=analysis.id, report_type="ANALYTICAL"
    )

    assert not eligible
    assert "Analysis specimen identity does not match its input VCF" in errors


def test_report_uses_analysis_time_phenotype_snapshot_after_case_context_changes():
    from backend.app.domain.clinical_input_snapshot import clinical_input_snapshot_digest

    d, _, _, case, analysis, _ = seed(True)
    snapshot = {
        "schema_version": 1,
        "phenotype_observations": [{
            "scope": "CASE", "hpo_id": "HP:0001251", "label": "Ataxia",
            "present": True, "phenotype_status": "PRESENT", "onset": "CHILDHOOD",
            "severity": None, "source": "CLINICAL_INPUT", "evidence": {},
        }],
        "gene_disease_evidence": [],
        "literature_evidence": [],
    }
    d.add_all([
        WorkflowStep(
            id=uuid4(), analysis_id=analysis.id, step_id="build_evidence",
            step_order=5, status="SUCCEEDED", attempt=1,
            input_artifacts=[], output_artifacts=[], metadata_json={
                "clinical_input_snapshot": snapshot,
                "clinical_input_snapshot_sha256": clinical_input_snapshot_digest(snapshot),
            },
        ),
        PhenotypeObservation(
            id=uuid4(), case_id=case.id, analysis_id=None,
            hpo_id="HP:0001250", label="Seizure", present=True,
            phenotype_status="PRESENT", source="CLINICAL_INPUT", evidence={},
        ),
    ])
    d.commit()

    content = build_report_content(d, analysis, "en", report_type="ANALYTICAL")

    assert [row["hpo_id"] for row in content["phenotype_context"]] == ["HP:0001251"]


def test_completed_evidence_without_clinical_snapshot_cannot_generate_report():
    d, _, _, _, analysis, _ = seed(True)
    d.add(WorkflowStep(
        id=uuid4(), analysis_id=analysis.id, step_id="build_evidence",
        step_order=5, status="SUCCEEDED", attempt=1,
        input_artifacts=[], output_artifacts=[], metadata_json={},
    ))
    d.commit()

    eligible, errors = final_report_eligibility(
        d, analysis_id=analysis.id, report_type="ANALYTICAL"
    )

    assert not eligible
    assert any("missing its captured clinical input snapshot" in error for error in errors)
    with pytest.raises(ValueError, match="missing its captured clinical input snapshot"):
        build_report_content(d, analysis, "en", report_type="ANALYTICAL")

def test_report_finalization_requires_reviewed_classifications():
    d,_,_,_,a,_=seed(False)
    ok, errors=final_report_eligibility(d,analysis_id=a.id); assert not ok and errors

def test_report_finalization_creates_approval_lineage(monkeypatch):
    monkeypatch.setattr("backend.app.reporting.finalization.render_pdf", lambda _content: b"%PDF-test%")
    d,_,u,c,a,_=seed(True)
    content = build_report_content(d, a, "en", report_type="CLINICAL_INTERPRETATION")
    r=Report(id=uuid4(),case_id=c.id,analysis_id=a.id,report_version=1,language='en',report_type='CLINICAL_INTERPRETATION',status='DRAFT',artifact_id=d.query(Artifact).first().id,content_json=content); d.add(r); d.commit()
    out=finalize_report(d,report_id=r.id,approver_id=u.id,reason='Approved after review'); d.commit(); assert out.status=='FINAL' and out.approved_by==u.id
