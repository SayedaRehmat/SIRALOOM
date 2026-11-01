"""Case status transitions derived from persisted primary VCF intake."""

from backend.app.domain.enums import CaseStatus


_INTAKE_STATUSES = frozenset(
    {
        CaseStatus.DRAFT,
        CaseStatus.SPECIMEN_REGISTERED,
        CaseStatus.ARTIFACT_UPLOADED,
        CaseStatus.VALIDATING,
        CaseStatus.READY_FOR_ANALYSIS,
        CaseStatus.INVALID,
    }
)


def case_status_after_vcf_upload(
    current_status: str,
    *,
    has_analysis_ready_vcf: bool,
    has_vcf: bool,
    has_site_only_vcf: bool = False,
) -> str:
    """Recompute case intake status from explicitly accepted analysis inputs.

    Structural VCF validity is necessary but insufficient for analysis readiness:
    reference verification, assay/caller qualification, specimen reconciliation,
    and the applicable laboratory QC decision are separate gates. Only a VCF
    carrying the explicit ANALYSIS_READY eligibility decision may advance the case.
    """
    if current_status not in _INTAKE_STATUSES:
        return current_status
    if has_analysis_ready_vcf:
        return CaseStatus.READY_FOR_ANALYSIS
    if has_site_only_vcf:
        # A conformant site-level VCF is not a patient callset; keep the case
        # at artifact intake rather than marking it clinically ready or invalid.
        return CaseStatus.ARTIFACT_UPLOADED
    if has_vcf:
        return CaseStatus.INVALID
    return current_status
