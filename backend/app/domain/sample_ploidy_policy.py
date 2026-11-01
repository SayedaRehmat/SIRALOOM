"""Explicit, provenance-backed sample ploidy evidence and caller policy resolution.

This module never infers chromosome copy number from pedigree sex, karyotype
strings, GT, allele balance, or observed X/Y calls. It resolves an expected
VCF GT ploidy only when specimen-level region copy-number evidence and an
exact, qualified caller+assay policy are both supplied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from backend.app.domain.sex_chromosome_regions import normalize_human_reference_build

SEX_CHROMOSOME_REGIONS = frozenset({"PAR", "X_NON_PAR", "Y_NON_PAR"})
_EVIDENCE_STATUSES = frozenset({"VERIFIED", "UNVERIFIED", "CONFLICTED", "MOSAIC_OR_COMPLEX"})
_CALLER_POLICY_STATUSES = frozenset({"QUALIFIED", "DRAFT", "RETIRED"})


class PloidyPolicyValidationError(ValueError):
    """Raised when an explicit ploidy evidence or caller policy payload is malformed."""


@dataclass(frozen=True)
class SamplePloidyEvidence:
    specimen_id: str
    reference_build: str
    status: str
    region_copy_number: Mapping[str, int]
    source_type: str | None
    evidence_reference: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None


@dataclass(frozen=True)
class CallerPloidyPolicy:
    caller_id: str
    caller_version: str
    assay_id: str
    policy_version: str
    reference_build: str
    status: str
    validation_evidence_reference: str | None
    qualified_by: str | None
    qualified_at: datetime | None
    region_copy_number_to_gt_ploidy: Mapping[str, Mapping[int, int | str]]


@dataclass(frozen=True)
class PloidyResolution:
    status: str
    reason_code: str
    region: str
    reference_build: str
    specimen_id: str | None = None
    copy_number: int | None = None
    expected_gt_ploidy: int | None = None
    caller_id: str | None = None
    caller_version: str | None = None
    assay_id: str | None = None
    caller_policy_version: str | None = None
    evidence_reference: str | None = None
    evidence_source_type: str | None = None
    evidence_reviewed_by: str | None = None
    evidence_reviewed_at: datetime | None = None
    caller_validation_evidence_reference: str | None = None
    caller_qualified_by: str | None = None
    caller_qualified_at: datetime | None = None


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PloidyPolicyValidationError(f"{key} must be a non-empty string")
    return value.strip()


def _parse_aware_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PloidyPolicyValidationError(f"{field_name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PloidyPolicyValidationError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PloidyPolicyValidationError(f"{field_name} must include a timezone offset")
    return parsed


def parse_sample_ploidy_evidence(payload: Mapping[str, Any]) -> SamplePloidyEvidence:
    """Validate the versioned specimen-level copy-number evidence contract."""
    if not isinstance(payload, Mapping):
        raise PloidyPolicyValidationError("Sample ploidy evidence must be an object")
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise PloidyPolicyValidationError("Unsupported sample ploidy evidence schema_version")
    allowed_keys = {"schema_version", "specimen_id", "reference_build", "status", "region_copy_number", "source_type", "evidence_reference", "reviewed_by", "reviewed_at"}
    if set(payload) - allowed_keys:
        raise PloidyPolicyValidationError(f"Unsupported sample ploidy evidence fields: {sorted(set(payload) - allowed_keys)}")
    try:
        specimen_id = str(UUID(_required_text(payload, "specimen_id")))
    except ValueError as exc:
        raise PloidyPolicyValidationError("specimen_id must be a UUID") from exc
    try:
        build = normalize_human_reference_build(_required_text(payload, "reference_build"))
    except ValueError as exc:
        raise PloidyPolicyValidationError(str(exc)) from exc
    status = _required_text(payload, "status").upper()
    if status not in _EVIDENCE_STATUSES:
        raise PloidyPolicyValidationError(f"Unsupported sample ploidy evidence status: {status}")

    raw_copy_number = payload.get("region_copy_number", {})
    if not isinstance(raw_copy_number, Mapping):
        raise PloidyPolicyValidationError("region_copy_number must be an object")
    unknown_regions = set(raw_copy_number) - SEX_CHROMOSOME_REGIONS
    if unknown_regions:
        raise PloidyPolicyValidationError(f"Unsupported sex-chromosome regions: {sorted(unknown_regions)}")
    copy_number: dict[str, int] = {}
    for region, value in raw_copy_number.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PloidyPolicyValidationError(f"Copy number for {region} must be a non-negative integer")
        copy_number[region] = value

    source_type = payload.get("source_type")
    evidence_reference = payload.get("evidence_reference")
    reviewed_by = payload.get("reviewed_by")
    reviewed_at = None
    if status == "VERIFIED":
        if not copy_number:
            raise PloidyPolicyValidationError("Verified evidence requires at least one region copy-number assertion")
        for key, value in (
            ("source_type", source_type),
            ("evidence_reference", evidence_reference),
            ("reviewed_by", reviewed_by),
        ):
            if not isinstance(value, str) or not value.strip():
                raise PloidyPolicyValidationError(f"Verified evidence requires {key}")
        reviewed_at = _parse_aware_datetime(payload.get("reviewed_at"), "reviewed_at")
    else:
        source_type = source_type.strip() if isinstance(source_type, str) and source_type.strip() else None
        evidence_reference = evidence_reference.strip() if isinstance(evidence_reference, str) and evidence_reference.strip() else None
        reviewed_by = reviewed_by.strip() if isinstance(reviewed_by, str) and reviewed_by.strip() else None
        if payload.get("reviewed_at") is not None:
            reviewed_at = _parse_aware_datetime(payload.get("reviewed_at"), "reviewed_at")

    return SamplePloidyEvidence(
        specimen_id=specimen_id,
        reference_build=build,
        status=status,
        region_copy_number=copy_number,
        source_type=source_type.strip() if isinstance(source_type, str) and source_type.strip() else None,
        evidence_reference=evidence_reference.strip() if isinstance(evidence_reference, str) and evidence_reference.strip() else None,
        reviewed_by=reviewed_by.strip() if isinstance(reviewed_by, str) and reviewed_by.strip() else None,
        reviewed_at=reviewed_at,
    )


def parse_caller_ploidy_policy(payload: Mapping[str, Any]) -> CallerPloidyPolicy:
    """Validate caller/assay/version-specific copy-number-to-GT encoding policy."""
    if not isinstance(payload, Mapping):
        raise PloidyPolicyValidationError("Caller ploidy policy must be an object")
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise PloidyPolicyValidationError("Unsupported caller ploidy policy schema_version")
    allowed_keys = {"schema_version", "caller_id", "caller_version", "assay_id", "policy_version", "reference_build", "status", "validation_evidence_reference", "qualified_by", "qualified_at", "region_copy_number_to_gt_ploidy"}
    if set(payload) - allowed_keys:
        raise PloidyPolicyValidationError(f"Unsupported caller policy fields: {sorted(set(payload) - allowed_keys)}")
    caller_id = _required_text(payload, "caller_id")
    caller_version = _required_text(payload, "caller_version")
    assay_id = _required_text(payload, "assay_id")
    policy_version = _required_text(payload, "policy_version")
    try:
        build = normalize_human_reference_build(_required_text(payload, "reference_build"))
    except ValueError as exc:
        raise PloidyPolicyValidationError(str(exc)) from exc
    status = _required_text(payload, "status").upper()
    if status not in _CALLER_POLICY_STATUSES:
        raise PloidyPolicyValidationError(f"Unsupported caller policy status: {status}")

    raw_regions = payload.get("region_copy_number_to_gt_ploidy", {})
    if not isinstance(raw_regions, Mapping):
        raise PloidyPolicyValidationError("region_copy_number_to_gt_ploidy must be an object")
    unknown_regions = set(raw_regions) - SEX_CHROMOSOME_REGIONS
    if unknown_regions:
        raise PloidyPolicyValidationError(f"Unsupported caller-policy regions: {sorted(unknown_regions)}")
    region_policies: dict[str, dict[int, int | str]] = {}
    for region, raw_mapping in raw_regions.items():
        if not isinstance(raw_mapping, Mapping):
            raise PloidyPolicyValidationError(f"Caller policy for {region} must be an object")
        mapping: dict[int, int | str] = {}
        for raw_copy_number, gt_ploidy in raw_mapping.items():
            try:
                copy_number = int(raw_copy_number)
            except (TypeError, ValueError) as exc:
                raise PloidyPolicyValidationError(f"Invalid copy-number key for {region}: {raw_copy_number!r}") from exc
            if str(copy_number) != str(raw_copy_number) or copy_number < 0:
                raise PloidyPolicyValidationError(f"Invalid copy-number key for {region}: {raw_copy_number!r}")
            if gt_ploidy == "NOT_CALLABLE":
                mapping[copy_number] = "NOT_CALLABLE"
            elif isinstance(gt_ploidy, int) and not isinstance(gt_ploidy, bool) and gt_ploidy > 0:
                mapping[copy_number] = gt_ploidy
            else:
                raise PloidyPolicyValidationError(
                    f"Policy value for {region} copy number {copy_number} must be a positive GT ploidy or NOT_CALLABLE"
                )
        region_policies[region] = mapping

    validation_reference = payload.get("validation_evidence_reference")
    qualified_by = payload.get("qualified_by")
    qualified_at = None
    if status == "QUALIFIED":
        for key, value in (
            ("validation_evidence_reference", validation_reference),
            ("qualified_by", qualified_by),
        ):
            if not isinstance(value, str) or not value.strip():
                raise PloidyPolicyValidationError(f"Qualified caller policy requires {key}")
        qualified_at = _parse_aware_datetime(payload.get("qualified_at"), "qualified_at")
    else:
        validation_reference = validation_reference.strip() if isinstance(validation_reference, str) and validation_reference.strip() else None
        qualified_by = qualified_by.strip() if isinstance(qualified_by, str) and qualified_by.strip() else None
        if payload.get("qualified_at") is not None:
            qualified_at = _parse_aware_datetime(payload.get("qualified_at"), "qualified_at")

    return CallerPloidyPolicy(
        caller_id=caller_id,
        caller_version=caller_version,
        assay_id=assay_id,
        policy_version=policy_version,
        reference_build=build,
        status=status,
        validation_evidence_reference=validation_reference,
        qualified_by=qualified_by,
        qualified_at=qualified_at,
        region_copy_number_to_gt_ploidy=region_policies,
    )


def resolve_expected_gt_ploidy(
    sample_evidence_payload: Mapping[str, Any] | None,
    caller_policy_payload: Mapping[str, Any] | None,
    *,
    specimen_id: str,
    caller_id: str,
    caller_version: str,
    assay_id: str,
    reference_build: str,
    region: str,
) -> PloidyResolution:
    """Resolve ploidy only from verified specimen evidence and exact qualified policy."""
    if not isinstance(region, str) or region not in SEX_CHROMOSOME_REGIONS:
        raise PloidyPolicyValidationError(f"Unsupported sex-chromosome region: {region}")
    try:
        build = normalize_human_reference_build(reference_build)
        normalized_specimen_id = str(UUID(specimen_id))
    except (ValueError, TypeError) as exc:
        raise PloidyPolicyValidationError("Invalid specimen_id or reference_build") from exc

    def unresolved(reason: str, evidence: SamplePloidyEvidence | None = None,
                   policy: CallerPloidyPolicy | None = None, copy_number: int | None = None):
        return PloidyResolution(
            status="UNRESOLVED",
            reason_code=reason,
            region=region,
            reference_build=build,
            specimen_id=evidence.specimen_id if evidence else normalized_specimen_id,
            copy_number=copy_number,
            caller_id=policy.caller_id if policy else caller_id,
            caller_version=policy.caller_version if policy else caller_version,
            assay_id=policy.assay_id if policy else assay_id,
            caller_policy_version=policy.policy_version if policy else None,
            evidence_reference=evidence.evidence_reference if evidence else None,
            evidence_source_type=evidence.source_type if evidence else None,
            evidence_reviewed_by=evidence.reviewed_by if evidence else None,
            evidence_reviewed_at=evidence.reviewed_at if evidence else None,
            caller_validation_evidence_reference=policy.validation_evidence_reference if policy else None,
            caller_qualified_by=policy.qualified_by if policy else None,
            caller_qualified_at=policy.qualified_at if policy else None,
        )

    if sample_evidence_payload is None:
        return unresolved("SAMPLE_PLOIDY_EVIDENCE_MISSING")
    if caller_policy_payload is None:
        return unresolved("CALLER_PLOIDY_POLICY_MISSING")
    try:
        evidence = parse_sample_ploidy_evidence(sample_evidence_payload)
    except PloidyPolicyValidationError:
        return unresolved("SAMPLE_PLOIDY_EVIDENCE_INVALID")
    if evidence.specimen_id != normalized_specimen_id:
        return unresolved("SPECIMEN_ID_MISMATCH", evidence)
    if evidence.reference_build != build:
        return unresolved("SAMPLE_EVIDENCE_REFERENCE_BUILD_MISMATCH", evidence)
    if evidence.status != "VERIFIED":
        return unresolved("SAMPLE_PLOIDY_EVIDENCE_NOT_VERIFIED", evidence)
    if region not in evidence.region_copy_number:
        return unresolved("SAMPLE_REGION_COPY_NUMBER_MISSING", evidence)

    try:
        policy = parse_caller_ploidy_policy(caller_policy_payload)
    except PloidyPolicyValidationError:
        return unresolved("CALLER_PLOIDY_POLICY_INVALID", evidence)
    if policy.status != "QUALIFIED":
        return unresolved("CALLER_PLOIDY_POLICY_NOT_QUALIFIED", evidence, policy)
    if (
        policy.caller_id != caller_id
        or policy.caller_version != caller_version
        or policy.assay_id != assay_id
    ):
        return unresolved("CALLER_ASSAY_VERSION_POLICY_MISMATCH", evidence, policy)
    if policy.reference_build != build:
        return unresolved("CALLER_POLICY_REFERENCE_BUILD_MISMATCH", evidence, policy)
    region_mapping = policy.region_copy_number_to_gt_ploidy.get(region)
    if region_mapping is None:
        return unresolved("CALLER_POLICY_REGION_UNSUPPORTED", evidence, policy)
    copy_number = evidence.region_copy_number[region]
    if copy_number not in region_mapping:
        return unresolved("CALLER_POLICY_COPY_NUMBER_UNSUPPORTED", evidence, policy, copy_number)
    gt_ploidy = region_mapping[copy_number]
    if gt_ploidy == "NOT_CALLABLE":
        return PloidyResolution(
            status="RESOLVED_NOT_CALLABLE",
            reason_code="CALLER_POLICY_DECLARES_REGION_NOT_CALLABLE",
            region=region,
            reference_build=build,
            specimen_id=evidence.specimen_id,
            copy_number=copy_number,
            caller_id=policy.caller_id,
            caller_version=policy.caller_version,
            assay_id=policy.assay_id,
            caller_policy_version=policy.policy_version,
            evidence_reference=evidence.evidence_reference,
            evidence_source_type=evidence.source_type,
            evidence_reviewed_by=evidence.reviewed_by,
            evidence_reviewed_at=evidence.reviewed_at,
            caller_validation_evidence_reference=policy.validation_evidence_reference,
            caller_qualified_by=policy.qualified_by,
            caller_qualified_at=policy.qualified_at,
        )
    return PloidyResolution(
        status="RESOLVED_CALLABLE",
        reason_code="VERIFIED_SAMPLE_EVIDENCE_AND_QUALIFIED_CALLER_POLICY_MATCH",
        region=region,
        reference_build=build,
        specimen_id=evidence.specimen_id,
        copy_number=copy_number,
        expected_gt_ploidy=gt_ploidy,
        caller_id=policy.caller_id,
        caller_version=policy.caller_version,
        assay_id=policy.assay_id,
        caller_policy_version=policy.policy_version,
        evidence_reference=evidence.evidence_reference,
        evidence_source_type=evidence.source_type,
        evidence_reviewed_by=evidence.reviewed_by,
        evidence_reviewed_at=evidence.reviewed_at,
        caller_validation_evidence_reference=policy.validation_evidence_reference,
        caller_qualified_by=policy.qualified_by,
        caller_qualified_at=policy.qualified_at,
    )
