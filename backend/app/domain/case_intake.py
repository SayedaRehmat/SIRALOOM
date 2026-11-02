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
    has_valid_vcf: bool,
    has_vcf: bool,
    has_site_only_vcf: bool = False,
    has_blocked_vcf: bool = False,
) -> str:
    """Recompute intake status without regressing a case already in later workflow."""
    if current_status not in _INTAKE_STATUSES:
        return current_status
    if has_valid_vcf:
        return CaseStatus.READY_FOR_ANALYSIS
    if has_site_only_vcf or has_blocked_vcf:
        # A conformant site-level VCF or a future-specification governance
        # block is retained at artifact intake; neither is a malformed VCF or
        # evidence that the case is ready for clinical analysis.
        return CaseStatus.ARTIFACT_UPLOADED
    if has_vcf:
        return CaseStatus.INVALID
    return current_status
