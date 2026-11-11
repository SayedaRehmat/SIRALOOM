"""Domain rules for evidence-backed assay validation and clinical-use authorization."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.assay_validation import (
    AssayValidationDecision,
    AssayValidationSubmission,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_INITIAL_VARIANT_CLASSES = frozenset({"SNV", "SMALL_INDEL"})


class AssayValidationError(ValueError):
    """Raised when validation evidence or its clinical-use scope is inadequate."""


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssayValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise AssayValidationError(f"{field} must contain at least one value")
    result = []
    for item in value:
        normalized = _nonempty(item, field)
        if normalized not in result:
            result.append(normalized)
    return result


def normalize_validation_submission(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize the frozen evidence package before persistence."""
    validation_type = _nonempty(payload.get("validation_type"), "validation_type").upper()
    if validation_type not in {"VALIDATION", "VERIFICATION"}:
        raise AssayValidationError("validation_type must be VALIDATION or VERIFICATION")

    specimen_types = _string_list(payload.get("specimen_types"), "specimen_types")
    variant_classes = list(dict.fromkeys(value.upper() for value in _string_list(payload.get("variant_classes"), "variant_classes")))
    specimen_types = list(dict.fromkeys(value.upper() for value in specimen_types))
    reference_builds = _string_list(payload.get("reference_builds"), "reference_builds")

    components = payload.get("pipeline_components")
    if not isinstance(components, list) or not components:
        raise AssayValidationError("pipeline_components must identify every validated pipeline component")
    normalized_components = []
    for component in components:
        if not isinstance(component, dict):
            raise AssayValidationError("Each pipeline component must be an object")
        name = _nonempty(component.get("name"), "pipeline component name")
        version = _nonempty(component.get("version"), "pipeline component version")
        digest = _nonempty(component.get("sha256"), "pipeline component sha256").lower()
        if not _SHA256.fullmatch(digest):
            raise AssayValidationError(f"Pipeline component {name} must have a valid SHA-256 digest")
        normalized_components.append({"name": name, "version": version, "sha256": digest})

    specifications = payload.get("performance_specifications")
    if not isinstance(specifications, list) or not specifications:
        raise AssayValidationError("performance_specifications must include objective criteria and observed results")
    normalized_specs = []
    covered_classes = set()
    for item in specifications:
        if not isinstance(item, dict):
            raise AssayValidationError("Each performance specification must be an object")
        variant_class = _nonempty(item.get("variant_class"), "performance specification variant_class").upper()
        metric_name = _nonempty(item.get("metric"), "performance specification metric").lower()
        if variant_class not in variant_classes:
            raise AssayValidationError("Every performance specification must refer to a declared variant class")
        result = _nonempty(item.get("result"), "performance specification result").upper()
        if result not in {"PASS", "FAIL", "NOT_ASSESSED"}:
            raise AssayValidationError("Performance specification result must be PASS, FAIL or NOT_ASSESSED")
        normalized_specs.append({
            "metric": metric_name,
            "variant_class": variant_class,
            "acceptance_criteria": _nonempty(item.get("acceptance_criteria"), "acceptance_criteria"),
            "observed_result": _nonempty(item.get("observed_result"), "observed_result"),
            "unit": str(item.get("unit") or "").strip() or None,
            "result": result,
        })
        covered_classes.add(variant_class)
    required_metrics = {"analytical_sensitivity", "positive_predictive_value"}
    for variant_class in variant_classes:
        class_metrics = {
            item["metric"] for item in normalized_specs
            if item["variant_class"] == variant_class
        }
        missing_metrics = required_metrics - class_metrics
        if missing_metrics:
            raise AssayValidationError(
                f"{variant_class} requires performance specifications for: "
                + ", ".join(sorted(missing_metrics))
            )
    if covered_classes != set(variant_classes):
        missing = sorted(set(variant_classes) - covered_classes)
        raise AssayValidationError(
            "Each declared variant class requires at least one performance specification; missing: "
            + ", ".join(missing)
        )

    evidence = payload.get("evidence_manifest")
    if not isinstance(evidence, list) or not evidence:
        raise AssayValidationError("evidence_manifest must reference objective validation evidence")
    normalized_evidence = []
    for item in evidence:
        if not isinstance(item, dict):
            raise AssayValidationError("Each evidence manifest entry must be an object")
        entry = {
            "evidence_type": _nonempty(item.get("evidence_type"), "evidence_type"),
            "reference": _nonempty(item.get("reference"), "evidence reference"),
        }
        digest = item.get("sha256")
        if digest is not None:
            digest = _nonempty(digest, "evidence sha256").lower()
            if not _SHA256.fullmatch(digest):
                raise AssayValidationError("Evidence SHA-256 must be a 64-character hexadecimal digest")
            entry["sha256"] = digest
        normalized_evidence.append(entry)

    sample_count = payload.get("sample_count")
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1:
        raise AssayValidationError("sample_count must be a positive integer")

    return {
        "validation_type": validation_type,
        "protocol_identifier": _nonempty(payload.get("protocol_identifier"), "protocol_identifier"),
        "protocol_version": _nonempty(payload.get("protocol_version"), "protocol_version"),
        "intended_use": _nonempty(payload.get("intended_use"), "intended_use"),
        "specimen_types": specimen_types,
        "variant_classes": variant_classes,
        "reference_builds": reference_builds,
        "workflow_id": _nonempty(payload.get("workflow_id"), "workflow_id"),
        "workflow_version": _nonempty(payload.get("workflow_version"), "workflow_version"),
        "pipeline_components": normalized_components,
        "performance_specifications": normalized_specs,
        "study_design_summary": _nonempty(payload.get("study_design_summary"), "study_design_summary"),
        "sample_count": sample_count,
        "evidence_manifest": normalized_evidence,
    }


def validation_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def latest_validation_decision(
    db: Session, submission_id: UUID
) -> AssayValidationDecision | None:
    return db.scalar(
        select(AssayValidationDecision)
        .where(AssayValidationDecision.submission_id == submission_id)
        .order_by(AssayValidationDecision.created_at.desc(), AssayValidationDecision.id.desc())
        .limit(1)
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def current_approved_validation(
    db: Session,
    *,
    assay_id: UUID,
    organization_id: UUID,
    at: datetime | None = None,
) -> tuple[AssayValidationSubmission, AssayValidationDecision] | None:
    """Return the newest effective approved submission not suspended or superseded."""
    instant = _utc(at or datetime.now(timezone.utc))
    submissions = db.scalars(
        select(AssayValidationSubmission)
        .where(
            AssayValidationSubmission.assay_id == assay_id,
            AssayValidationSubmission.organization_id == organization_id,
        )
        .order_by(AssayValidationSubmission.revision.desc())
    ).all()
    for submission in submissions:
        decision = latest_validation_decision(db, submission.id)
        if decision is None or decision.decision != "APPROVE":
            continue
        if decision.effective_at is None or decision.expires_at is None:
            continue
        if _utc(decision.effective_at) <= instant < _utc(decision.expires_at):
            return submission, decision
    return None


def _assert_scope(
    submission: AssayValidationSubmission,
    *,
    workflow_id: str,
    workflow_version: str,
    reference_build: str,
    specimen_type: str,
) -> None:
    if submission.workflow_id != workflow_id or submission.workflow_version != workflow_version:
        raise AssayValidationError("Approved assay validation does not cover this workflow and version")
    if reference_build not in (submission.reference_builds or []):
        raise AssayValidationError("Approved assay validation does not cover the selected reference build")
    if specimen_type not in (submission.specimen_types or []):
        raise AssayValidationError("Approved assay validation does not cover this specimen type")
    declared = {str(value).upper() for value in (submission.variant_classes or [])}
    if declared != _REQUIRED_INITIAL_VARIANT_CLASSES:
        raise AssayValidationError(
            "Approved assay validation scope must match the initial workflow exactly: SNV and small indels only"
        )
    specifications = submission.performance_specifications or []
    if any(str(item.get("result", "")).upper() != "PASS" for item in specifications):
        raise AssayValidationError("Assay validation contains performance criteria that did not pass")


def authorize_assay_validation(
    db: Session,
    *,
    assay_id: UUID,
    organization_id: UUID,
    workflow_id: str,
    workflow_version: str,
    reference_build: str,
    specimen_type: str,
) -> dict[str, Any]:
    current = current_approved_validation(
        db, assay_id=assay_id, organization_id=organization_id
    )
    if current is None:
        raise AssayValidationError(
            "Clinical analysis requires a currently effective, independently approved assay validation"
        )
    submission, decision = current
    _assert_scope(
        submission,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        reference_build=reference_build,
        specimen_type=specimen_type,
    )
    return {
        "submission_id": str(submission.id),
        "revision": submission.revision,
        "payload_sha256": submission.payload_sha256,
        "decision_id": str(decision.id),
        "protocol_identifier": submission.protocol_identifier,
        "protocol_version": submission.protocol_version,
        "validation_type": submission.validation_type,
        "workflow_id": submission.workflow_id,
        "workflow_version": submission.workflow_version,
        "specimen_types": list(submission.specimen_types or []),
        "variant_classes": list(submission.variant_classes or []),
        "reference_builds": list(submission.reference_builds or []),
        # Freeze the exact component declarations with the approval snapshot.
        # Runtime attestation must compare these digests with observed worker bytes.
        "pipeline_components": list(submission.pipeline_components or []),
        "effective_at": _utc(decision.effective_at).isoformat(),
        "expires_at": _utc(decision.expires_at).isoformat(),
    }


def assert_assay_validation_current(
    db: Session,
    *,
    assay_id: UUID,
    organization_id: UUID,
    snapshot: dict[str, Any] | None,
    workflow_id: str,
    workflow_version: str,
    reference_build: str,
    specimen_type: str,
) -> None:
    if not isinstance(snapshot, dict):
        raise AssayValidationError("Clinical analysis has no immutable assay validation approval snapshot")
    current = authorize_assay_validation(
        db,
        assay_id=assay_id,
        organization_id=organization_id,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        reference_build=reference_build,
        specimen_type=specimen_type,
    )
    for key in ("submission_id", "revision", "payload_sha256", "decision_id"):
        if current.get(key) != snapshot.get(key):
            raise AssayValidationError(
                "Assay validation approval changed, expired or was withdrawn after analysis creation"
            )
