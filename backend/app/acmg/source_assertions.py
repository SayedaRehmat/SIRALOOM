"""Persistence boundary for source-level ACMG/ClinGen criterion assertions.

Source assertions are evidence-derived observations. They are deliberately not
CriterionAssessment objects and never create a SIRALOOM Classification.
"""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import ACMGSourceAssertion, Evidence

PATHOGENIC_CRITERION_PREFIXES = ("PVS", "PS", "PM", "PP")
BENIGN_CRITERION_PREFIXES = ("BA", "BS", "BP")


def _source_direction(criterion: str) -> str:
    code = criterion.strip().upper()
    if code.startswith(PATHOGENIC_CRITERION_PREFIXES):
        return "SUPPORTS"
    if code.startswith(BENIGN_CRITERION_PREFIXES):
        return "REFUTES"
    return "NEUTRAL"


def persist_clingen_source_assertions(
    db: Session, *, evidence: Evidence
) -> list[ACMGSourceAssertion]:
    """Materialize criterion-level ClinGen assertions from one persisted Evidence row.

    The Evidence row is the provenance boundary. Every source assertion points
    back to it and retains source identity. No final classification is inferred.
    """
    payload = evidence.payload or {}
    raw_items = payload.get("criterion_assertions") or ()
    if not raw_items:
        return []

    created: list[ACMGSourceAssertion] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip().upper()
        status = str(raw.get("status") or "").strip().upper()
        if not code or status not in {"MET", "NOT_MET"}:
            continue
        pmids = tuple(
            dict.fromkeys(
                str(x).strip()
                for x in (raw.get("pmids") or ())
                if str(x).strip()
            )
        )
        normalized = {
            "criterion": code,
            "status": status,
            "strength": raw.get("strength"),
            "source": raw.get("source"),
            "rationale": raw.get("rationale"),
            "pmids": list(pmids),
            "source_record_id": evidence.source_record_id,
            "source_classification": payload.get("classification"),
            "condition": payload.get("condition"),
            "gene": payload.get("gene"),
            "mondo_id": payload.get("mondo_id"),
            "expert_panel": payload.get("expert_panel"),
            "evidence_id": str(evidence.id),
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                normalized, sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")
        ).hexdigest()
        existing = db.scalar(
            select(ACMGSourceAssertion).where(
                ACMGSourceAssertion.assertion_fingerprint == fingerprint
            )
        )
        if existing is not None:
            created.append(existing)
            continue

        row = ACMGSourceAssertion(
            id=uuid4(),
            analysis_id=evidence.analysis_id,
            variant_id=evidence.variant_id,
            evidence_id=evidence.id,
            criterion=code,
            status=status,
            strength=str(raw.get("strength")).strip() if raw.get("strength") else None,
            source_name=evidence.source_name,
            source_version=evidence.source_version,
            source_record_id=evidence.source_record_id,
            source_classification=payload.get("classification"),
            condition=payload.get("condition"),
            gene=payload.get("gene"),
            mondo_id=payload.get("mondo_id"),
            expert_panel=payload.get("expert_panel"),
            rationale=raw.get("rationale"),
            pmids=list(pmids),
            source_payload={
                "criterion_source": raw.get("source"),
                "direction": _source_direction(code),
                "criterion_detail_available": payload.get("criterion_detail_available"),
                "criterion_detail_note": payload.get("criterion_detail_note"),
                "erepo_classification_url": payload.get("erepo_classification_url"),
            },
            assertion_fingerprint=fingerprint,
        )
        db.add(row)
        created.append(row)
    return created
