from __future__ import annotations

import html
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.reporting.reportability import final_reportability_state, latest_decision
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    Annotation,
    Artifact,
    AuditEvent,
    Case,
    Classification,
    Evidence,
    PopulationObservation,
    Report,
    Resource,
    ReviewAction,
    Variant,
    Specimen,
    User,
    PhenotypeObservation,
    PedigreeMember, PedigreeRelationship, SegregationObservation, InheritanceAssessment,
    ConfirmationRecord, FollowUpPlan, SecondaryFindingDecision,
)

REPORT_STATUS_DRAFT = "DRAFT"
REPORT_STATUS_FINAL = "FINAL"
REPORT_STATUS_SUPERSEDED = "SUPERSEDED"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _latest_classification(db: Session, analysis_id: UUID, variant_id: UUID) -> Classification | None:
    return db.scalar(
        select(Classification)
        .where(Classification.analysis_id == analysis_id, Classification.variant_id == variant_id)
        .order_by(Classification.version.desc())
    )


def _approved_classifications(db: Session, analysis_id: UUID) -> list[Classification]:
    return list(
        db.scalars(
            select(Classification)
            .where(
                Classification.analysis_id == analysis_id,
                Classification.review_status == "APPROVED",
                Classification.state == "FINAL",
            )
            .order_by(Classification.variant_id, Classification.version.desc())
        )
    )


def _latest_by_variant(rows: list[Classification]) -> list[Classification]:
    latest: dict[UUID, Classification] = {}
    for row in rows:
        current = latest.get(row.variant_id)
        if current is None or row.version > current.version:
            latest[row.variant_id] = row
    return list(latest.values())


def final_report_eligibility(db: Session, *, analysis_id: UUID) -> tuple[bool, list[str]]:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        return False, ["Analysis not found"]
    errors: list[str] = []
    if analysis.status not in {"REQUIRES_REVIEW", "SUCCEEDED"}:
        errors.append(f"Analysis status {analysis.status} is not report-eligible")

    classifications = list(db.scalars(select(Classification).where(Classification.analysis_id == analysis_id)))
    latest: dict[UUID, Classification] = {}
    for row in classifications:
        if row.variant_id not in latest or row.version > latest[row.variant_id].version:
            latest[row.variant_id] = row
    if not latest:
        errors.append("No variant classification is available for final reporting")
    for variant_id, row in latest.items():
        if row.review_status != "APPROVED" or row.state != "FINAL":
            errors.append(f"Variant {variant_id} classification is not FINAL + APPROVED")

    # Confirmation is an explicit laboratory policy gate: only a record marked required
    # can block release, preserving assay-specific confirmation policies.
    reportable_variant_ids = set()
    for row in latest.values():
        decision = latest_decision(db, analysis_id, row.variant_id)
        if decision and decision.status == "FINAL" and decision.disposition == "REPORT":
            reportable_variant_ids.add(row.variant_id)
    for variant_id in reportable_variant_ids:
        confirmation = db.scalar(select(ConfirmationRecord).where(ConfirmationRecord.analysis_id == analysis_id, ConfirmationRecord.variant_id == variant_id).order_by(ConfirmationRecord.version.desc()))
        if confirmation and confirmation.required and confirmation.status not in {"COMPLETED", "WAIVED"}:
            errors.append(f"Variant {variant_id} requires confirmation before clinical report release (status {confirmation.status})")

    reportability_ok, reportability_errors = final_reportability_state(db, analysis_id)
    if not reportability_ok:
        errors.extend(reportability_errors)
    return not errors, errors

def _criterion_summary(db: Session, analysis_id: UUID, variant_id: UUID) -> list[dict[str, Any]]:
    assessments = list(
        db.scalars(
            select(ACMGAssessment)
            .where(
                ACMGAssessment.analysis_id == analysis_id,
                ACMGAssessment.variant_id == variant_id,
            )
            .order_by(ACMGAssessment.criterion)
        )
    )
    result = []
    for row in assessments:
        chosen = row.final_assessment or row.reviewed_assessment or row.automated_assessment
        result.append(
            {
                "criterion": row.criterion,
                "state": row.state,
                "review_version": row.review_version,
                "assessment": chosen,
                "specification": {
                    "provider": row.specification_provider,
                    "id": row.specification_id,
                    "version": row.specification_version,
                },
            }
        )
    return result


def _population_summary(db: Session, analysis_id: UUID, variant_id: UUID) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(PopulationObservation, Resource)
            .join(Resource, PopulationObservation.resource_id == Resource.id)
            .where(
                PopulationObservation.analysis_id == analysis_id,
                PopulationObservation.variant_id == variant_id,
            )
            .order_by(PopulationObservation.population_level, PopulationObservation.population_code)
        )
    )
    return [
        {
            "population_level": obs.population_level,
            "population_code": obs.population_code,
            "population_label": obs.population_label,
            "allele_count": obs.allele_count,
            "allele_number": obs.allele_number,
            "allele_frequency": obs.allele_frequency,
            "homozygote_count": obs.homozygote_count,
            "availability": obs.availability,
            "quality_status": obs.quality_status,
            "resource": {"name": resource.name, "version": resource.version},
        }
        for obs, resource in rows
    ]


def _evidence_summary(db: Session, analysis_id: UUID, variant_id: UUID) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(Evidence)
            .where(Evidence.analysis_id == analysis_id, Evidence.variant_id == variant_id)
            .order_by(Evidence.created_at, Evidence.id)
        )
    )
    return [
        {
            "evidence_id": str(row.id),
            "type": row.evidence_type,
            "statement": row.statement,
            "direction": row.direction,
            "source": {"name": row.source_name, "version": row.source_version, "record_id": row.source_record_id},
            "observation_ids": list(row.observation_ids or []),
            "payload": row.payload or {},
        }
        for row in rows
    ]


def _annotation_summary(db: Session, analysis_id: UUID, variant_id: UUID) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(Annotation)
            .where(Annotation.analysis_id == analysis_id, Annotation.variant_id == variant_id)
            .order_by(Annotation.created_at, Annotation.id)
        )
    )
    return [
        {
            "provider": row.provider_name,
            "provider_version": row.provider_version,
            "resource": row.resource_name,
            "resource_version": row.resource_version,
            "normalized": (row.payload or {}).get("normalized", {}),
        }
        for row in rows
    ]


def _review_summary(db: Session, analysis_id: UUID, variant_id: UUID) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(ReviewAction)
            .where(ReviewAction.analysis_id == analysis_id, ReviewAction.variant_id == variant_id)
            .order_by(ReviewAction.sequence_number)
        )
    )
    return [
        {
            "sequence": row.sequence_number,
            "action": row.action_type,
            "reviewer_id": str(row.reviewer_id),
            "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "before": row.before_state,
            "after": row.after_state,
        }
        for row in rows
    ]


def build_report_content(db: Session, analysis: Analysis, language: str, *, report_type: str = "CLINICAL_INTERPRETATION", include_full_evidence: bool = False) -> dict[str, Any]:
    if language not in {"en", "ar", "bilingual"}:
        raise ValueError("Unsupported report language")

    case = db.get(Case, analysis.case_id)
    if case is None:
        raise ValueError("Case not found")
    if report_type not in {"CLINICAL_INTERPRETATION", "ANALYTICAL"}:
        raise ValueError("Unsupported report type")
    specimen = db.scalar(select(Specimen).where(Specimen.case_id == case.id).order_by(Specimen.created_at.desc()))

    latest_rows = _latest_by_variant(
        list(db.scalars(select(Classification).where(Classification.analysis_id == analysis.id)))
    )
    latest_rows.sort(key=lambda row: str(row.variant_id))

    findings: list[dict[str, Any]] = []
    phenotype_rows = db.scalars(select(PhenotypeObservation).where(PhenotypeObservation.case_id == case.id, (PhenotypeObservation.analysis_id == analysis.id) | (PhenotypeObservation.analysis_id.is_(None))).order_by(PhenotypeObservation.created_at)).all()
    phenotype_context = [{"hpo_id": r.hpo_id, "label": r.label, "present": r.present, "onset": r.onset, "severity": r.severity, "source": r.source} for r in phenotype_rows]
    pedigree_members = list(db.scalars(select(PedigreeMember).where(PedigreeMember.case_id == case.id).order_by(PedigreeMember.created_at, PedigreeMember.member_identifier)))
    pedigree_relationships = list(db.scalars(select(PedigreeRelationship).where(PedigreeRelationship.case_id == case.id).order_by(PedigreeRelationship.created_at)))
    pedigree_context = {
        "members": [{"member_identifier": m.member_identifier, "relationship_to_proband": m.relationship_to_proband, "sex": m.sex, "affected_status": m.affected_status, "is_proband": m.is_proband, "sampled": m.sampled} for m in pedigree_members],
        "relationships": [{"parent_member_id": str(r.parent_member_id), "child_member_id": str(r.child_member_id), "relationship_type": r.relationship_type} for r in pedigree_relationships],
    }
    reportability_complete, reportability_errors = final_reportability_state(db, analysis.id)
    for cls in latest_rows:
        decision = latest_decision(db, analysis.id, cls.variant_id)
        # Analytical reports retain the full reviewed variant set. Clinical reports
        # contain only explicitly finalized REPORT findings.
        if report_type == "CLINICAL_INTERPRETATION" and (decision is None or decision.status != "FINAL" or decision.disposition != "REPORT"):
            continue
        variant = db.get(Variant, cls.variant_id)
        if variant is None:
            raise ValueError(f"Variant {cls.variant_id} referenced by classification is missing")

        annotations = _annotation_summary(db, analysis.id, variant.id)
        normalized = {}
        if annotations:
            normalized = annotations[-1].get("normalized", {}) or {}
        gene = (normalized.get("gene") or {}).get("symbol")
        transcript = (normalized.get("transcript") or {}).get("accession")
        hgvs = normalized.get("hgvs") or {}
        consequences = normalized.get("consequence") or normalized.get("consequences") or {}

        contextual_evidence = [e for e in _evidence_summary(db, analysis.id, variant.id) if e.get("type") in {"PHENOTYPE", "GENE_DISEASE", "LITERATURE"}]
        segregation_rows = list(db.scalars(select(SegregationObservation).where(SegregationObservation.analysis_id == analysis.id, SegregationObservation.variant_id == variant.id).order_by(SegregationObservation.created_at)))
        inheritance_rows = list(db.scalars(select(InheritanceAssessment).where(InheritanceAssessment.analysis_id == analysis.id, InheritanceAssessment.variant_id == variant.id).order_by(InheritanceAssessment.created_at.desc())))
        confirmation = db.scalar(select(ConfirmationRecord).where(ConfirmationRecord.analysis_id == analysis.id, ConfirmationRecord.variant_id == variant.id).order_by(ConfirmationRecord.version.desc()))
        followups = list(db.scalars(select(FollowUpPlan).where(FollowUpPlan.analysis_id == analysis.id, FollowUpPlan.variant_id == variant.id).order_by(FollowUpPlan.created_at.desc())))
        finding = {
            "variant_id": str(variant.id),
            "canonical_key": variant.canonical_key,
            "genomic": {
                "build": variant.genome_build,
                "chromosome": variant.chromosome,
                "position": variant.position,
                "reference": variant.reference,
                "alternate": variant.alternate,
            },
            "gene": gene,
            "transcript": transcript,
            "hgvs": hgvs,
            "consequence": consequences,
            "zygosity": (normalized.get("genotype") or {}).get("zygosity"),
            "classification": cls.result,
            "classification_version": cls.version,
            "reportability": {
                "decision_id": str(decision.id) if decision else None,
                "version": decision.version if decision else None,
                "disposition": decision.disposition if decision else "NOT_DETERMINED",
                "status": decision.status if decision else "NOT_DETERMINED",
                "priority_score": decision.priority_score if decision else None,
                "priority_band": decision.priority_band if decision else None,
                "reasons": list(decision.reasons or []) if decision else [],
                "policy": f"{decision.policy_name}@{decision.policy_version}" if decision else None,
            },

            "framework": {
                "name": cls.framework_name,
                "version": cls.framework_version,
                "specification_provider": cls.specification_provider,
                "specification_id": cls.specification_id,
                "specification_version": cls.specification_version,
            },
            "acmg_criteria": _criterion_summary(db, analysis.id, variant.id),
            "population": _population_summary(db, analysis.id, variant.id),
            "review_history": _review_summary(db, analysis.id, variant.id),
            "clinical_context": {
                "hpo_terms": phenotype_context,
                "contextual_evidence": contextual_evidence,
            },
            "inheritance_context": {
                "assessments": [{"model": a.model, "status": a.status, "score": a.score, "rationale": a.rationale, "fingerprint": a.observation_fingerprint} for a in inheritance_rows],
                "segregation_observations": [{"pedigree_member_id": str(o.pedigree_member_id), "genotype": o.genotype, "zygosity": o.zygosity, "phase": o.phase, "phenotype_status": o.phenotype_status, "source": o.source, "notes": o.notes} for o in segregation_rows],
            },
            "confirmation_context": {
                "required": confirmation.required if confirmation else None,
                "status": confirmation.status if confirmation else "NOT_CONFIGURED",
                "method": confirmation.method if confirmation else None,
                "result": confirmation.result if confirmation else None,
                "laboratory": confirmation.laboratory if confirmation else None,
                "accession": confirmation.accession if confirmation else None,
                "performed_at": confirmation.performed_at.isoformat() if confirmation and confirmation.performed_at else None,
                "notes": confirmation.notes if confirmation else None,
            },
            "follow_up": [{"action_type": x.action_type, "status": x.status, "due_date": x.due_date.isoformat() if x.due_date else None, "responsible_role": x.responsible_role, "outcome": x.outcome, "notes": x.notes} for x in followups],
        }
        if include_full_evidence:
            finding["evidence"] = _evidence_summary(db, analysis.id, variant.id)
            finding["annotations"] = annotations
        findings.append(finding)

    secondary_rows = list(db.scalars(select(SecondaryFindingDecision).where(SecondaryFindingDecision.analysis_id == analysis.id).order_by(SecondaryFindingDecision.variant_id, SecondaryFindingDecision.version)))
    secondary_latest = {}
    for row in secondary_rows:
        secondary_latest[row.variant_id] = row
    secondary_findings = [{
        "variant_id": str(row.variant_id), "version": row.version, "policy": {"name": row.policy_name, "version": row.policy_version},
        "eligibility": row.eligibility, "consent_status": row.consent_status, "disposition": row.disposition,
        "status": row.status, "rationale": row.rationale, "gene_disease_context": row.gene_disease_context or {},
    } for row in secondary_latest.values() if row.status == "FINAL" and row.disposition == "REPORT"]
    tool_rows = list(db.scalars(select(Artifact).where(Artifact.analysis_id == analysis.id).order_by(Artifact.created_at, Artifact.id)))
    audit_rows = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.analysis_id == analysis.id)
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
        )
    )
    versions = analysis.configuration.get("versions", {}) if isinstance(analysis.configuration, dict) else {}

    return {
        "report_schema_version": "1.1.0",
        "report_version": 1,
        "report_status": "DRAFT",
        "report_type": report_type,
        "language": language,
        "case_id": str(case.id),
        "case_identifier": case.case_identifier,
        "analysis_id": str(analysis.id),
        "analysis_type": analysis.analysis_type,
        "test": case.clinical_context.get("test"),
        "indication": case.clinical_context.get("indication"),
        "clinical_question": case.clinical_context.get("clinical_question") or case.clinical_context.get("indication"),
        "phenotype_context": phenotype_context,
        "pedigree_context": pedigree_context,
        "secondary_findings": secondary_findings,
        "specimen": {
            "specimen_id": str(specimen.id) if specimen else None,
            "specimen_identifier": specimen.specimen_identifier if specimen else None,
            "specimen_type": specimen.specimen_type if specimen else None,
            "collection_datetime": specimen.collection_datetime.isoformat() if specimen and specimen.collection_datetime else None,
            "received_datetime": specimen.received_datetime.isoformat() if specimen and specimen.received_datetime else None,
        },
        "reference_build": analysis.reference_build,
        "final_result": {
            "status": "DRAFT",
            "release_state": "NOT_FOR_CLINICAL_RELEASE",
            "findings_count": len(findings),
            "reportable_findings_count": sum(1 for f in findings if f.get("reportability", {}).get("disposition") == "REPORT"),
            "reportability_complete": reportability_complete,
            "reportability_errors": reportability_errors,
        },
        "findings": findings,
        "methodology": (
            "SIRALOOM Variant Phase 1 VCF interpretation workflow. "
            "The report reflects the configured laboratory workflow and resource versions."
        ),
        "limitations": (
            "This Phase 1 service starts from VCF and does not perform primary sequencing, "
            "alignment, or variant calling. Clinical use requires laboratory-specific validation, "
            "qualified review, and applicable quality/regulatory controls."
        ),
        "recommendations": case.clinical_context.get("recommendations"),
        "references": case.clinical_context.get("references", []),
        "resource_versions": versions,
        "artifact_manifest": [
            {
                "artifact_id": str(a.id),
                "type": a.artifact_type,
                "filename": a.filename,
                "sha256": a.sha256,
                "size_bytes": a.size_bytes,
            }
            for a in tool_rows
        ],
        "audit_summary": {
            "event_count": len(audit_rows),
            "first_event": audit_rows[0].occurred_at.isoformat() if audit_rows else None,
            "last_event": audit_rows[-1].occurred_at.isoformat() if audit_rows else None,
        },
        "generated_at": _utc_now().isoformat(),
    }


def _html_document(content: dict[str, Any]) -> str:
    lang = content["language"]
    direction = "rtl" if lang == "ar" else "ltr"
    bilingual = lang == "bilingual"
    findings_html: list[str] = []
    for finding in content["findings"]:
        g = html.escape(str(finding.get("gene") or "-"))
        tx = html.escape(str(finding.get("transcript") or "-"))
        hgvs = finding.get("hgvs") or {}
        c_hgvs = html.escape(str(hgvs.get("coding") or "-"))
        p_hgvs = html.escape(str(hgvs.get("protein") or "-"))
        cls = html.escape(str(finding["classification"]))
        genomic = finding["genomic"]
        genomic_text = f"{genomic['build']}:{genomic['chromosome']}:{genomic['position']} {genomic['reference']}>{genomic['alternate']}"
        criteria = finding.get("acmg_criteria", [])
        criterion_rows = "".join(
            f"<tr><td>{html.escape(str(c['criterion']))}</td><td>{html.escape(json.dumps(c.get('assessment'), ensure_ascii=False))}</td></tr>"
            for c in criteria
        )
        pop_rows = "".join(
            f"<tr><td>{html.escape(str(p['population_label']))}</td><td>{html.escape(str(p['allele_frequency']))}</td><td>{html.escape(str(p['availability']))}</td><td>{html.escape(str(p['resource']['name']))} {html.escape(str(p['resource']['version']))}</td></tr>"
            for p in finding.get("population", [])
        )
        findings_html.append(
            f"""
            <section class='finding'>
              <h2>{g} — {cls}</h2>
              <p><strong>Genomic:</strong> {html.escape(genomic_text)}</p>
              <p><strong>Transcript:</strong> {tx}</p>
              <p><strong>HGVS c.:</strong> {c_hgvs}<br><strong>HGVS p.:</strong> {p_hgvs}</p>
              <p><strong>Reportability:</strong> {html.escape(str((finding.get("reportability") or {}).get("disposition", "NOT_DETERMINED")))} · <strong>Priority:</strong> {html.escape(str((finding.get("reportability") or {}).get("priority_score", "-")))}</p>
              <h3>ACMG Evidence</h3>
              <table><thead><tr><th>Criterion</th><th>Assessment</th></tr></thead><tbody>{criterion_rows or '<tr><td colspan="2">No criterion records</td></tr>'}</tbody></table>
              <h3>Population Context</h3>
              <table><thead><tr><th>Population</th><th>AF</th><th>Availability</th><th>Source</th></tr></thead><tbody>{pop_rows or '<tr><td colspan="4">No population observations</td></tr>'}</tbody></table>
            </section>
            """
        )
    title_en = "SIRALOOM Variant Interpretation Report"
    title_ar = "تقرير تفسير المتغيرات الجينية - SIRALOOM"
    title = f"{title_ar} / {title_en}" if bilingual else (title_ar if lang == "ar" else title_en)
    case_identifier = content.get("case_identifier", content.get("case_id", "-"))
    reference_build = content.get("reference_build", "-")
    final_result = content.get("final_result", {"findings_count": len(content.get("findings", []))})
    generated_at = content.get("generated_at", _utc_now().isoformat())
    report_schema_version = content.get("report_schema_version", "1.0.0")
    report_version = content.get("report_version", 1)
    return f"""<!doctype html>
<html lang='{lang}' dir='{direction}'>
<head>
<meta charset='utf-8'>
<style>
@page {{ size:A4; margin:18mm 16mm 18mm 16mm; }}
body {{ font-family: Arial, 'Noto Sans Arabic', sans-serif; color:#111; font-size:10pt; line-height:1.45; }}
h1 {{ font-size:20pt; margin-bottom:4mm; }} h2 {{ font-size:14pt; margin:8mm 0 3mm; }} h3 {{ font-size:11pt; margin:5mm 0 2mm; }}
.meta {{ border:1px solid #bbb; padding:8px; border-radius:5px; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
table {{ width:100%; border-collapse:collapse; margin:3mm 0 5mm; }}
th,td {{ border:1px solid #bbb; padding:4px; vertical-align:top; }} th {{ background:#eee; }}
.finding {{ page-break-inside:avoid; border-top:2px solid #333; padding-top:4mm; }}
.small {{ color:#444; font-size:8.5pt; }}
.footer {{ margin-top:8mm; padding-top:4mm; border-top:1px solid #bbb; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<div class='meta'>
<div class='grid'>
<div><strong>Case:</strong> {html.escape(str(case_identifier))}</div>
<div><strong>Analysis:</strong> {html.escape(content['analysis_id'])}</div>
<div><strong>Test:</strong> {html.escape(str(content.get('test') or '-'))}</div>
<div><strong>Indication:</strong> {html.escape(str(content.get('indication') or '-'))}</div>
<div><strong>Reference:</strong> {html.escape(str(reference_build))}</div>
<div><strong>Findings:</strong> {final_result.get('findings_count', 0)}</div>
</div></div>
<h2>{'Final Result' if not bilingual else 'Final Result / النتيجة النهائية'}</h2>
<p><strong>{html.escape(str(final_result.get('release_state', 'NOT_FOR_CLINICAL_RELEASE')))}</strong> — This generated artifact is not a clinical release until an authorized sign-out is recorded.</p>
{''.join(findings_html)}
<h2>{'Methodology' if not bilingual else 'Methodology / المنهجية'}</h2>
<p>{html.escape(content['methodology'])}</p>
<h2>{'Limitations' if not bilingual else 'Limitations / القيود'}</h2>
<p>{html.escape(content['limitations'])}</p>
<h2>{'Recommendations' if not bilingual else 'Recommendations / التوصيات'}</h2>
<p>{html.escape(str(content.get('recommendations') or '-'))}</p>
<h2>{'References' if not bilingual else 'References / المراجع'}</h2>
<ul>{''.join(f"<li>{html.escape(str(r))}</li>" for r in content.get('references', [])) or '<li>No case-specific references recorded.</li>'}</ul>
<div class='footer small'>
Report schema {html.escape(str(report_schema_version))} · Report version {report_version} · Generated {html.escape(str(generated_at))}
</div>
</body></html>"""


def render_html(content: dict[str, Any]) -> bytes:
    return _html_document(content).encode("utf-8")


def render_pdf(content: dict[str, Any]) -> bytes:
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise RuntimeError("WeasyPrint is required for Phase 1 HTML/PDF report rendering") from exc
    with tempfile.TemporaryDirectory(prefix="siraloom-report-") as tmp:
        html_path = Path(tmp) / "report.html"
        pdf_path = Path(tmp) / "report.pdf"
        html_path.write_bytes(render_html(content))
        try:
            HTML(filename=str(html_path), base_url=str(html_path.parent)).write_pdf(str(pdf_path))
        except Exception as exc:
            raise RuntimeError(f"Report PDF rendering failed: {exc}") from exc
        if not pdf_path.is_file() or pdf_path.stat().st_size < 500:
            raise RuntimeError("Report renderer produced no usable PDF")
        return pdf_path.read_bytes()
