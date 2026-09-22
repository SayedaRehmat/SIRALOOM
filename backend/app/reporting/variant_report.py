from __future__ import annotations

import csv
import io
import json
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Annotation,
    Classification,
    Evidence,
    PopulationObservation,
    Variant,
    ReportabilityDecision,
    AnalysisPartition,
)


CSV_COLUMNS = [
    "variant_id", "canonical_key", "genome_build", "chromosome", "position", "reference", "alternate",
    "normalization_status", "gene", "transcript", "consequence", "protein_change", "clinvar_significance",
    "global_af", "mid_af", "local_af", "functional_summary", "splice_summary", "literature_evidence_count",
    "evidence_count", "acmg_criteria", "classification", "classification_state", "review_status", "reportability",
]


def _first_value(mapping: dict, *paths: tuple[str, ...]) -> object | None:
    for path in paths:
        current: object = mapping
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if current is not None:
            return current
    return None


def _text(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def build_variant_rows(db: Session, analysis_id: UUID) -> list[dict[str, object]]:
    partitions = db.scalars(
        select(AnalysisPartition)
        .where(
            AnalysisPartition.analysis_id == analysis_id,
            AnalysisPartition.step_id == "normalize",
        )
        .order_by(AnalysisPartition.ordinal)
    ).all()

    variant_ids: list[UUID] = []
    seen: set[UUID] = set()
    for partition in partitions:
        for raw_id in ((partition.metadata_json or {}).get("variant_ids") or []):
            try:
                variant_id = UUID(str(raw_id))
            except (TypeError, ValueError):
                continue
            if variant_id not in seen:
                seen.add(variant_id)
                variant_ids.append(variant_id)

    if variant_ids:
        variants = db.scalars(
            select(Variant)
            .where(Variant.id.in_(variant_ids))
            .order_by(
                Variant.chromosome,
                Variant.position,
                Variant.reference,
                Variant.alternate,
            )
        ).all()
    else:
        variants = db.scalars(
            select(Variant)
            .join(Annotation, Annotation.variant_id == Variant.id)
            .where(Annotation.analysis_id == analysis_id)
            .distinct()
            .order_by(
                Variant.chromosome,
                Variant.position,
                Variant.reference,
                Variant.alternate,
            )
        ).all()
    annotations = db.scalars(select(Annotation).where(Annotation.analysis_id == analysis_id)).all()
    populations = db.scalars(select(PopulationObservation).where(PopulationObservation.analysis_id == analysis_id)).all()
    evidence = db.scalars(select(Evidence).where(Evidence.analysis_id == analysis_id)).all()
    acmg = db.scalars(select(ACMGAssessment).where(ACMGAssessment.analysis_id == analysis_id)).all()
    classifications = db.scalars(select(Classification).where(Classification.analysis_id == analysis_id)).all()
    reportability = db.scalars(select(ReportabilityDecision).where(ReportabilityDecision.analysis_id == analysis_id)).all()

    ann_by_variant: dict[UUID, Annotation] = {}
    for row in annotations:
        ann_by_variant.setdefault(row.variant_id, row)
    pop_by_variant: dict[UUID, list[PopulationObservation]] = {}
    for row in populations:
        pop_by_variant.setdefault(row.variant_id, []).append(row)
    ev_by_variant: dict[UUID, list[Evidence]] = {}
    for row in evidence:
        ev_by_variant.setdefault(row.variant_id, []).append(row)
    acmg_by_variant: dict[UUID, list[ACMGAssessment]] = {}
    for row in acmg:
        acmg_by_variant.setdefault(row.variant_id, []).append(row)
    cls_by_variant: dict[UUID, list[Classification]] = {}
    rep_by_variant: dict[UUID, list[ReportabilityDecision]] = {}
    for row in classifications:
        cls_by_variant.setdefault(row.variant_id, []).append(row)
    for row in reportability:
        rep_by_variant.setdefault(row.variant_id, []).append(row)

    rows: list[dict[str, object]] = []
    for variant in variants:
        ann = ann_by_variant.get(variant.id)
        normalized = ((ann.payload or {}).get("normalized") or {}) if ann else {}
        gene = _first_value(normalized, ("gene", "symbol"), ("gene_symbol",))
        transcript = _first_value(normalized, ("transcript", "id"), ("transcript_id",))
        consequence = _first_value(normalized, ("consequence",), ("most_severe_consequence",))
        protein_change = _first_value(normalized, ("protein_change",), ("hgvsp",))
        clinvar = _first_value(normalized, ("clinvar", "significance"), ("clinvar_significance",))
        functional = normalized.get("functional") if isinstance(normalized, dict) else None
        splice = normalized.get("splice") if isinstance(normalized, dict) else None

        by_code = {p.population_code: p for p in pop_by_variant.get(variant.id, [])}
        global_pop = by_code.get("GLOBAL")
        mid_pop = by_code.get("MID")
        local_pop = by_code.get("LOCAL")
        variant_evidence = ev_by_variant.get(variant.id, [])
        criteria = acmg_by_variant.get(variant.id, [])
        ordered_cls = sorted(cls_by_variant.get(variant.id, []), key=lambda c: c.version)
        classification = ordered_cls[-1] if ordered_cls else None
        decisions = sorted(rep_by_variant.get(variant.id, []), key=lambda d: d.version)
        decision = decisions[-1] if decisions else None
        reportability_value = decision.disposition if decision else "NOT_DETERMINED"
        rows.append({
            "variant_id": str(variant.id), "canonical_key": variant.canonical_key, "genome_build": variant.genome_build,
            "chromosome": variant.chromosome, "position": variant.position, "reference": variant.reference,
            "alternate": variant.alternate, "normalization_status": variant.normalization_status, "gene": _text(gene),
            "transcript": _text(transcript), "consequence": _text(consequence), "protein_change": _text(protein_change),
            "clinvar_significance": _text(clinvar), "global_af": global_pop.allele_frequency if global_pop else None,
            "mid_af": mid_pop.allele_frequency if mid_pop else None, "local_af": local_pop.allele_frequency if local_pop else None,
            "functional_summary": _text(functional), "splice_summary": _text(splice),
            "literature_evidence_count": sum(1 for e in variant_evidence if str(e.evidence_type).upper() == "LITERATURE"),
            "evidence_count": len(variant_evidence), "acmg_criteria": ",".join(sorted({a.criterion for a in criteria})),
            "classification": classification.result if classification else "NOT_ASSESSED",
            "classification_state": classification.state if classification else "NOT_ASSESSED",
            "review_status": classification.review_status if classification else "NOT_REVIEWED",
            "reportability": str(reportability_value),
        })
    return rows


def render_csv(rows: list[dict[str, object]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def render_json(rows: list[dict[str, object]]) -> bytes:
    return json.dumps({"schema_version": "1.0.0", "variant_count": len(rows), "variants": rows}, ensure_ascii=False, indent=2).encode("utf-8")
