from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    Annotation,
    Artifact,
    AuditEvent,
    Case,
    CaseExport,
    Classification,
    Evidence,
    PopulationObservation,
    Report,
    ReportabilityDecision,
    Resource,
    ReviewAction,
    ToolRun,
    Variant,
    WorkflowStep,
)


class CaseExportError(ValueError):
    pass


def _iso(value):
    return value.isoformat() if value else None


def build_manifest(db: Session, case: Case) -> dict:
    analyses = list(db.scalars(select(Analysis).where(Analysis.case_id == case.id).order_by(Analysis.created_at, Analysis.id)))
    analysis_ids = [a.id for a in analyses]
    artifacts = list(db.scalars(select(Artifact).where(Artifact.case_id == case.id).order_by(Artifact.created_at, Artifact.id)))
    return {
        "export_schema_version": "1.0.0",
        "case": {
            "case_id": str(case.id),
            "case_identifier": case.case_identifier,
            "status": case.status,
            "language": case.language,
        },
        "analyses": [
            {
                "analysis_id": str(a.id),
                "parent_analysis_id": str(a.parent_analysis_id) if a.parent_analysis_id else None,
                "analysis_type": a.analysis_type,
                "workflow_id": a.workflow_id,
                "workflow_version": a.workflow_version,
                "reference_build": a.reference_build,
                "status": a.status,
                "created_at": _iso(a.created_at),
                "started_at": _iso(a.started_at),
                "completed_at": _iso(a.completed_at),
            }
            for a in analyses
        ],
        "artifacts": [
            {
                "artifact_id": str(a.id),
                "analysis_id": str(a.analysis_id) if a.analysis_id else None,
                "type": a.artifact_type,
                "filename": a.filename,
                "sha256": a.sha256,
                "size_bytes": a.size_bytes,
            }
            for a in artifacts
        ],
    }


def build_case_export(db: Session, *, export: CaseExport, store: ArtifactStore) -> Artifact:
    case = db.get(Case, export.case_id)
    if case is None:
        raise CaseExportError("Case not found")

    analyses = list(db.scalars(select(Analysis).where(Analysis.case_id == case.id).order_by(Analysis.created_at, Analysis.id)))
    analysis_ids = [a.id for a in analyses]
    artifacts = list(db.scalars(select(Artifact).where(Artifact.case_id == case.id).order_by(Artifact.created_at, Artifact.id)))

    with TemporaryDirectory(prefix="siraloom-export-") as tmp:
        root = Path(tmp)
        manifest = build_manifest(db, case)
        (root / "case_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        if export.include_audit:
            audits = list(db.scalars(select(AuditEvent).where(AuditEvent.case_id == case.id).order_by(AuditEvent.occurred_at, AuditEvent.id)))
            (root / "audit_events.json").write_text(
                json.dumps([{
                    "event_id": str(a.id), "event_type": a.event_type, "occurred_at": _iso(a.occurred_at),
                    "actor_type": a.actor_type, "actor_id": a.actor_id, "subject_type": a.subject_type,
                    "subject_id": a.subject_id, "operation": a.operation, "before_state": a.before_state,
                    "after_state": a.after_state, "reason": a.reason, "input_artifacts": a.input_artifacts,
                    "output_artifacts": a.output_artifacts, "software": a.software, "workflow": a.workflow,
                    "resource_versions": a.resource_versions, "correlation_id": a.correlation_id,
                    "payload": a.payload, "previous_event_hash": a.previous_event_hash, "event_hash": a.event_hash,
                } for a in audits], indent=2, ensure_ascii=False), encoding="utf-8")

        if export.include_provenance:
            tool_runs = list(db.scalars(select(ToolRun).where(ToolRun.analysis_id.in_(analysis_ids)))) if analysis_ids else []
            steps = list(db.scalars(select(WorkflowStep).where(WorkflowStep.analysis_id.in_(analysis_ids)))) if analysis_ids else []
            provenance = {
                "tool_runs": [{
                    "id": str(t.id), "analysis_id": str(t.analysis_id), "tool_name": t.tool_name,
                    "tool_version": t.tool_version, "container_digest": t.container_digest,
                    "command_fingerprint": t.command_fingerprint, "parameters": t.parameters,
                    "status": t.status, "started_at": _iso(t.started_at), "completed_at": _iso(t.completed_at),
                    "exit_code": t.exit_code,
                } for t in tool_runs],
                "workflow_steps": [{
                    "id": str(s.id), "analysis_id": str(s.analysis_id), "step_id": s.step_id,
                    "step_order": s.step_order, "status": s.status, "attempt": s.attempt,
                    "last_heartbeat": _iso(s.last_heartbeat), "started_at": _iso(s.started_at),
                    "completed_at": _iso(s.completed_at), "input_artifacts": s.input_artifacts,
                    "output_artifacts": s.output_artifacts, "error_code": s.error_code,
                    "error_message": s.error_message, "metadata": s.metadata_json,
                } for s in steps],
            }
            (root / "provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")

        if export.include_reports:
            reports = list(db.scalars(select(Report).where(Report.case_id == case.id).order_by(Report.report_version)))
            (root / "reports.json").write_text(json.dumps([
                {
                    "report_id": str(r.id), "analysis_id": str(r.analysis_id), "version": r.report_version,
                    "status": r.status, "language": r.language, "report_type": r.report_type,
                    "artifact_id": str(r.artifact_id) if r.artifact_id else None,
                    "approved_by": str(r.approved_by) if r.approved_by else None,
                    "approved_at": _iso(r.approved_at), "content": r.content_json,
                } for r in reports], indent=2, ensure_ascii=False), encoding="utf-8")

        if export.include_evidence:
            if analysis_ids:
                evidence = list(db.scalars(select(Evidence).where(Evidence.analysis_id.in_(analysis_ids))))
                classifications = list(db.scalars(select(Classification).where(Classification.analysis_id.in_(analysis_ids))))
                acmg = list(db.scalars(select(ACMGAssessment).where(ACMGAssessment.analysis_id.in_(analysis_ids))))
                populations = list(db.scalars(select(PopulationObservation).where(PopulationObservation.analysis_id.in_(analysis_ids))))
                review_actions = list(db.scalars(select(ReviewAction).where(ReviewAction.analysis_id.in_(analysis_ids))))
                reportability = list(db.scalars(select(ReportabilityDecision).where(ReportabilityDecision.analysis_id.in_(analysis_ids))))
            else:
                evidence = []; classifications = []; acmg = []; populations = []; review_actions = []; reportability = []
            evidence_obj = {
                "evidence": [{"id": str(e.id), "analysis_id": str(e.analysis_id), "variant_id": str(e.variant_id), "type": e.evidence_type, "statement": e.statement, "direction": e.direction, "source_name": e.source_name, "source_version": e.source_version, "source_record_id": e.source_record_id, "observation_ids": e.observation_ids, "payload": e.payload} for e in evidence],
                "classifications": [{"id": str(c.id), "analysis_id": str(c.analysis_id), "variant_id": str(c.variant_id), "version": c.version, "result": c.result, "state": c.state, "review_status": c.review_status, "framework": c.framework_name, "framework_version": c.framework_version, "specification_provider": c.specification_provider, "specification_id": c.specification_id, "specification_version": c.specification_version, "criterion_ids": c.criterion_ids} for c in classifications],
                "acmg_assessments": [{"id": str(a.id), "analysis_id": str(a.analysis_id), "variant_id": str(a.variant_id), "criterion": a.criterion, "automated_assessment": a.automated_assessment, "reviewed_assessment": a.reviewed_assessment, "final_assessment": a.final_assessment, "state": a.state, "review_version": a.review_version} for a in acmg],
                "population_observations": [{"id": str(p.id), "analysis_id": str(p.analysis_id), "variant_id": str(p.variant_id), "resource_id": str(p.resource_id), "population_level": p.population_level, "population_code": p.population_code, "population_label": p.population_label, "allele_count": p.allele_count, "allele_number": p.allele_number, "allele_frequency": p.allele_frequency, "availability": p.availability, "quality_status": p.quality_status} for p in populations],
                "review_actions": [{"id": str(r.id), "analysis_id": str(r.analysis_id), "variant_id": str(r.variant_id) if r.variant_id else None, "action_type": r.action_type, "sequence_number": r.sequence_number, "reviewer_id": str(r.reviewer_id), "reason": r.reason, "before_state": r.before_state, "after_state": r.after_state, "expected_version": r.expected_version, "resulting_version": r.resulting_version, "created_at": _iso(r.created_at)} for r in review_actions],
                "reportability_decisions": [{"id": str(r.id), "analysis_id": str(r.analysis_id), "variant_id": str(r.variant_id), "classification_id": str(r.classification_id), "version": r.version, "supersedes_decision_id": str(r.supersedes_decision_id) if r.supersedes_decision_id else None, "policy_name": r.policy_name, "policy_version": r.policy_version, "disposition": r.disposition, "priority_score": r.priority_score, "priority_band": r.priority_band, "reasons": r.reasons, "status": r.status, "review_version": r.review_version, "reviewed_by": str(r.reviewed_by) if r.reviewed_by else None, "approved_at": _iso(r.approved_at)} for r in reportability],
            }
            (root / "evidence.json").write_text(json.dumps(evidence_obj, indent=2, ensure_ascii=False), encoding="utf-8")

        if export.include_artifacts:
            artifacts_root = root / "artifacts"
            artifacts_root.mkdir()
            for artifact in artifacts:
                source = store.local_path(artifact.storage_uri)
                target = artifacts_root / f"{artifact.id}-{artifact.filename}"
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as src, target.open("wb") as dst:
                    while chunk := src.read(8 * 1024 * 1024):
                        dst.write(chunk)

        archive = root / "case_export.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(root.rglob("*")):
                if path.is_file() and path != archive:
                    zf.write(path, path.relative_to(root).as_posix())

        return store.put_file(
            db=db,
            case_id=case.id,
            analysis_id=None,
            source_path=archive,
            filename=f"case_export_{case.case_identifier}.zip",
            artifact_type="AUDIT_PACKAGE",
            media_type="application/zip",
            genome_build=None,
            metadata={"export_id": str(export.id), "schema_version": "1.0.0"},
        )
