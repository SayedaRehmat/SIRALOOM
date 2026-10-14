"""Deterministic comparison of pinned reanalysis inputs and scientific outputs.

This module deliberately separates execution identity from scientific output
identity. Random database IDs and timestamps are excluded from the scientific
hash; variant canonical keys and exact resource snapshot identities are used
instead. A comparison is not declared reproducible when resource snapshots are
missing or any snapshot lacks both a version and checksum.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    AnalysisResourceSnapshot,
    Annotation,
    Classification,
    Evidence,
    PopulationObservation,
    Report,
    Resource,
    Variant,
)


def _json_value(value: Any) -> Any:
    """Return JSON-safe data with deterministic handling for non-JSON values."""
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _variant_key_map(db: Session, analysis_id: UUID) -> dict[UUID, str]:
    variant_ids = set(db.scalars(select(Annotation.variant_id).where(
        Annotation.analysis_id == analysis_id
    )).all())
    variant_ids.update(db.scalars(select(PopulationObservation.variant_id).where(
        PopulationObservation.analysis_id == analysis_id
    )).all())
    variant_ids.update(db.scalars(select(Evidence.variant_id).where(
        Evidence.analysis_id == analysis_id
    )).all())
    variant_ids.update(db.scalars(select(ACMGAssessment.variant_id).where(
        ACMGAssessment.analysis_id == analysis_id
    )).all())
    variant_ids.update(db.scalars(select(Classification.variant_id).where(
        Classification.analysis_id == analysis_id
    )).all())
    if not variant_ids:
        return {}
    variants = db.scalars(select(Variant).where(Variant.id.in_(variant_ids))).all()
    return {row.id: row.canonical_key for row in variants}


def build_reproducibility_manifest(db: Session, analysis_id: UUID) -> dict[str, Any]:
    """Build stable resource and scientific-output fingerprints for one analysis.

    The result is suitable for controlled baseline comparison, not a claim of
    clinical validity. Missing or unchecksummed resource snapshots are surfaced
    explicitly and make the manifest ineligible for a reproducibility pass.
    """
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise ValueError(f"Analysis {analysis_id} does not exist.")

    snapshots = db.scalars(select(AnalysisResourceSnapshot).where(
        AnalysisResourceSnapshot.analysis_id == analysis_id
    )).all()
    resource_material = [
        {
            "resource_kind": row.resource_kind,
            "resource_name": row.resource_name,
            "provider": row.provider,
            "version": row.version,
            "checksum": row.checksum,
            "genome_build": row.genome_build,
            "metadata": row.metadata_json or {},
        }
        for row in snapshots
    ]
    resource_material.sort(key=_canonical_json)
    unpinned_resources = [
        f"{row.resource_kind}:{row.resource_name}"
        for row in snapshots
        if not row.version or not row.checksum
    ]
    if not snapshots:
        unpinned_resources.append("NO_RESOURCE_SNAPSHOTS")

    variant_keys = _variant_key_map(db, analysis_id)
    resource_rows = db.scalars(select(Resource)).all()
    resource_by_id = {row.id: row for row in resource_rows}

    annotations = [
        {
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "provider": row.provider_name,
            "provider_version": row.provider_version,
            "resource_name": row.resource_name,
            "resource_version": row.resource_version,
            "request_fingerprint": row.request_fingerprint,
            "response_sha256": row.response_sha256,
            "payload": row.payload or {},
        }
        for row in db.scalars(select(Annotation).where(
            Annotation.analysis_id == analysis_id
        )).all()
    ]

    population = []
    for row in db.scalars(select(PopulationObservation).where(
        PopulationObservation.analysis_id == analysis_id
    )).all():
        resource = resource_by_id.get(row.resource_id)
        population.append({
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "resource": {
                "name": resource.name if resource else None,
                "provider": resource.provider if resource else None,
                "version": resource.version if resource else None,
                "checksum": resource.checksum if resource else None,
            },
            "population_level": row.population_level,
            "population_code": row.population_code,
            "population_label": row.population_label,
            "allele_count": row.allele_count,
            "allele_number": row.allele_number,
            "allele_frequency": row.allele_frequency,
            "homozygote_count": row.homozygote_count,
            "availability": row.availability,
            "quality_status": row.quality_status,
            "source_record_id": row.source_record_id,
            "request_fingerprint": row.request_fingerprint,
            "response_sha256": row.response_sha256,
            "request_metadata": row.request_metadata or {},
        })

    evidence = [
        {
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "evidence_type": row.evidence_type,
            "statement": row.statement,
            "direction": row.direction,
            "source_name": row.source_name,
            "source_version": row.source_version,
            "source_record_id": row.source_record_id,
            "request_fingerprint": row.request_fingerprint,
            "response_sha256": row.response_sha256,
            "request_metadata": row.request_metadata or {},
            "payload": row.payload or {},
            "evidence_fingerprint": row.evidence_fingerprint,
        }
        for row in db.scalars(select(Evidence).where(
            Evidence.analysis_id == analysis_id
        )).all()
    ]

    acmg = [
        {
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "framework_name": row.framework_name,
            "framework_version": row.framework_version,
            "specification_provider": row.specification_provider,
            "specification_id": row.specification_id,
            "specification_version": row.specification_version,
            "criterion": row.criterion,
            "automated_assessment": row.automated_assessment or {},
            "reviewed_assessment": row.reviewed_assessment,
            "final_assessment": row.final_assessment,
            "state": row.state,
            "review_version": row.review_version,
        }
        for row in db.scalars(select(ACMGAssessment).where(
            ACMGAssessment.analysis_id == analysis_id
        )).all()
    ]

    classifications = [
        {
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "framework_name": row.framework_name,
            "framework_version": row.framework_version,
            "specification_provider": row.specification_provider,
            "specification_id": row.specification_id,
            "specification_version": row.specification_version,
            "result": row.result,
            "criterion_ids": row.criterion_ids or [],
            "metadata": row.metadata_json or {},
            "state": row.state,
            "review_status": row.review_status,
            "review_version": row.review_version,
        }
        for row in db.scalars(select(Classification).where(
            Classification.analysis_id == analysis_id
        )).all()
    ]

    reports = []
    for row in db.scalars(select(Report).where(
        Report.analysis_id == analysis_id
    )).all():
        content = dict(row.content_json or {})
        # Report version is a case-level sequence, not a scientific result.
        content.pop("report_version", None)
        reports.append({
            "report_type": row.report_type,
            "language": row.language,
            "status": row.status,
            "signed_sha256": row.signed_sha256,
            "content": content,
        })

    output_material = {
        "reference_build": analysis.reference_build,
        "annotations": sorted(annotations, key=_canonical_json),
        "population_observations": sorted(population, key=_canonical_json),
        "evidence": sorted(evidence, key=_canonical_json),
        "acmg_assessments": sorted(acmg, key=_canonical_json),
        "classifications": sorted(classifications, key=_canonical_json),
        "reports": sorted(reports, key=_canonical_json),
    }
    return {
        "analysis_id": str(analysis_id),
        "workflow_id": analysis.workflow_id,
        "workflow_version": analysis.workflow_version,
        "reference_build": analysis.reference_build,
        "resource_snapshot_sha256": _sha256(resource_material),
        "scientific_output_sha256": _sha256(output_material),
        "resource_snapshot_count": len(snapshots),
        "unpinned_resources": sorted(unpinned_resources),
        "reproducibility_eligible": not unpinned_resources,
    }


def compare_reanalysis_outputs(
    db: Session,
    *,
    parent_analysis_id: UUID,
    child_analysis_id: UUID,
) -> dict[str, Any]:
    """Compare parent/child resource pins and scientific outputs without guessing."""
    parent = build_reproducibility_manifest(db, parent_analysis_id)
    child = build_reproducibility_manifest(db, child_analysis_id)
    resources_match = parent["resource_snapshot_sha256"] == child["resource_snapshot_sha256"]
    outputs_match = parent["scientific_output_sha256"] == child["scientific_output_sha256"]
    eligible = parent["reproducibility_eligible"] and child["reproducibility_eligible"]
    return {
        "parent": parent,
        "child": child,
        "resource_snapshots_match": resources_match,
        "scientific_outputs_match": outputs_match,
        "reproducible": bool(eligible and resources_match and outputs_match),
        "decision": (
            "MATCH"
            if eligible and resources_match and outputs_match
            else "MISMATCH"
            if eligible
            else "INELIGIBLE_UNPINNED_RESOURCES"
        ),
    }
