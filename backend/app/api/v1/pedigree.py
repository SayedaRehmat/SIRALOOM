from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.auth.authorization import get_accessible_analysis
from backend.app.auth.principal import Principal, get_current_principal, require_case_tenant
from backend.app.infrastructure.db.models import Case, Analysis, PedigreeMember, PedigreeRelationship, SegregationObservation, InheritanceAssessment, Variant, Evidence
from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.audit.service import AuditService
from backend.app.inheritance import FamilyObservation, normalize_model, assess_model, fingerprint

router = APIRouter(tags=["pedigree-inheritance"])

class MemberInput(BaseModel):
    member_identifier: str = Field(min_length=1, max_length=100)
    relationship_to_proband: str | None = Field(default=None, max_length=100)
    sex: str | None = Field(default=None, max_length=30)
    affected_status: str = Field(default="UNKNOWN", pattern=r"^(AFFECTED|UNAFFECTED|UNKNOWN)$")
    is_proband: bool = False
    sampled: bool = False
    specimen_id: UUID | None = None
    metadata: dict = Field(default_factory=dict)

class RelationshipInput(BaseModel):
    parent_member_id: UUID
    child_member_id: UUID
    relationship_type: str = Field(default="PARENT_CHILD", max_length=50)
    metadata: dict = Field(default_factory=dict)

class SegregationInput(BaseModel):
    pedigree_member_id: UUID
    genotype: str | None = Field(default=None, max_length=50)
    zygosity: str | None = Field(default=None, max_length=50)
    phase: str | None = Field(default=None, max_length=50)
    allele_observed: str | None = Field(default=None, max_length=50)
    phenotype_status: str | None = Field(default=None, max_length=30)
    source: str = Field(default="HUMAN_REVIEW", max_length=50)
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict = Field(default_factory=dict)

class AssessmentInput(BaseModel):
    models: list[str] = Field(default_factory=lambda:["AD","AR","X_LINKED","MITOCHONDRIAL","DE_NOVO"])
    reviewer_note: str | None = Field(default=None, max_length=5000)


def _member(m):
    return {"id":str(m.id),"member_identifier":m.member_identifier,"relationship_to_proband":m.relationship_to_proband,"sex":m.sex,"affected_status":m.affected_status,"is_proband":m.is_proband,"sampled":m.sampled,"specimen_id":str(m.specimen_id) if m.specimen_id else None,"metadata":m.metadata_json or {}}

def _relationship(r):
    return {"id":str(r.id),"parent_member_id":str(r.parent_member_id),"child_member_id":str(r.child_member_id),"relationship_type":r.relationship_type,"metadata":r.metadata_json or {}}

def _seg(o, member=None):
    return {"id":str(o.id),"pedigree_member_id":str(o.pedigree_member_id),"member_identifier":member.member_identifier if member else None,"genotype":o.genotype,"zygosity":o.zygosity,"phase":o.phase,"allele_observed":o.allele_observed,"phenotype_status":o.phenotype_status,"source":o.source,"notes":o.notes,"metadata":o.metadata_json or {}}

@router.get("/cases/{case_id}/pedigree")
def get_pedigree(case_id: UUID, db: Session=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    case=db.get(Case,case_id)
    if not case: raise HTTPException(404,"Case not found")
    require_case_tenant(case,principal)
    members=list(db.scalars(select(PedigreeMember).where(PedigreeMember.case_id==case_id).order_by(PedigreeMember.created_at,PedigreeMember.member_identifier)))
    rels=list(db.scalars(select(PedigreeRelationship).where(PedigreeRelationship.case_id==case_id).order_by(PedigreeRelationship.created_at)))
    return {"case_id":str(case_id),"members":[_member(m) for m in members],"relationships":[_relationship(r) for r in rels]}

@router.post("/cases/{case_id}/pedigree/members",status_code=201)
def add_member(case_id: UUID, body: MemberInput, db: Session=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    case=db.get(Case,case_id)
    if not case: raise HTTPException(404,"Case not found")
    require_case_tenant(case,principal)
    if db.scalar(select(PedigreeMember).where(PedigreeMember.case_id==case_id,PedigreeMember.member_identifier==body.member_identifier.strip())):
        raise HTTPException(409,"Pedigree member identifier already exists")
    if body.is_proband and db.scalar(select(PedigreeMember).where(PedigreeMember.case_id==case_id,PedigreeMember.is_proband.is_(True))):
        raise HTTPException(409,"A case can have only one designated proband")
    row=PedigreeMember(id=uuid4(),case_id=case_id,member_identifier=body.member_identifier.strip(),relationship_to_proband=body.relationship_to_proband,sex=body.sex,affected_status=body.affected_status,is_proband=body.is_proband,sampled=body.sampled,specimen_id=body.specimen_id,metadata_json=body.metadata)
    db.add(row)
    AuditService(db).record(event_type="PEDIGREE_MEMBER_ADDED",case_id=case_id,analysis_id=None,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="PEDIGREE_MEMBER",subject_id=str(row.id),operation="CREATE",after_state=_member(row))
    db.commit(); return _member(row)

@router.post("/cases/{case_id}/pedigree/relationships",status_code=201)
def add_relationship(case_id: UUID, body: RelationshipInput, db: Session=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    case=db.get(Case,case_id)
    if not case: raise HTTPException(404,"Case not found")
    require_case_tenant(case,principal)
    parent=db.get(PedigreeMember,body.parent_member_id); child=db.get(PedigreeMember,body.child_member_id)
    if not parent or not child or parent.case_id!=case_id or child.case_id!=case_id or parent.id==child.id: raise HTTPException(400,"Parent and child must be distinct members in the same case")
    if db.scalar(select(PedigreeRelationship).where(PedigreeRelationship.case_id==case_id,PedigreeRelationship.parent_member_id==parent.id,PedigreeRelationship.child_member_id==child.id)):
        raise HTTPException(409,"Pedigree relationship already exists")
    row=PedigreeRelationship(id=uuid4(),case_id=case_id,parent_member_id=parent.id,child_member_id=child.id,relationship_type=body.relationship_type,metadata_json=body.metadata)
    db.add(row)
    AuditService(db).record(event_type="PEDIGREE_RELATIONSHIP_ADDED",case_id=case_id,analysis_id=None,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="PEDIGREE_RELATIONSHIP",subject_id=str(row.id),operation="CREATE",after_state=_relationship(row))
    db.commit(); return _relationship(row)

@router.get("/analyses/{analysis_id}/variants/{variant_id}/segregation")
def get_segregation(analysis_id: UUID,variant_id: UUID,db: Session=Depends(get_db),principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id,db,principal)
    variant=db.get(Variant,variant_id)
    if not variant: raise HTTPException(404,"Variant not found")
    rows=list(db.scalars(select(SegregationObservation).where(SegregationObservation.analysis_id==analysis_id,SegregationObservation.variant_id==variant_id).order_by(SegregationObservation.created_at)))
    members={m.id:m for m in db.scalars(select(PedigreeMember).where(PedigreeMember.case_id==analysis.case_id))}
    assessments=list(db.scalars(select(InheritanceAssessment).where(InheritanceAssessment.analysis_id==analysis_id,InheritanceAssessment.variant_id==variant_id).order_by(InheritanceAssessment.created_at.desc())))
    return {"analysis_id":str(analysis_id),"variant_id":str(variant_id),"observations":[_seg(x,members.get(x.pedigree_member_id)) for x in rows],"assessments":[{"id":str(a.id),"model":a.model,"status":a.status,"score":a.score,"rationale":a.rationale,"fingerprint":a.observation_fingerprint,"reviewer_note":a.reviewer_note,"created_by":a.created_by,"created_at":a.created_at.isoformat()} for a in assessments]}

@router.post("/analyses/{analysis_id}/variants/{variant_id}/segregation",status_code=201)
def add_segregation(analysis_id: UUID,variant_id: UUID,body: SegregationInput,db: Session=Depends(get_db),principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id,db,principal)
    variant=db.get(Variant,variant_id)
    member=db.get(PedigreeMember,body.pedigree_member_id)
    if not variant or not member or member.case_id!=analysis.case_id: raise HTTPException(400,"Variant and pedigree member must belong to this analysis/case")
    existing=db.scalar(select(SegregationObservation).where(SegregationObservation.analysis_id==analysis_id,SegregationObservation.variant_id==variant_id,SegregationObservation.pedigree_member_id==member.id))
    if existing:
        existing.genotype=body.genotype; existing.zygosity=body.zygosity; existing.phase=body.phase; existing.allele_observed=body.allele_observed; existing.phenotype_status=body.phenotype_status; existing.source=body.source; existing.notes=body.notes; existing.metadata_json=body.metadata
        row=existing; action="UPDATE"
    else:
        row=SegregationObservation(id=uuid4(),analysis_id=analysis_id,variant_id=variant_id,pedigree_member_id=member.id,genotype=body.genotype,zygosity=body.zygosity,phase=body.phase,allele_observed=body.allele_observed,phenotype_status=body.phenotype_status,source=body.source,notes=body.notes,metadata_json=body.metadata); db.add(row); action="CREATE"
    AuditService(db).record(event_type="SEGREGATION_OBSERVATION_RECORDED",case_id=analysis.case_id,analysis_id=analysis_id,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="SEGREGATION_OBSERVATION",subject_id=str(row.id),operation=action,after_state=_seg(row,member))
    db.commit(); return _seg(row,member)

@router.post("/analyses/{analysis_id}/variants/{variant_id}/inheritance/assess")
def assess_inheritance(analysis_id: UUID,variant_id: UUID,body: AssessmentInput,db: Session=Depends(get_db),principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id,db,principal)
    variant=db.get(Variant,variant_id)
    if not variant: raise HTTPException(404,"Variant not found")
    rows=list(db.scalars(select(SegregationObservation).where(SegregationObservation.analysis_id==analysis_id,SegregationObservation.variant_id==variant_id)))
    members={m.id:m for m in db.scalars(select(PedigreeMember).where(PedigreeMember.case_id==analysis.case_id))}
    obs=[FamilyObservation(member_id=members[r.pedigree_member_id].member_identifier,sex=members[r.pedigree_member_id].sex,affected_status=r.phenotype_status or members[r.pedigree_member_id].affected_status,genotype=r.genotype,zygosity=r.zygosity) for r in rows if r.pedigree_member_id in members]
    fp=fingerprint(obs); results=[]
    for raw in body.models:
        try: model=normalize_model(raw)
        except ValueError as exc: raise HTTPException(400,str(exc))
        result=assess_model(model,obs)
        row=InheritanceAssessment(id=uuid4(),analysis_id=analysis_id,variant_id=variant_id,model=model,status=result["status"],score=result["score"],rationale=result["rationale"],observation_fingerprint=fp,reviewer_note=body.reviewer_note,created_by=str(principal.user_id))
        db.add(row); results.append({"id":str(row.id),**result,"fingerprint":fp,"reviewer_note":body.reviewer_note})
        # Preserve segregation context for review, but never map it automatically to an ACMG strength.
        payload={"model":model,"status":result["status"],"score":result["score"],"observation_fingerprint":fp,"reviewer_note":body.reviewer_note}
        stmt=select(Evidence).where(Evidence.analysis_id==analysis_id,Evidence.variant_id==variant_id,Evidence.evidence_type=="SEGREGATION",Evidence.evidence_fingerprint==__import__('hashlib').sha256(__import__('json').dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest())
        if not db.scalar(stmt):
            db.add(Evidence(id=uuid4(),variant_id=variant_id,analysis_id=analysis_id,evidence_type="SEGREGATION",statement=f"Inheritance model {model}: {result['status']}",direction="CONTEXTUAL",source_name="SIRALOOM Inheritance Engine",source_version="M10",source_record_id=None,observation_ids=[str(r.id) for r in rows],payload=payload,created_by_type="SYSTEM",created_by_id="inheritance",evidence_fingerprint=__import__('hashlib').sha256(__import__('json').dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()))
    AuditService(db).record(event_type="INHERITANCE_ASSESSMENT_RECORDED",case_id=analysis.case_id,analysis_id=analysis_id,actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="VARIANT_INHERITANCE",subject_id=str(variant_id),operation="CREATE",after_state={"models":results,"observation_fingerprint":fp},reason=body.reviewer_note)
    db.commit(); return {"analysis_id":str(analysis_id),"variant_id":str(variant_id),"observation_fingerprint":fp,"results":results,"important_note":"Inheritance consistency is decision support and does not itself establish pathogenicity or an ACMG/ClinGen criterion strength."}
