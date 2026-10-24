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
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    AnalysisResourceSnapshot,
    Annotation,
    Artifact,
    Classification,
    ConfirmationRecord,
    Evidence,
    InheritanceAssessment,
    PedigreeMember,
    PhenotypeObservation,
    PopulationObservation,
    QCAssessment,
    Report,
    ReportabilityDecision,
    Resource,
    ReviewAction,
    SecondaryFindingDecision,
    SegregationObservation,
    TechnicalQCObservation,
    ToolRun,
    Variant,
    WorkflowDecisionRecord,
    WorkflowStep,
)


class ReanalysisComparisonError(ValueError):
    """Raised when two analyses do not form a valid parent/child comparison."""


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


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


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
    variant_ids.update(db.scalars(select(SegregationObservation.variant_id).where(
        SegregationObservation.analysis_id == analysis_id
    )).all())
    variant_ids.update(db.scalars(select(InheritanceAssessment.variant_id).where(
        InheritanceAssessment.analysis_id == analysis_id
    )).all())
    variant_ids.update(db.scalars(select(ReportabilityDecision.variant_id).where(
        ReportabilityDecision.analysis_id == analysis_id
    )).all())
    variant_ids.update(db.scalars(select(ConfirmationRecord.variant_id).where(
        ConfirmationRecord.analysis_id == analysis_id
    )).all())
    variant_ids.update(db.scalars(select(SecondaryFindingDecision.variant_id).where(
        SecondaryFindingDecision.analysis_id == analysis_id
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
    input_reference = (analysis.configuration or {}).get("input_artifact_id")
    input_artifact = None
    if input_reference:
        try:
            input_artifact = db.get(Artifact, UUID(str(input_reference)))
        except (TypeError, ValueError):
            input_artifact = None
    input_artifact_valid = bool(
        input_artifact
        and input_artifact.case_id == analysis.case_id
        and input_artifact.validation_status in {"VALIDATED", "ACCEPTED", "ACCEPTED_WITH_WARNINGS"}
        and _is_sha256(input_artifact.sha256)
    )
    provenance_issues = []
    if not input_artifact_valid:
        provenance_issues.append("SOURCE_ARTIFACT_MISSING_OR_UNVERIFIED")
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

    phenotypes = [
        {
            "hpo_id": row.hpo_id,
            "label": row.label,
            "present": row.present,
            "status": row.phenotype_status,
            "onset": row.onset,
            "severity": row.severity,
            "source": row.source,
            "evidence": row.evidence or {},
        }
        for row in db.scalars(select(PhenotypeObservation).where(
            PhenotypeObservation.analysis_id == analysis_id
        )).all()
    ]

    technical_qc = [
        {
            "metric_name": row.metric_name,
            "metric_value": row.metric_value,
            "metric_unit": row.metric_unit,
            "status": row.status,
            "source": row.source,
            "source_version": row.source_version,
            "metadata": row.metadata_json or {},
        }
        for row in db.scalars(select(TechnicalQCObservation).where(
            TechnicalQCObservation.analysis_id == analysis_id
        )).all()
    ]

    qc_assessments = [
        {
            "status": row.status,
            "profile_name": row.profile_name,
            "profile_version": row.profile_version,
            "metrics": row.metrics_json or {},
            "evaluated_rules": row.evaluated_rules or [],
            "gate_status": row.gate_status,
            "reviewer_note": row.reviewer_note,
        }
        for row in db.scalars(select(QCAssessment).where(
            QCAssessment.analysis_id == analysis_id
        )).all()
    ]

    segregation = []
    for row in db.scalars(select(SegregationObservation).where(
        SegregationObservation.analysis_id == analysis_id
    )).all():
        member = db.get(PedigreeMember, row.pedigree_member_id)
        metadata = row.metadata_json or {}
        pedigree_context = metadata.get("pedigree_context_snapshot")
        if not isinstance(pedigree_context, dict) or pedigree_context.get("schema_version") != 1:
            provenance_issues.append("SEGREGATION_PEDIGREE_CONTEXT_SNAPSHOT_MISSING")
            pedigree_context = None
        segregation.append({
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "member_identifier": member.member_identifier if member else "MISSING_PEDIGREE_MEMBER",
            "pedigree_context_snapshot": pedigree_context,
            "genotype": row.genotype,
            "zygosity": row.zygosity,
            "phase": row.phase,
            "allele_observed": row.allele_observed,
            "phenotype_status": row.phenotype_status,
            "source": row.source,
            "notes": row.notes,
            "metadata": metadata,
        })

    inheritance = [
        {
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "model": row.model,
            "status": row.status,
            "score": row.score,
            "rationale": row.rationale,
            "observation_fingerprint": row.observation_fingerprint,
            "reviewer_note": row.reviewer_note,
        }
        for row in db.scalars(select(InheritanceAssessment).where(
            InheritanceAssessment.analysis_id == analysis_id
        )).all()
    ]

    reportability = [
        {
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "policy_name": row.policy_name,
            "policy_version": row.policy_version,
            "disposition": row.disposition,
            "priority_score": row.priority_score,
            "priority_band": row.priority_band,
            "reasons": row.reasons or [],
            "status": row.status,
            "review_version": row.review_version,
        }
        for row in db.scalars(select(ReportabilityDecision).where(
            ReportabilityDecision.analysis_id == analysis_id
        )).all()
    ]

    confirmations = [
        {
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "version": row.version,
            "required": row.required,
            "method": row.method,
            "status": row.status,
            "result": row.result,
            "laboratory": row.laboratory,
            "accession": row.accession,
            "notes": row.notes,
            "metadata": row.metadata_json or {},
        }
        for row in db.scalars(select(ConfirmationRecord).where(
            ConfirmationRecord.analysis_id == analysis_id
        )).all()
    ]

    tool_runs = [
        {
            "tool_name": row.tool_name,
            "tool_version": row.tool_version,
            "container_digest": row.container_digest,
            "command_fingerprint": row.command_fingerprint,
            "parameters": row.parameters or {},
            "status": row.status,
            "exit_code": row.exit_code,
        }
        for row in db.scalars(select(ToolRun).where(
            ToolRun.analysis_id == analysis_id
        )).all()
    ]

    review_actions = [
        {
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT") if row.variant_id else None,
            "action_type": row.action_type,
            "sequence_number": row.sequence_number,
            "reason": row.reason,
            "before_state": row.before_state,
            "after_state": row.after_state,
            "expected_version": row.expected_version,
            "resulting_version": row.resulting_version,
        }
        for row in db.scalars(select(ReviewAction).where(
            ReviewAction.analysis_id == analysis_id
        )).all()
    ]

    secondary_findings = [
        {
            "variant": variant_keys.get(row.variant_id, "MISSING_CANONICAL_VARIANT"),
            "version": row.version,
            "eligibility": row.eligibility,
            "consent_status": row.consent_status,
            "disposition": row.disposition,
            "status": row.status,
            "rationale": row.rationale,
            "gene_disease_context": row.gene_disease_context or {},
        }
        for row in db.scalars(select(SecondaryFindingDecision).where(
            SecondaryFindingDecision.analysis_id == analysis_id
        )).all()
    ]

    workflow_steps = []
    for row in db.scalars(select(WorkflowStep).where(
        WorkflowStep.analysis_id == analysis_id
    )).all():
        artifact_refs = []
        for collection_name, references in (
            ("input", row.input_artifacts or []),
            ("output", row.output_artifacts or []),
        ):
            for reference in references:
                reference = reference if isinstance(reference, dict) else {"artifact_id": reference}
                artifact_id = reference.get("artifact_id") or reference.get("id")
                try:
                    artifact = db.get(Artifact, UUID(str(artifact_id))) if artifact_id else None
                except (TypeError, ValueError):
                    artifact = None
                if artifact is None:
                    provenance_issues.append(
                        f"WORKFLOW_ARTIFACT_MISSING:{row.step_id}:{collection_name}"
                    )
                else:
                    if artifact.case_id != analysis.case_id:
                        provenance_issues.append(
                            f"WORKFLOW_ARTIFACT_CASE_MISMATCH:{row.step_id}:{collection_name}"
                        )
                    if not _is_sha256(artifact.sha256):
                        provenance_issues.append(
                            f"WORKFLOW_ARTIFACT_CHECKSUM_MISSING_OR_INVALID:{row.step_id}:{collection_name}"
                        )
                    declared_sha256 = reference.get("sha256")
                    if declared_sha256 is not None and (
                        not _is_sha256(declared_sha256)
                        or not _is_sha256(artifact.sha256)
                        or declared_sha256.lower() != artifact.sha256.lower()
                    ):
                        provenance_issues.append(
                            f"WORKFLOW_ARTIFACT_CHECKSUM_MISMATCH:{row.step_id}:{collection_name}"
                        )
                artifact_refs.append({
                    "direction": collection_name,
                    "artifact_record_found": artifact is not None,
                    "persisted_sha256": artifact.sha256.lower() if artifact and _is_sha256(artifact.sha256) else None,
                    "declared_sha256": reference.get("sha256"),
                    "artifact_type": artifact.artifact_type if artifact else reference.get("artifact_type"),
                    "filename": artifact.filename if artifact else reference.get("filename"),
                    "validation_status": artifact.validation_status if artifact else reference.get("validation_status"),
                })
        workflow_steps.append({
            "step_id": row.step_id,
            "step_order": row.step_order,
            "status": row.status,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "artifacts": sorted(artifact_refs, key=_canonical_json),
            "metadata": row.metadata_json or {},
        })

    workflow_decisions = [
        {
            "step_id": row.step_id,
            "outcome_kind": row.outcome_kind,
            "action": row.action,
            "code": row.code,
            "message": row.message,
            "retryable": row.retryable,
            "fallback_allowed": row.fallback_allowed,
            "lab_action_required": row.lab_action_required,
            "metadata": row.metadata_json or {},
        }
        for row in db.scalars(select(WorkflowDecisionRecord).where(
            WorkflowDecisionRecord.analysis_id == analysis_id
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

    scientific_configuration = dict(analysis.configuration or {})
    # The source artifact's random database ID is execution identity. Its
    # checksum and scientific metadata are fingerprinted separately below.
    scientific_configuration.pop("input_artifact_id", None)
    output_material = {
        "reference_build": analysis.reference_build,
        "analysis_configuration": scientific_configuration,
        "source_artifact": ({
            "artifact_type": input_artifact.artifact_type,
            "sha256": input_artifact.sha256,
            "size_bytes": input_artifact.size_bytes,
            "genome_build": input_artifact.genome_build,
            "validation_status": input_artifact.validation_status,
        } if input_artifact_valid else None),
        "annotations": sorted(annotations, key=_canonical_json),
        "population_observations": sorted(population, key=_canonical_json),
        "evidence": sorted(evidence, key=_canonical_json),
        "acmg_assessments": sorted(acmg, key=_canonical_json),
        "classifications": sorted(classifications, key=_canonical_json),
        "phenotype_observations": sorted(phenotypes, key=_canonical_json),
        "technical_qc_observations": sorted(technical_qc, key=_canonical_json),
        "qc_assessments": sorted(qc_assessments, key=_canonical_json),
        "segregation_observations": sorted(segregation, key=_canonical_json),
        "inheritance_assessments": sorted(inheritance, key=_canonical_json),
        "reportability_decisions": sorted(reportability, key=_canonical_json),
        "confirmation_records": sorted(confirmations, key=_canonical_json),
        "tool_runs": sorted(tool_runs, key=_canonical_json),
        "review_actions": sorted(review_actions, key=_canonical_json),
        "secondary_finding_decisions": sorted(secondary_findings, key=_canonical_json),
        "workflow_steps": sorted(workflow_steps, key=_canonical_json),
        "workflow_decisions": sorted(workflow_decisions, key=_canonical_json),
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
        "provenance_issues": sorted(set(provenance_issues)),
        "reproducibility_eligible": not unpinned_resources and not provenance_issues,
    }


def compare_reanalysis_outputs(
    db: Session,
    *,
    parent_analysis_id: UUID,
    child_analysis_id: UUID,
) -> dict[str, Any]:
    """Compare parent/child resource pins and scientific outputs without guessing."""
    parent_analysis = db.get(Analysis, parent_analysis_id)
    child_analysis = db.get(Analysis, child_analysis_id)
    if parent_analysis is None or child_analysis is None:
        missing_id = parent_analysis_id if parent_analysis is None else child_analysis_id
        raise ReanalysisComparisonError(f"Analysis {missing_id} does not exist.")
    if parent_analysis.case_id != child_analysis.case_id:
        raise ReanalysisComparisonError(
            "Parent and child analyses must belong to the same case."
        )
    if child_analysis.parent_analysis_id != parent_analysis.id:
        raise ReanalysisComparisonError(
            "Child analysis is not a direct reanalysis of the selected parent."
        )

    parent = build_reproducibility_manifest(db, parent_analysis_id)
    child = build_reproducibility_manifest(db, child_analysis_id)
    resources_match = parent["resource_snapshot_sha256"] == child["resource_snapshot_sha256"]
    outputs_match = parent["scientific_output_sha256"] == child["scientific_output_sha256"]
    eligible = parent["reproducibility_eligible"] and child["reproducibility_eligible"]
    has_unpinned_resources = bool(parent["unpinned_resources"] or child["unpinned_resources"])
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
            if has_unpinned_resources
            else "INELIGIBLE_INCOMPLETE_PROVENANCE"
        ),
    }
