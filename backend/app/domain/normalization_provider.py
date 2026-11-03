"""Governed execution boundary for VCF normalization engines.

The scientific normalization contract is stable; concrete tools are replaceable.
A resource is executable only after SIRALOOM qualification and the laboratory's
organization-scoped approval/binding have selected it for the analysis profile.

BCFtools is implemented here as the first engine because the existing SIRALOOM
normalization implementation already performs reference-aware normalization,
multiallelic handling, source-record reconciliation, sorting and CSI indexing.
The adapter intentionally does not pin one global version: the selected Resource
version is passed to the executable as an exact runtime expectation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from backend.app.domain.vcf_tools import (
    VCFToolError,
    VCFToolUnavailable,
    normalize_vcf_with_bcftools,
)
from backend.app.infrastructure.db.models import Resource


NORMALIZATION_RESOURCE_TYPE = "NORMALIZATION"
BCFTOOLS_PROVIDER = "bcftools"


class NormalizationProviderError(VCFToolError):
    """Raised when a governed normalization resource cannot be executed."""

    def __init__(self, message: str, *, code: str = "NORMALIZATION_PROVIDER_UNAVAILABLE"):
        super().__init__(message)
        self.code = code


class NormalizationProviderUnavailable(VCFToolUnavailable):
    """A governed provider is temporarily unavailable and should be retried."""

    def __init__(self, message: str, *, code: str = "NORMALIZATION_PROVIDER_UNAVAILABLE"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NormalizationProviderSelection:
    provider: str
    version: str
    executable: str
    resource_id: str
    resource_name: str
    resource_checksum: str | None

    @property
    def snapshot(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "version": self.version,
            "executable": self.executable,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "resource_checksum": self.resource_checksum,
        }


def _metadata_capabilities(resource: Resource) -> set[str]:
    raw = (resource.metadata_json or {}).get("capabilities")
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(value).strip().upper() for value in raw if str(value).strip()}


def resolve_normalization_provider(
    resource: Resource,
    *,
    qualified_executable: str | None = None,
) -> NormalizationProviderSelection:
    """Resolve a selected Resource into an executable normalization provider.

    The resource's version is authoritative. No latest-version lookup and no
    settings-level version override are allowed here. This is what permits a
    laboratory to retain an older approved release while a newer qualified
    release is merely available for approval.

    Approval itself is enforced by ``resolve_approved_normalization_resource``;
    this function only validates the already-selected resource contract.
    """
    if resource.resource_type.strip().upper() != NORMALIZATION_RESOURCE_TYPE:
        raise NormalizationProviderError(
            f"Resource {resource.id} is not a normalization resource.",
            code="NORMALIZATION_RESOURCE_TYPE_INVALID",
        )
    if resource.status not in {"QUALIFIED", "ACTIVE", "SUPERSEDED"}:
        raise NormalizationProviderError(
            f"Normalization resource {resource.id} is not technically qualified for execution.",
            code="NORMALIZATION_RESOURCE_NOT_QUALIFIED",
        )
    capabilities = _metadata_capabilities(resource)
    if "NORMALIZATION" not in capabilities:
        raise NormalizationProviderError(
            "Normalization resource does not declare the NORMALIZATION capability.",
            code="NORMALIZATION_CAPABILITY_MISSING",
        )

    provider = resource.provider.strip().casefold()
    if provider != BCFTOOLS_PROVIDER:
        raise NormalizationProviderError(
            f"No executable normalization adapter is registered for provider {resource.provider!r}.",
            code="NORMALIZATION_PROVIDER_NOT_IMPLEMENTED",
        )
    if not resource.version.strip():
        raise NormalizationProviderError(
            "A normalization resource must declare an exact tool version.",
            code="NORMALIZATION_VERSION_MISSING",
        )

    execution = dict((resource.metadata_json or {}).get("execution") or {})
    toolchain = dict(execution.get("toolchain") or {})
    bcftools_tool = dict(toolchain.get("bcftools") or {})
    declared_version = str(bcftools_tool.get("version") or "").strip()
    if declared_version and declared_version != resource.version.strip():
        raise NormalizationProviderError(
            "The BCFtools toolchain version does not match the qualified Resource version.",
            code="NORMALIZATION_EXECUTION_VERSION_CONTRACT_MISMATCH",
        )
    executable = str(
        qualified_executable
        or bcftools_tool.get("executable")
        or execution.get("executable")
        or "bcftools"
    ).strip()
    if not executable:
        executable = "bcftools"

    return NormalizationProviderSelection(
        provider=BCFTOOLS_PROVIDER,
        version=resource.version.strip(),
        executable=executable,
        resource_id=str(resource.id),
        resource_name=resource.name,
        resource_checksum=resource.checksum,
    )


def normalize_with_selected_provider(
    resource: Resource,
    input_path: str | Path,
    output_path: str | Path,
    *,
    reference_fasta: str | Path,
    approved: bool,
    expected_bcftools_sha256: str | None = None,
    qualified_bcftools_executable: str | None = None,
    source_only_format_fields: list[str] | None = None,
) -> tuple[dict, NormalizationProviderSelection]:
    """Execute the exact approved normalization release selected for an analysis."""
    if not approved:
        raise NormalizationProviderError(
            "Normalization execution requires an organization-approved resource binding.",
            code="NORMALIZATION_LAB_APPROVAL_REQUIRED",
        )
    selection = resolve_normalization_provider(
        resource,
        qualified_executable=qualified_bcftools_executable,
    )
    expected_digest = str(expected_bcftools_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise NormalizationProviderError(
            "The qualified normalization execution contract has no valid BCFtools executable SHA-256.",
            code="NORMALIZATION_EXECUTABLE_SHA256_NOT_QUALIFIED",
        )
    try:
        result = normalize_vcf_with_bcftools(
            input_path,
            output_path,
            reference_fasta=reference_fasta,
            expected_bcftools_version=selection.version,
            source_only_format_fields=source_only_format_fields,
            bcftools_executable=selection.executable,
            expected_bcftools_sha256=expected_bcftools_sha256,
        )
    except VCFToolUnavailable as exc:
        tool_error_code = getattr(exc, "code", None)
        provider_error_code = (
            "NORMALIZATION_PROVIDER_UNAVAILABLE"
            if tool_error_code in {None, "VCF_TOOL_UNAVAILABLE"}
            else tool_error_code
        )
        raise NormalizationProviderUnavailable(
            str(exc),
            code=provider_error_code,
        ) from exc
    except VCFToolError as exc:
        raise NormalizationProviderError(
            str(exc),
            code=getattr(exc, "code", None) or "NORMALIZATION_EXECUTION_FAILED",
        ) from exc
    result["provider_resource_id"] = selection.resource_id
    result["provider_resource_name"] = selection.resource_name
    result["provider_resource_checksum"] = selection.resource_checksum
    result["provider_executable"] = selection.executable
    result["provider_version"] = selection.version
    return result, selection
