from uuid import UUID, uuid4
from pathlib import Path
import tempfile
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
from backend.app.reporting.service import build_report_content, render_pdf, render_html, final_report_eligibility
from backend.app.reporting.finalization import finalize_report, ReportFinalizationError
from backend.app.reporting.reportability import evaluate_analysis, finalize_reportability, latest_decision
from backend.app.application.case_export import enqueue_case_export
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.config import settings
from backend.app.infrastructure.audit.service import AuditService
from backend.app.application.analysis import resume_analysis

router = APIRouter(tags=["reports"])

@router.post("/analyses/{analysis_id}/reports", status_code=201)
def create_report(analysis_id: UUID, payload: ReportCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    require_role(principal, CASE_WRITE_ROLES)
    eligible, errors = final_report_eligibility(db, analysis_id=analysis.id)
    if not eligible:
        raise HTTPException(status_code=409, detail="Report generation is blocked until classification review and reportability are finalized: " + "; ".join(errors))
