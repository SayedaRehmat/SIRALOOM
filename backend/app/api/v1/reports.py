import tempfile
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from backend.app.application.analysis import resume_analysis
from backend.app.application.case_export import enqueue_case_export
from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    REPORT_FINALIZE_ROLES,
    get_accessible_analysis,
    get_accessible_report,
    get_analysis_variant,
    require_role,
)
from backend.app.auth.principal import Principal, get_current_principal, require_case_tenant
from backend.app.domain.artifact_integrity import (
    ArtifactIntegrityError,
    stage_verified_cloud_artifact,
    verify_artifact_file,
)
from backend.app.domain.enums import AnalysisStatus
from backend.app.domain.review import ClassificationReviewRequest
from backend.app.domain.schemas import ExportCreate, ReportabilityDecisionRequest, ReportCreate
from backend.app.domain.storage_profiles import StorageProfileError, artifact_store_for_organization
from backend.app.infrastructure.artifacts.compensation import (
    commit_with_artifact_compensation,
    compensate_uncommitted_artifact,
)
from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, CaseExport, Report
from backend.app.domain.report_integrity import (
    has_valid_draft_artifact,
    has_valid_signed_artifact,
)
from backend.app.infrastructure.db.session import get_db
from backend.app.reporting.finalization import ReportFinalizationError, finalize_report
from backend.app.reporting.reportability import (
    evaluate_analysis,
    finalize_reportability,
    is_current_approved_reportability_decision,
)
from backend.app.reporting.service import (
    build_report_content,
    final_report_eligibility,
    render_pdf,
)

router = APIRouter(tags=["reports"])


def _require_reportability_variant(analysis, variant_id: UUID, db: Session) -> None:
    try:
        get_analysis_variant(analysis, variant_id, db)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=409,
                detail="Reportability decision references a variant outside its analysis",
            ) from exc
        raise


def _accessible_case_export(export_id: UUID, db: Session, principal: Principal):
    export = db.get(CaseExport, export_id)
    case = db.get(Case, export.case_id) if export is not None else None
    if export is None or case is None or case.organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Export not found")
    return export, case

@router.post("/analyses/{analysis_id}/reports", status_code=201)
def create_report(analysis_id: UUID, payload: ReportCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    require_role(principal, CASE_WRITE_ROLES)

    # Report version allocation is a case-scoped clinical history mutation.
    # Lock the case before eligibility/version allocation so concurrent requests serialize.
    case = db.get(Case, analysis.case_id, with_for_update=True)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    db.refresh(case, with_for_update=True)

    eligible, errors = final_report_eligibility(db, analysis_id=analysis.id)
    if not eligible:
        raise HTTPException(status_code=409, detail="Report generation is blocked until classification review and reportability are finalized: " + "; ".join(errors))

    content = build_report_content(
        db,
        analysis,
        payload.language,
        report_type=payload.report_type,
        include_full_evidence=payload.include_full_evidence,
    )
    last = db.scalar(
        select(func.max(Report.report_version)).where(
            Report.case_id == analysis.case_id,
            Report.report_type == payload.report_type,
        )
    ) or 0
    version = int(last) + 1
    content["report_version"] = version

    report = Report(
        id=uuid4(),
        case_id=analysis.case_id,
        analysis_id=analysis.id,
        report_version=version,
        language=payload.language,
        report_type=payload.report_type,
        status="DRAFT",
        artifact_id=None,
        content_json=content,
    )
    db.add(report)
    db.flush()

    draft_artifact_id = uuid5(
        NAMESPACE_URL,
        f"siraloom:draft-report:{analysis.case_id}:{payload.report_type}:{version}",
    )
    pdf = render_pdf(content)
    try:
        store = artifact_store_for_organization(db, organization_id=case.organization_id)
    except StorageProfileError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    with tempfile.NamedTemporaryFile(prefix="siraloom-report-draft-", suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf)
        draft_path = Path(tmp.name)
    try:
        artifact = store.put_file(
            db=db,
            case_id=analysis.case_id,
            analysis_id=analysis.id,
            source_path=draft_path,
            filename=f"report_v{version}_draft.pdf",
            artifact_type="REPORT_PDF",
            media_type="application/pdf",
            genome_build=analysis.reference_build,
            metadata={
                "rendered_format": "PDF",
                "report_schema_version": content["report_schema_version"],
                "report_state": "DRAFT",
                "report_id": str(report.id),
                "report_version": report.report_version,
            },
            validation_status="VALID",
            artifact_id=draft_artifact_id,
        )
    finally:
        draft_path.unlink(missing_ok=True)

    report.artifact_id = artifact.id
    try:
        AuditService(db).record(
            event_type="REPORT_GENERATED",
            case_id=analysis.case_id,
            analysis_id=analysis.id,
            actor_type="HUMAN",
            actor_id=str(principal.user_id),
            subject_type="REPORT",
            subject_id=str(report.id),
            operation="CREATE",
            output_artifacts=[{"artifact_id": str(artifact.id), "sha256": artifact.sha256}],
            payload={"draft": True, "reportability_final": True},
        )
    except Exception:
        # put_file may already have written external bytes. An audit-flush
        # failure aborts the report transaction, so remove those bytes only
        # after a fresh session confirms the artifact row did not commit.
        compensate_uncommitted_artifact(db, store, artifact.id, artifact.storage_uri)
        raise
    try:
        commit_with_artifact_compensation(db, store, artifact)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Report version was allocated concurrently; retry report generation.") from exc
    return {
        "report_id": str(report.id),
        "version": version,
        "artifact_id": str(artifact.id),
        "status": report.status,
        "signed_artifact_id": None,
        "signed_sha256": None,
    }

@router.get("/analyses/{analysis_id}/reports")
def list_reports(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    rows = list(db.scalars(select(Report).where(Report.analysis_id == analysis.id).order_by(Report.report_version.desc())))
    if any(row.case_id != analysis.case_id for row in rows):
        raise HTTPException(
            status_code=409,
            detail="Report case does not match its analysis",
        )
    for row in rows:
        if not has_valid_draft_artifact(db, row):
            raise HTTPException(
                status_code=409,
                detail="Report draft artifact does not match its case and analysis",
            )
        if row.status in {"FINAL", "SUPERSEDED"} and not has_valid_signed_artifact(db, row):
            raise HTTPException(
                status_code=409,
                detail="Final or superseded report is missing a valid linked signed artifact",
            )
    return {"analysis_id": str(analysis_id), "items": [{"report_id": str(r.id), "case_id": str(r.case_id), "version": r.report_version, "status": r.status, "language": r.language, "report_type": r.report_type, "artifact_id": str(r.artifact_id) if r.artifact_id else None, "signed_artifact_id": str(r.signed_artifact_id) if r.signed_artifact_id else None, "signed_sha256": r.signed_sha256, "signout_reason": r.signout_reason, "approved_by": str(r.approved_by) if r.approved_by else None, "approved_at": r.approved_at.isoformat() if r.approved_at else None, "supersedes_report_id": str(r.supersedes_report_id) if r.supersedes_report_id else None, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}

@router.get("/reports/{report_id}")
def get_report(report_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    report=get_accessible_report(report_id, db, principal)
    return {"report_id":str(report.id),"case_id":str(report.case_id),"analysis_id":str(report.analysis_id),"version":report.report_version,"status":report.status,"language":report.language,"report_type":report.report_type,"artifact_id":str(report.artifact_id) if report.artifact_id else None,"signed_artifact_id":str(report.signed_artifact_id) if report.signed_artifact_id else None,"signed_sha256":report.signed_sha256,"signout_reason":report.signout_reason,"approved_by":str(report.approved_by) if report.approved_by else None,"approved_at":report.approved_at.isoformat() if report.approved_at else None,"content":report.content_json}

@router.post("/reports/{report_id}/finalize")
def finalize(report_id: UUID, payload: ClassificationReviewRequest, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    report = get_accessible_report(report_id, db, principal); require_role(principal, REPORT_FINALIZE_ROLES)
    if report.status == "FINAL":
        if not payload.reason.strip():
            raise HTTPException(status_code=409, detail="Approval reason is required")
        # The shared accessor already verified the durable signed artifact.
        # A retry after a lost response must not depend on today's storage
        # profile: the immutable sign-out has already committed. Preserve the
        # existing recovery behavior if workflow resumption is still needed.
        analysis = db.get(Analysis, report.analysis_id)
        resume_queued = False
        if analysis is not None and analysis.status in {
            AnalysisStatus.REQUIRES_REVIEW,
            AnalysisStatus.QUEUED,
            AnalysisStatus.RUNNING,
        }:
            try:
                resume_queued = resume_analysis(db, report.analysis_id) is not None
            except ValueError as exc:
                db.rollback()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "report_id": str(report.id),
            "version": report.report_version,
            "status": report.status,
            "approved_by": str(report.approved_by),
            "approved_at": report.approved_at.isoformat() if report.approved_at else None,
            "supersedes_report_id": str(report.supersedes_report_id) if report.supersedes_report_id else None,
            "workflow_resume_queued": resume_queued,
        }
    if report.status != "DRAFT":
        raise HTTPException(status_code=409, detail=f"Report cannot be finalized from status {report.status}")
    if payload.expected_version != report.report_version:
        raise HTTPException(
            status_code=409,
            detail="Report version changed. Refresh the report before signing out.",
        )
    case = db.get(Case, report.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Report case not found")
    signed_artifact_id = uuid5(report.id, "siraloom:signed-report-pdf")
    signed_filename = f"report_v{report.report_version}_signed.pdf"
    try:
        store = artifact_store_for_organization(db, organization_id=case.organization_id)
        signed_uri = store.uri_for_artifact(
            case_id=report.case_id,
            artifact_id=signed_artifact_id,
            filename=signed_filename,
        )
    except StorageProfileError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        r=finalize_report(db, report_id=report_id, approver_id=principal.user_id, reason=payload.reason)
        resume_queued = False
        if r.status == "FINAL":
            # A repeated sign-out must remain successful after the analysis has
            # completed. Resume only when the analysis is at a resumable human
            # gate; an already queued/running analysis is handled idempotently by
            # resume_analysis, while terminal states must not be restarted here.
            analysis = db.get(Analysis, r.analysis_id)
            if analysis is not None and analysis.status in {
                AnalysisStatus.REQUIRES_REVIEW,
                AnalysisStatus.QUEUED,
                AnalysisStatus.RUNNING,
            }:
                try:
                    # Persist the sign-out mutation and durable resume intent together;
                    # broker publication is handled by the analysis outbox.
                    resume_queued = resume_analysis(db, r.analysis_id) is not None
                except ValueError as exc:
                    db.rollback()
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
            else:
                signed_artifact = db.get(Artifact, r.signed_artifact_id)
                if signed_artifact is None:
                    raise ReportFinalizationError("Final report signed artifact metadata is missing")
                commit_with_artifact_compensation(db, store, signed_artifact)
        else:
            signed_artifact = db.get(Artifact, r.signed_artifact_id)
            if signed_artifact is None:
                raise ReportFinalizationError("Final report signed artifact metadata is missing")
            commit_with_artifact_compensation(db, store, signed_artifact)
        return {"report_id":str(r.id),"version":r.report_version,"status":r.status,"approved_by":str(r.approved_by),"approved_at":r.approved_at.isoformat() if r.approved_at else None,"supersedes_report_id":str(r.supersedes_report_id) if r.supersedes_report_id else None,"workflow_resume_queued":resume_queued}
    except ReportFinalizationError as exc:
        compensate_uncommitted_artifact(db, store, signed_artifact_id, signed_uri)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        compensate_uncommitted_artifact(db, store, signed_artifact_id, signed_uri)
        raise

@router.post("/analyses/{analysis_id}/reportability/evaluate")
def evaluate_reportability(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal); require_role(principal, CASE_WRITE_ROLES)
    try:
        decisions = evaluate_analysis(db, analysis)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"analysis_id": str(analysis_id), "created": len(decisions), "decisions": [{"decision_id": str(d.id), "variant_id": str(d.variant_id), "classification_id": str(d.classification_id), "version": d.version, "status": d.status, "disposition": d.disposition, "priority_score": d.priority_score, "priority_band": d.priority_band, "reasons": d.reasons} for d in decisions]}

@router.get("/analyses/{analysis_id}/reportability")
def list_reportability(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    from backend.app.infrastructure.db.models import ReportabilityDecision
    rows = list(db.scalars(select(ReportabilityDecision).where(ReportabilityDecision.analysis_id == analysis_id).order_by(ReportabilityDecision.variant_id, ReportabilityDecision.version)))
    latest = {}
    for row in rows:
        _require_reportability_variant(analysis, row.variant_id, db)
        latest[row.variant_id] = row
    if any(
        not is_current_approved_reportability_decision(db, decision)
        for decision in latest.values()
    ):
        raise HTTPException(
            status_code=409,
            detail="Reportability decision is not linked to the latest approved classification",
        )
    return {"analysis_id": str(analysis_id), "items": [{"decision_id": str(d.id), "variant_id": str(d.variant_id), "classification_id": str(d.classification_id), "version": d.version, "status": d.status, "disposition": d.disposition, "priority_score": d.priority_score, "priority_band": d.priority_band, "reasons": d.reasons, "policy_name": d.policy_name, "policy_version": d.policy_version, "review_version": d.review_version, "reviewed_by": str(d.reviewed_by) if d.reviewed_by else None, "approved_at": d.approved_at.isoformat() if d.approved_at else None} for d in latest.values()]}

@router.post("/reportability/{decision_id}/finalize")
def finalize_reportability_decision(decision_id: UUID, payload: ReportabilityDecisionRequest, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    from backend.app.infrastructure.db.models import ReportabilityDecision
    decision = db.get(ReportabilityDecision, decision_id)
    if decision is None: raise HTTPException(status_code=404, detail="Reportability decision not found")
    try:
        analysis = get_accessible_analysis(decision.analysis_id, db, principal)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Reportability decision not found") from exc
        raise
    require_role(principal, REPORT_FINALIZE_ROLES)
    _require_reportability_variant(analysis, decision.variant_id, db)
    try:
        out = finalize_reportability(db, decision_id=decision_id, reviewer_id=principal.user_id, expected_version=payload.expected_version, disposition=payload.disposition, reason=payload.reason)
        resume_queued = False
        if out.status == "FINAL" and analysis.status in {
            AnalysisStatus.REQUIRES_REVIEW,
            AnalysisStatus.QUEUED,
            AnalysisStatus.RUNNING,
        }:
            try:
                # Persist reportability sign-off and durable resume intent in the
                # same transaction; the outbox closes the post-commit publish gap.
                resume_queued = resume_analysis(db, analysis.id) is not None
            except ValueError as exc:
                db.rollback()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        # resume_analysis commits when it creates a dispatch, but its idempotent
        # QUEUED/RUNNING paths return without committing this sign-off mutation.
        # Commit here as well; this is a no-op after a dispatch commit.
        db.commit()
        return {"decision_id": str(out.id), "analysis_id": str(analysis.id), "variant_id": str(out.variant_id), "version": out.version, "review_version": out.review_version, "status": out.status, "disposition": out.disposition, "priority_score": out.priority_score, "priority_band": out.priority_band, "reviewed_by": str(out.reviewed_by), "approved_at": out.approved_at.isoformat() if out.approved_at else None, "workflow_resume_queued": resume_queued}
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/cases/{case_id}/exports", status_code=202)
def create_case_export(case_id: UUID, payload: ExportCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case: raise HTTPException(status_code=404, detail="Case not found")
    require_case_tenant(case, principal); require_role(principal, CASE_WRITE_ROLES)
    exp=CaseExport(id=uuid4(), case_id=case_id, requested_by=principal.user_id, status="QUEUED", include_artifacts=payload.include_artifacts, include_reports=payload.include_reports, include_evidence=payload.include_evidence, include_audit=payload.include_audit, include_provenance=payload.include_provenance)
    db.add(exp)
    AuditService(db).record(
        event_type="CASE_EXPORT_REQUESTED",
        case_id=case_id,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="CASE_EXPORT",
        subject_id=str(exp.id),
        operation="CREATE",
    )
    db.commit()
    dispatch_id = enqueue_case_export(db, exp)
    return {"export_id": str(exp.id), "status": "QUEUED", "task_id": dispatch_id}

@router.get("/exports/{export_id}")
def get_export(export_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    exp, case = _accessible_case_export(export_id, db, principal)
    return {"export_id":str(exp.id),"case_id":str(exp.case_id),"status":exp.status,"artifact_id":str(exp.artifact_id) if exp.artifact_id else None,"error_code":exp.error_code,"error_message":("Case export failed. Contact a laboratory administrator." if exp.status == "FAILED" else None),"created_at":exp.created_at.isoformat() if exp.created_at else None,"completed_at":exp.completed_at.isoformat() if exp.completed_at else None}


@router.get("/exports/{export_id}/download")
def download_case_export(export_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    exp, case = _accessible_case_export(export_id, db, principal)
    if exp.status != "SUCCEEDED" or not exp.artifact_id:
        raise HTTPException(status_code=409, detail="Case export is not ready")
    artifact = db.get(Artifact, exp.artifact_id)
    metadata = dict(artifact.metadata_json or {}) if artifact is not None else {}
    if (
        artifact is None
        or artifact.case_id != case.id
        or artifact.analysis_id is not None
        or artifact.artifact_type != "AUDIT_PACKAGE"
        or metadata.get("export_id") != str(exp.id)
        or not isinstance(artifact.sha256, str)
        or len(artifact.sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in artifact.sha256)
    ):
        raise HTTPException(status_code=404, detail="Export artifact not found")
    try:
        store = artifact_store_for_organization(
            db,
            organization_id=case.organization_id,
        )
    except StorageProfileError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Resolve the export through the same organization-selected store that
    # created it. A cloud URI must never be treated as a local filesystem path.
    if isinstance(store, FirebaseArtifactStore):
        if store.uri_for_artifact(
            case_id=artifact.case_id,
            artifact_id=artifact.id,
            filename=artifact.filename,
        ) != artifact.storage_uri:
            raise HTTPException(status_code=404, detail="Export artifact not found")
        try:
            path = stage_verified_cloud_artifact(
                store,
                artifact,
                prefix="siraloom-export-download-",
            )
        except ArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=503,
                detail="Export artifact is unavailable or failed integrity verification.",
            ) from exc
        return FileResponse(
            path,
            media_type=artifact.media_type or "application/zip",
            filename=Path(artifact.filename).name,
            headers={"X-Content-Type-Options": "nosniff"},
            background=BackgroundTask(path.unlink, missing_ok=True),
        )

    try:
        if store.uri_for_artifact(
            case_id=artifact.case_id,
            artifact_id=artifact.id,
            filename=artifact.filename,
        ) != artifact.storage_uri:
            raise HTTPException(status_code=404, detail="Export artifact not found")
        path = store.local_path(artifact.storage_uri)
        verify_artifact_file(path, sha256=artifact.sha256, size_bytes=artifact.size_bytes)
    except ArtifactIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Export artifact is unavailable or failed integrity verification.",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=409,
            detail="Export artifact is unavailable or failed integrity verification.",
        ) from exc
    except (AttributeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Export artifact storage URI is incompatible with the organization's configured storage profile.",
        ) from exc
    return FileResponse(
        path,
        media_type=artifact.media_type or "application/zip",
        filename=Path(artifact.filename).name,
        headers={"X-Content-Type-Options": "nosniff"},
    )
