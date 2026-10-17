"""Reusable case-inherited authorization dependencies."""
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.auth.principal import Principal, get_current_principal, require_case_tenant
from backend.app.domain.report_integrity import (
    has_valid_draft_artifact,
    has_valid_signed_artifact,
)
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    AnalysisPartition,
    Annotation,
    Artifact,
    Case,
    Classification,
    Report,
    Specimen,
    Variant,
)
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

def get_analysis_variant(analysis: Analysis, variant_id: UUID, db: Session) -> Variant:
    """Return a variant only when its identity is present in this analysis."""
    variant = db.get(Variant, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")

    # The normalization partition manifest is authoritative before annotation.
    partitions = db.scalars(
        select(AnalysisPartition.metadata_json).where(
            AnalysisPartition.analysis_id == analysis.id,
            AnalysisPartition.step_id == "normalize",
        )
    ).all()
    for metadata in partitions:
        variant_ids = metadata.get("variant_ids", []) if isinstance(metadata, dict) else []
        for item in variant_ids:
            try:
                if UUID(str(item)) == variant_id:
                    return variant
            except (TypeError, ValueError):
                # Ignore malformed manifest entries; they cannot establish membership.
                continue

    # Older analyses may not have normalization partitions. Accept only their
    # persisted analysis-scoped annotation/classification lineage as a fallback.
    if db.scalar(
        select(Annotation.id).where(
            Annotation.analysis_id == analysis.id,
            Annotation.variant_id == variant_id,
        ).limit(1)
    ) is not None:
        return variant
    if db.scalar(
        select(Classification.id).where(
            Classification.analysis_id == analysis.id,
            Classification.variant_id == variant_id,
        ).limit(1)
    ) is not None:
        return variant
    if db.scalar(
        select(ACMGAssessment.id).where(
            ACMGAssessment.analysis_id == analysis.id,
            ACMGAssessment.variant_id == variant_id,
        ).limit(1)
    ) is not None:
        return variant
    raise HTTPException(status_code=404, detail="Variant is not part of this analysis")

def get_accessible_artifact(artifact_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if not artifact: raise HTTPException(status_code=404, detail="Artifact not found")
    case = db.get(Case, artifact.case_id)
    if not case: raise HTTPException(status_code=404, detail="Artifact not found")
    require_case_tenant(case, principal)
    if artifact.analysis_id is not None:
        analysis = db.get(Analysis, artifact.analysis_id)
        if analysis is None or analysis.case_id != artifact.case_id:
            raise HTTPException(status_code=404, detail="Artifact not found")
    specimen_id = getattr(artifact, "specimen_id", None)
    if specimen_id is not None:
        specimen = db.get(Specimen, specimen_id)
        if specimen is None or specimen.case_id != artifact.case_id:
            raise HTTPException(status_code=404, detail="Artifact not found")
    paired_artifact_id = getattr(artifact, "paired_artifact_id", None)
    if paired_artifact_id is not None:
        paired_artifact = db.get(Artifact, paired_artifact_id)
        if paired_artifact is None or paired_artifact.case_id != artifact.case_id:
            raise HTTPException(status_code=404, detail="Artifact not found")
    # Report PDFs are also exposed through the generic case artifact listing
    # and download route. Bind either role of PDF to its owning report so a
    # malformed same-tenant artifact link cannot make another report's PDF
    # appear as this report's signed or draft output.
    if artifact.artifact_type == "REPORT_PDF":
        metadata = dict(artifact.metadata_json or {})
        report_id_raw = metadata.get("report_id")
        if report_id_raw is not None:
            try:
                report_id = UUID(str(report_id_raw))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=404, detail="Artifact not found") from exc
            report = db.get(Report, report_id)
        else:
            # Older report PDFs predate explicit report_id metadata. Accept
            # them only when exactly one persisted report points at this PDF.
            matches = list(db.scalars(
                select(Report).where(
                    or_(Report.artifact_id == artifact.id, Report.signed_artifact_id == artifact.id)
                )
            ).all())
            report = matches[0] if len(matches) == 1 else None
        if report_id_raw is not None or report is not None:
            if (
                report is None
                or report.case_id != artifact.case_id
                or report.analysis_id != artifact.analysis_id
                or (
                    metadata.get("report_version") is not None
                    and metadata.get("report_version") != report.report_version
                )
            ):
                raise HTTPException(status_code=404, detail="Artifact not found")
            is_signed_artifact = report.signed_artifact_id == artifact.id
            if is_signed_artifact:
                if (
                    report.status not in {"FINAL", "SUPERSEDED"}
                    or report.signed_sha256 != artifact.sha256
                    or metadata.get("signed") not in (None, True)
                    or metadata.get("report_state") not in (None, "FINAL")
                ):
                    raise HTTPException(status_code=404, detail="Artifact not found")
            elif (
                report.artifact_id != artifact.id
                or metadata.get("signed") is True
                or metadata.get("report_state") not in (None, "DRAFT")
            ):
                raise HTTPException(status_code=404, detail="Artifact not found")
        else:
            raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact

def require_analysis_artifact(analysis: Analysis, artifact_id: UUID, db: Session) -> Artifact:
    """Require an artifact reference to stay inside its owning analysis context."""
    artifact = db.get(Artifact, artifact_id)
    if (
        artifact is None
        or artifact.case_id != analysis.case_id
        or (artifact.analysis_id is not None and artifact.analysis_id != analysis.id)
    ):
        raise HTTPException(
            status_code=409,
            detail="Analysis artifact reference does not match its case and analysis",
        )
    return artifact

def get_accessible_report(report_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)) -> Report:
    report = db.get(Report, report_id)
    if not report: raise HTTPException(status_code=404, detail="Report not found")
    case = db.get(Case, report.case_id)
    if not case: raise HTTPException(status_code=404, detail="Report not found")
    require_case_tenant(case, principal)
    analysis = db.get(Analysis, report.analysis_id)
    if analysis is None or analysis.case_id != report.case_id:
        raise HTTPException(status_code=404, detail="Report not found")
    if not has_valid_draft_artifact(db, report):
        raise HTTPException(status_code=404, detail="Report not found")
    if getattr(report, "status", None) in {"FINAL", "SUPERSEDED"} and not has_valid_signed_artifact(db, report):
        raise HTTPException(status_code=404, detail="Report not found")
    return report
