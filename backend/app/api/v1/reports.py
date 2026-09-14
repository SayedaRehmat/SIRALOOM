from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from backend.app.auth.principal import Principal, get_current_principal, require_case_tenant
from backend.app.auth.authorization import CASE_WRITE_ROLES, REPORT_FINALIZE_ROLES, get_accessible_analysis, get_accessible_report, require_role
from backend.app.domain.schemas import ReportCreate, ExportCreate, ReportabilityDecisionRequest
from backend.app.domain.review import ClassificationReviewRequest
from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.db.models import Analysis, Report, CaseExport, Case
from backend.app.reporting.service import build_report_content, render_pdf, render_html
from backend.app.reporting.finalization import finalize_report, ReportFinalizationError
from backend.app.reporting.reportability import evaluate_analysis, finalize_reportability, latest_decision
from backend.app.reporting.export_task import run_case_export
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.config import settings
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.queue.celery_app import run_case_export_task

router = APIRouter(tags=["reports"])

@router.post("/analyses/{analysis_id}/reports", status_code=201)
def create_report(analysis_id: UUID, payload: ReportCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal); require_role(principal, CASE_WRITE_ROLES)
    content = build_report_content(db, analysis, payload.language, report_type=payload.report_type, include_full_evidence=payload.include_full_evidence)
    last = db.scalar(select(func.max(Report.report_version)).where(Report.case_id == analysis.case_id, Report.report_type == payload.report_type)) or 0
    version = int(last) + 1; content["report_version"] = version
    pdf = render_pdf(content)
    store = FirebaseArtifactStore(settings.firebase_storage_bucket) if settings.firebase_storage_enabled else ArtifactStore(settings.artifact_root)
    artifact = store.put_bytes(db=db, case_id=analysis.case_id, analysis_id=analysis.id, data=pdf, filename=f"report_v{version}.pdf", artifact_type="REPORT_PDF", media_type="application/pdf", genome_build=analysis.reference_build, metadata={"rendered_format":"PDF","report_schema_version":content["report_schema_version"]})
    report = Report(id=uuid4(), case_id=analysis.case_id, analysis_id=analysis.id, report_version=version, language=payload.language, report_type=payload.report_type, status="DRAFT", artifact_id=artifact.id, content_json=content)
    db.add(report)
    AuditService(db).record(event_type="REPORT_GENERATED", case_id=analysis.case_id, analysis_id=analysis.id, actor_type="SYSTEM", actor_id="reporting", subject_type="REPORT", subject_id=str(report.id), operation="CREATE", output_artifacts=[{"artifact_id":str(artifact.id),"sha256":artifact.sha256}], payload={"draft":True})
    db.commit(); return {"report_id":str(report.id),"version":version,"artifact_id":str(artifact.id),"status":report.status}

@router.get("/analyses/{analysis_id}/reports")
def list_reports(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    rows = list(db.scalars(select(Report).where(Report.analysis_id == analysis.id).order_by(Report.report_version.desc())))
    return {"analysis_id": str(analysis_id), "items": [{"report_id": str(r.id), "case_id": str(r.case_id), "version": r.report_version, "status": r.status, "language": r.language, "report_type": r.report_type, "artifact_id": str(r.artifact_id) if r.artifact_id else None, "approved_by": str(r.approved_by) if r.approved_by else None, "approved_at": r.approved_at.isoformat() if r.approved_at else None, "supersedes_report_id": str(r.supersedes_report_id) if r.supersedes_report_id else None, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}

@router.get("/reports/{report_id}")
def get_report(report_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    report=get_accessible_report(report_id, db, principal)
    return {"report_id":str(report.id),"case_id":str(report.case_id),"analysis_id":str(report.analysis_id),"version":report.report_version,"status":report.status,"language":report.language,"report_type":report.report_type,"artifact_id":str(report.artifact_id) if report.artifact_id else None,"approved_by":str(report.approved_by) if report.approved_by else None,"approved_at":report.approved_at.isoformat() if report.approved_at else None,"content":report.content_json}

@router.post("/reports/{report_id}/finalize")
def finalize(report_id: UUID, payload: ClassificationReviewRequest, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    get_accessible_report(report_id, db, principal); require_role(principal, REPORT_FINALIZE_ROLES)
    try:
        r=finalize_report(db, report_id=report_id, approver_id=principal.user_id, reason=payload.reason)
        db.commit(); return {"report_id":str(r.id),"version":r.report_version,"status":r.status,"approved_by":str(r.approved_by),"approved_at":r.approved_at.isoformat() if r.approved_at else None,"supersedes_report_id":str(r.supersedes_report_id) if r.supersedes_report_id else None}
    except ReportFinalizationError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/analyses/{analysis_id}/reportability/evaluate")
def evaluate_reportability(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal); require_role(principal, CASE_WRITE_ROLES)
    decisions = evaluate_analysis(db, analysis)
    db.commit()
    return {"analysis_id": str(analysis_id), "created": len(decisions), "decisions": [{"decision_id": str(d.id), "variant_id": str(d.variant_id), "classification_id": str(d.classification_id), "version": d.version, "status": d.status, "disposition": d.disposition, "priority_score": d.priority_score, "priority_band": d.priority_band, "reasons": d.reasons} for d in decisions]}

@router.get("/analyses/{analysis_id}/reportability")
def list_reportability(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    from backend.app.infrastructure.db.models import ReportabilityDecision
    rows = list(db.scalars(select(ReportabilityDecision).where(ReportabilityDecision.analysis_id == analysis_id).order_by(ReportabilityDecision.variant_id, ReportabilityDecision.version)))
    latest = {}
    for row in rows: latest[row.variant_id] = row
    return {"analysis_id": str(analysis_id), "items": [{"decision_id": str(d.id), "variant_id": str(d.variant_id), "classification_id": str(d.classification_id), "version": d.version, "status": d.status, "disposition": d.disposition, "priority_score": d.priority_score, "priority_band": d.priority_band, "reasons": d.reasons, "policy_name": d.policy_name, "policy_version": d.policy_version, "review_version": d.review_version, "reviewed_by": str(d.reviewed_by) if d.reviewed_by else None, "approved_at": d.approved_at.isoformat() if d.approved_at else None} for d in latest.values()]}

@router.post("/reportability/{decision_id}/finalize")
def finalize_reportability_decision(decision_id: UUID, payload: ReportabilityDecisionRequest, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    from backend.app.infrastructure.db.models import ReportabilityDecision
    decision = db.get(ReportabilityDecision, decision_id)
    if decision is None: raise HTTPException(status_code=404, detail="Reportability decision not found")
    analysis = get_accessible_analysis(decision.analysis_id, db, principal); require_role(principal, REPORT_FINALIZE_ROLES)
    try:
        out = finalize_reportability(db, decision_id=decision_id, reviewer_id=principal.user_id, expected_version=payload.expected_version, disposition=payload.disposition, reason=payload.reason)
        db.commit()
        return {"decision_id": str(out.id), "analysis_id": str(analysis.id), "variant_id": str(out.variant_id), "version": out.version, "review_version": out.review_version, "status": out.status, "disposition": out.disposition, "priority_score": out.priority_score, "priority_band": out.priority_band, "reviewed_by": str(out.reviewed_by), "approved_at": out.approved_at.isoformat() if out.approved_at else None}
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/cases/{case_id}/exports", status_code=202)
def create_case_export(case_id: UUID, payload: ExportCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case: raise HTTPException(status_code=404, detail="Case not found")
    require_case_tenant(case, principal); require_role(principal, CASE_WRITE_ROLES)
    exp=CaseExport(id=uuid4(), case_id=case_id, requested_by=principal.user_id, status="QUEUED", include_artifacts=payload.include_artifacts, include_reports=payload.include_reports, include_evidence=payload.include_evidence, include_audit=payload.include_audit, include_provenance=payload.include_provenance)
    db.add(exp); AuditService(db).record(event_type="CASE_EXPORT_REQUESTED", case_id=case_id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="CASE_EXPORT", subject_id=str(exp.id), operation="CREATE"); db.commit()
    try: task=run_case_export_task.delay(str(exp.id));
    except RuntimeError:
        return {"export_id":str(exp.id),"status":"QUEUED","executor":"not_available_in_current_environment"}
    return {"export_id":str(exp.id),"status":"QUEUED","task_id":task.id}

@router.get("/exports/{export_id}")
def get_export(export_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    exp=db.get(CaseExport, export_id)
    if not exp: raise HTTPException(status_code=404, detail="Export not found")
    case = db.get(Case, exp.case_id); require_case_tenant(case, principal)
    return {"export_id":str(exp.id),"case_id":str(exp.case_id),"status":exp.status,"artifact_id":str(exp.artifact_id) if exp.artifact_id else None,"error_code":exp.error_code,"error_message":exp.error_message,"created_at":exp.created_at.isoformat() if exp.created_at else None,"completed_at":exp.completed_at.isoformat() if exp.completed_at else None}


@router.get("/exports/{export_id}/download")
def download_case_export(export_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    exp = db.get(CaseExport, export_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Export not found")
    case = db.get(Case, exp.case_id); require_case_tenant(case, principal)
    if exp.status != "SUCCEEDED" or not exp.artifact_id:
        raise HTTPException(status_code=409, detail="Case export is not ready")
    artifact = db.get(__import__("backend.app.infrastructure.db.models", fromlist=["Artifact"]).Artifact, exp.artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Export artifact not found")
    path = ArtifactStore(settings.artifact_root).local_path(artifact.storage_uri)
    return FileResponse(path, media_type="application/zip", filename=artifact.filename)
