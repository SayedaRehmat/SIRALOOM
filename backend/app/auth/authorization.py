"""Reusable case-inherited authorization dependencies."""
from uuid import UUID
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.auth.principal import Principal, get_current_principal, require_case_tenant
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, Report
from backend.app.infrastructure.db.session import get_db

READ_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director", "clinical_geneticist", "reviewer", "bioinformatician", "lab_scientist", "read_only"})
CASE_WRITE_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director", "clinical_geneticist", "bioinformatician", "lab_scientist"})
REVIEW_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director", "clinical_geneticist", "reviewer"})
REPORT_FINALIZE_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director", "clinical_geneticist"})

def require_role(principal: Principal, roles: frozenset[str]) -> Principal:
    if principal.role not in roles:
        raise HTTPException(status_code=403, detail="Your organization role is not authorized for this operation")
    return principal

def get_accessible_case(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)) -> Case:
    case = db.get(Case, case_id)
    if not case: raise HTTPException(status_code=404, detail="Case not found")
    require_case_tenant(case, principal)
    return case

def get_accessible_analysis(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if not analysis: raise HTTPException(status_code=404, detail="Analysis not found")
    case = db.get(Case, analysis.case_id)
    if not case: raise HTTPException(status_code=404, detail="Analysis not found")
    require_case_tenant(case, principal)
    return analysis

def get_accessible_artifact(artifact_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if not artifact: raise HTTPException(status_code=404, detail="Artifact not found")
    case = db.get(Case, artifact.case_id)
    if not case: raise HTTPException(status_code=404, detail="Artifact not found")
    require_case_tenant(case, principal)
    return artifact

def get_accessible_report(report_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)) -> Report:
    report = db.get(Report, report_id)
    if not report: raise HTTPException(status_code=404, detail="Report not found")
    case = db.get(Case, report.case_id)
    if not case: raise HTTPException(status_code=404, detail="Report not found")
    require_case_tenant(case, principal)
    return report
