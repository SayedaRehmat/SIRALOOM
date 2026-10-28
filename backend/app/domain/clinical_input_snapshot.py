"""Stable capture of clinical inputs consumed by a scientific analysis stage."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    Analysis,
    Case,
    PhenotypeObservation,
    WorkflowStep,
)

SNAPSHOT_SCHEMA_VERSION = 1


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_case_clinical_input_snapshot(db: Session, analysis: Analysis) -> dict[str, Any]:
    """Build the input snapshot used by the evidence stage for this analysis.

    Case-level observations are intentionally captured alongside analysis-level
    observations because the current evidence stage consumes both.
    """
    case = db.scalar(
        select(Case).where(Case.id == analysis.case_id).with_for_update()
    )
    if case is None:
        raise ValueError("Cannot snapshot clinical inputs for a missing case")
    rows = db.scalars(
        select(PhenotypeObservation)
        .where(
            PhenotypeObservation.case_id == analysis.case_id,
            (PhenotypeObservation.analysis_id == analysis.id)
            | (PhenotypeObservation.analysis_id.is_(None)),
        )
        .order_by(PhenotypeObservation.created_at, PhenotypeObservation.id)
    ).all()
    context = case.clinical_context if isinstance(case.clinical_context, dict) else {}
    gene_disease_evidence = context.get("gene_disease_evidence") or []
    literature_evidence = context.get("literature_evidence") or []
    if not isinstance(gene_disease_evidence, list) or not all(
        isinstance(item, dict) for item in gene_disease_evidence
    ):
        raise ValueError("Case gene-disease evidence must be a list of records")
    if not isinstance(literature_evidence, list) or not all(
        isinstance(item, dict) for item in literature_evidence
    ):
        raise ValueError("Case literature evidence must be a list of records")
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "phenotype_observations": [
            {
                "scope": "CASE" if row.analysis_id is None else "ANALYSIS",
                "hpo_id": row.hpo_id,
                "label": row.label,
                "present": row.present,
                "phenotype_status": row.phenotype_status,
                "onset": row.onset,
                "severity": row.severity,
                "source": row.source,
                "evidence": row.evidence or {},
            }
            for row in rows
        ],
        "gene_disease_evidence": gene_disease_evidence,
        "literature_evidence": literature_evidence,
    }


def validate_case_clinical_input_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("Persisted clinical input snapshot has an unsupported schema")
    if not isinstance(value.get("phenotype_observations"), list):
        raise ValueError("Persisted clinical input snapshot has invalid phenotype observations")
    for key in ("gene_disease_evidence", "literature_evidence"):
        if not isinstance(value.get(key), list) or not all(
            isinstance(item, dict) for item in value[key]
        ):
            raise ValueError(f"Persisted clinical input snapshot has invalid {key}")
    for row in value["phenotype_observations"]:
        if (
            not isinstance(row, dict)
            or row.get("scope") not in {"CASE", "ANALYSIS"}
            or not isinstance(row.get("hpo_id"), str)
            or not isinstance(row.get("phenotype_status"), str)
        ):
            raise ValueError("Persisted clinical input snapshot contains an invalid phenotype row")
    return value


def clinical_input_snapshot_digest(value: dict[str, Any]) -> str:
    validated = validate_case_clinical_input_snapshot(value)
    return hashlib.sha256(_canonical_json(validated).encode("utf-8")).hexdigest()


def capture_or_reuse_case_clinical_input_snapshot(
    db: Session, analysis: Analysis, evidence_step: WorkflowStep
) -> dict[str, Any]:
    """Persist the evidence stage's clinical inputs once and reuse on retries."""
    metadata = dict(evidence_step.metadata_json or {})
    snapshot = metadata.get("clinical_input_snapshot")
    if snapshot is None:
        snapshot = build_case_clinical_input_snapshot(db, analysis)
        metadata["clinical_input_snapshot"] = snapshot
        metadata["clinical_input_snapshot_sha256"] = clinical_input_snapshot_digest(snapshot)
        evidence_step.metadata_json = metadata
        db.add(evidence_step)
        # The snapshot must be durable before external queries or evidence writes.
        db.commit()
        return snapshot

    snapshot = validate_case_clinical_input_snapshot(snapshot)
    if metadata.get("clinical_input_snapshot_sha256") != clinical_input_snapshot_digest(snapshot):
        raise ValueError("Persisted clinical input snapshot checksum does not match")
    return snapshot


def inherit_reused_case_clinical_input_snapshot(
    parent_step: WorkflowStep, child_step: WorkflowStep
) -> dict[str, Any] | None:
    """Copy and validate frozen clinical inputs when an evidence stage is reused."""
    parent_metadata = parent_step.metadata_json or {}
    snapshot = parent_metadata.get("clinical_input_snapshot")
    if snapshot is None:
        return None
    snapshot = validate_case_clinical_input_snapshot(snapshot)
    digest = clinical_input_snapshot_digest(snapshot)
    if parent_metadata.get("clinical_input_snapshot_sha256") != digest:
        raise ValueError("Parent clinical input snapshot checksum does not match")

    child_metadata = dict(child_step.metadata_json or {})
    existing = child_metadata.get("clinical_input_snapshot")
    if existing is not None:
        existing = validate_case_clinical_input_snapshot(existing)
        if child_metadata.get("clinical_input_snapshot_sha256") != clinical_input_snapshot_digest(existing):
            raise ValueError("Child clinical input snapshot checksum does not match")
        if existing != snapshot:
            raise ValueError("Child clinical inputs conflict with reused parent evidence")
    child_metadata["clinical_input_snapshot"] = snapshot
    child_metadata["clinical_input_snapshot_sha256"] = digest
    child_step.metadata_json = child_metadata
    return snapshot


def saved_case_clinical_input_snapshot(
    db: Session, analysis_id: UUID
) -> dict[str, Any] | None:
    step = db.scalar(
        select(WorkflowStep).where(
            WorkflowStep.analysis_id == analysis_id,
            WorkflowStep.step_id == "build_evidence",
        )
    )
    metadata = step.metadata_json or {} if step else {}
    snapshot = metadata.get("clinical_input_snapshot")
    if snapshot is None:
        return None
    snapshot = validate_case_clinical_input_snapshot(snapshot)
    if metadata.get("clinical_input_snapshot_sha256") != clinical_input_snapshot_digest(snapshot):
        raise ValueError("Persisted clinical input snapshot checksum does not match")
    return snapshot
