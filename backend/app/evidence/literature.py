from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

@dataclass(frozen=True)
class LiteratureRecord:
    evidence_id: UUID
    variant_id: UUID
    gene: str | None
    disease: str | None
    title: str
    citation: str | None
    source_id: str | None
    source_url: str | None
    publication_year: int | None
    evidence_summary: str
    evidence_category: str
    direction: str = "NEUTRAL"
    payload: dict[str, Any] | None = None

def build_literature_record(*, variant_id: UUID, payload: dict[str, Any]) -> LiteratureRecord:
    title = str(payload.get("title") or "").strip()
    summary = str(payload.get("evidence_summary") or payload.get("summary") or "").strip()
    if not title or not summary:
        raise ValueError("Literature evidence requires title and evidence_summary")
    year = payload.get("publication_year")
    try: year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError): year = None
    direction = str(payload.get("direction") or "NEUTRAL").upper()
    if direction not in {"SUPPORTS", "REFUTES", "NEUTRAL", "UNKNOWN"}: direction = "NEUTRAL"
    return LiteratureRecord(uuid4(), variant_id, payload.get("gene"), payload.get("disease"), title,
        payload.get("citation"), payload.get("source_id") or payload.get("pmid"), payload.get("source_url"), year,
        summary, str(payload.get("evidence_category") or "CLINICAL_CASE").upper(), direction, dict(payload))
