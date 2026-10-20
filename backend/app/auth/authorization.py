"""Reusable case-inherited authorization dependencies."""
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import and_, exists, or_, select
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
    CaseAccessGrant,
    Classification,
    Report,
    Specimen,
    Variant,
    WorkflowStep,
    OrganizationMembership,
)
from backend.app.infrastructure.db.session import get_db

READ_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director", "clinical_geneticist", "reviewer", "bioinformatician", "lab_scientist", "read_only"})
CASE_WRITE_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director", "clinical_geneticist", "bioinformatician", "lab_scientist"})
REVIEW_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director", "clinical_geneticist", "reviewer"})
REPORT_FINALIZE_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director", "clinical_geneticist"})
CASE_ACCESS_ADMIN_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director"})
CASE_ACCESS_COLUMNS = {
    "read": CaseAccessGrant.can_read,
    "write": CaseAccessGrant.can_write,
    "review": CaseAccessGrant.can_review,
}
CASE_ROLE_COLUMNS = {
    "read": READ_ROLES,
    "write": CASE_WRITE_ROLES,
    "review": REVIEW_ROLES,
}

def require_role(principal: Principal, roles: frozenset[str]) -> Principal:
    if principal.role not in roles:
        raise HTTPException(status_code=403, detail="Your organization role is not authorized for this operation")
    return principal

def require_case_permission(case: Case, principal: Principal, db: Session, permission: str = "read") -> None:
    """Enforce tenant isolation and a per-case capability, bounded by org role."""
    require_case_tenant(case, principal)
    permission_column = CASE_ACCESS_COLUMNS.get(permission)
    role_set = CASE_ROLE_COLUMNS.get(permission)
    if permission_column is None or role_set is None:
        raise ValueError(f"Unsupported case permission: {permission}")
    membership_query = select(OrganizationMembership).where(
        OrganizationMembership.organization_id == case.organization_id,
        OrganizationMembership.user_id == principal.user_id,
        OrganizationMembership.status == "ACTIVE",
    )
    if permission != "read":
        membership_query = membership_query.with_for_update()
    membership = db.scalar(membership_query)
    if membership is None:
        raise HTTPException(status_code=404, detail="Case not found")
    effective_role = membership.role
    if effective_role in CASE_ACCESS_ADMIN_ROLES:
        return
    grant_query = (
        select(CaseAccessGrant.id)
        .join(
            OrganizationMembership,
            OrganizationMembership.user_id == CaseAccessGrant.user_id,
        )
        .where(
            CaseAccessGrant.case_id == case.id,
            CaseAccessGrant.user_id == principal.user_id,
            permission_column.is_(True),
            OrganizationMembership.organization_id == case.organization_id,
            OrganizationMembership.status == "ACTIVE",
        )
        .limit(1)
    )
    if permission != "read":
        grant_query = grant_query.with_for_update()
    granted = db.scalar(grant_query)
    if granted is None:
        # Hide both foreign-tenant and unassigned cases behind the same response.
        raise HTTPException(status_code=404, detail="Case not found")
    if effective_role not in role_set:
        raise HTTPException(status_code=403, detail="Your organization role is not authorized for this operation")


def case_access_predicate(principal: Principal, permission: str = "read"):
    """SQL predicate for tenant-scoped list endpoints, including grant filtering."""
    permission_column = CASE_ACCESS_COLUMNS.get(permission)
    if permission_column is None:
        raise ValueError(f"Unsupported case permission: {permission}")
    assigned = exists(
            select(CaseAccessGrant.id)
            .join(
                OrganizationMembership,
                OrganizationMembership.user_id == CaseAccessGrant.user_id,
            )
            .where(
                CaseAccessGrant.case_id == Case.id,
                CaseAccessGrant.user_id == principal.user_id,
                permission_column.is_(True),
                OrganizationMembership.organization_id == Case.organization_id,
                OrganizationMembership.status == "ACTIVE",
            )
        )
    current_admin = exists(
        select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == Case.organization_id,
            OrganizationMembership.user_id == principal.user_id,
            OrganizationMembership.status == "ACTIVE",
            OrganizationMembership.role.in_(CASE_ACCESS_ADMIN_ROLES),
        )
    )
    # Determine administrative bypass from the current membership row inside
    # the query. A role change after authentication must not leave a stale
    # administrator principal able to enumerate every case in the tenant.
    return (
        (Case.organization_id == principal.organization_id)
        & (assigned | current_admin)
    )


def case_read_recipient_user_ids(db: Session, *, case_id: UUID, organization_id: UUID) -> set[UUID]:
    """Return active members allowed to read a case for case-scoped notifications."""
    granted_read = exists(
        select(CaseAccessGrant.id).where(
            CaseAccessGrant.case_id == case_id,
            CaseAccessGrant.user_id == OrganizationMembership.user_id,
            CaseAccessGrant.can_read.is_(True),
        )
    )
    rows = db.scalars(
        select(OrganizationMembership.user_id).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.status == "ACTIVE",
            or_(
                OrganizationMembership.role.in_(CASE_ACCESS_ADMIN_ROLES),
                and_(OrganizationMembership.role.in_(READ_ROLES), granted_read),
            ),
        )
    ).all()
    return set(rows)


def get_accessible_case(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal), permission: str = "read") -> Case:
    case = db.get(Case, case_id)
    if not case: raise HTTPException(status_code=404, detail="Case not found")
    require_case_permission(case, principal, db, permission)
    return case

def get_accessible_analysis(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal), permission: str = "read") -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if not analysis: raise HTTPException(status_code=404, detail="Analysis not found")
    case = db.get(Case, analysis.case_id)
    if not case: raise HTTPException(status_code=404, detail="Analysis not found")
    require_case_permission(case, principal, db, permission)
    return analysis

def get_analysis_variant_ids(analysis: Analysis, db: Session) -> set[UUID] | None:
    """Return manifest membership, or None for legacy analyses without a manifest."""
    # The normalization partition manifest is authoritative before annotation.
    partitions = db.scalars(
        select(AnalysisPartition.metadata_json).where(
            AnalysisPartition.analysis_id == analysis.id,
            AnalysisPartition.step_id == "normalize",
        )
    ).all()
    if not partitions:
        normalization_step = db.scalar(
            select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis.id,
                WorkflowStep.step_id == "normalize",
            )
        )
        step_metadata = (
            normalization_step.metadata_json
            if normalization_step and isinstance(normalization_step.metadata_json, dict)
            else {}
        )
        if not (
            normalization_step
            and normalization_step.status == "SUCCEEDED"
            and (
                "partition_count" in step_metadata
                or step_metadata.get("streaming") is True
                or step_metadata.get("normalization") == "REFERENCE_AWARE"
            )
        ):
            return None
        # The current streaming normalizer can successfully produce an empty
        # input. Its successful step metadata is an explicit empty manifest;
        # downstream annotation rows must not activate the legacy fallback.
        return set()

    variant_ids: set[UUID] = set()
    for metadata in partitions:
        raw_variant_ids = metadata.get("variant_ids", []) if isinstance(metadata, dict) else []
        if not isinstance(raw_variant_ids, (list, tuple)):
            continue
        for item in raw_variant_ids:
            try:
                variant_ids.add(UUID(str(item)))
            except (TypeError, ValueError):
                # Ignore malformed manifest entries; they cannot establish membership.
                continue
    return variant_ids


def get_analysis_variant(analysis: Analysis, variant_id: UUID, db: Session) -> Variant:
    """Return a variant only when its identity is present in this analysis."""
    variant = db.get(Variant, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")

    manifest_variant_ids = get_analysis_variant_ids(analysis, db)
    if manifest_variant_ids is not None:
        if variant_id in manifest_variant_ids:
            return variant
        # A present normalization manifest is the durable input-membership
        # record. Downstream rows cannot add variants that were absent from it.
        raise HTTPException(status_code=404, detail="Variant is not part of this analysis")

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

def get_accessible_artifact(artifact_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal), permission: str = "read") -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if not artifact: raise HTTPException(status_code=404, detail="Artifact not found")
    case = db.get(Case, artifact.case_id)
    if not case: raise HTTPException(status_code=404, detail="Artifact not found")
    require_case_permission(case, principal, db, permission)
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

def get_accessible_report(report_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal), permission: str = "read") -> Report:
    report = db.get(Report, report_id)
    if not report: raise HTTPException(status_code=404, detail="Report not found")
    case = db.get(Case, report.case_id)
    if not case: raise HTTPException(status_code=404, detail="Report not found")
    require_case_permission(case, principal, db, permission)
    analysis = db.get(Analysis, report.analysis_id)
    if analysis is None or analysis.case_id != report.case_id:
        raise HTTPException(status_code=404, detail="Report not found")
    if not has_valid_draft_artifact(db, report):
        raise HTTPException(status_code=404, detail="Report not found")
    if getattr(report, "status", None) in {"FINAL", "SUPERSEDED"} and not has_valid_signed_artifact(db, report):
        raise HTTPException(status_code=404, detail="Report not found")
    return report
