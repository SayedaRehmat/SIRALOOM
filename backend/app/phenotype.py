from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterable
import re

HPO_RE = re.compile(r"^HP:\d{7}$")

@dataclass(frozen=True)
class PhenotypeTerm:
    hpo_id: str
    label: str | None = None
    present: bool = True

@dataclass(frozen=True)
class PhenotypeMatch:
    matched: tuple[str, ...]
    query_count: int
    target_count: int
    score: float
    method: str = "EXACT_HPO_OVERLAP"

def normalize_hpo_id(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not HPO_RE.fullmatch(text):
        raise ValueError(f"Invalid HPO identifier: {value!r}")
    return text

def normalize_terms(values: Iterable[Any]) -> tuple[PhenotypeTerm, ...]:
    out: list[PhenotypeTerm] = []
    seen: set[tuple[str, bool]] = set()
    for item in values:
        if isinstance(item, str):
            hpo = normalize_hpo_id(item); label = None; present = True
        elif isinstance(item, dict):
            hpo = normalize_hpo_id(item.get("hpo_id") or item.get("id"))
            label = str(item.get("label")).strip() if item.get("label") else None
            present = bool(item.get("present", True))
        else:
            raise ValueError("HPO terms must be strings or objects")
        key = (hpo, present)
        if key not in seen:
            seen.add(key); out.append(PhenotypeTerm(hpo, label, present))
    return tuple(out)

def match_hpo(query_terms: Iterable[Any], target_terms: Iterable[Any], *, ancestor_map: dict[str, list[str]] | None = None) -> PhenotypeMatch:
    query = {t.hpo_id for t in normalize_terms(query_terms) if t.present}
    target = {t.hpo_id for t in normalize_terms(target_terms) if t.present}
    expanded = set(target)
    method = "EXACT_HPO_OVERLAP"
    if ancestor_map:
        method = "HPO_OVERLAP_WITH_ANCESTORS"
        for term in list(target):
            expanded.update(normalize_hpo_id(x) for x in ancestor_map.get(term, []))
    matched = tuple(sorted(query & expanded))
    score = len(matched) / len(query) if query else 0.0
    return PhenotypeMatch(matched, len(query), len(target), round(score, 6), method)

def priority_adjustment(score: float) -> int:
    if score >= 0.8: return 25
    if score >= 0.5: return 15
    if score > 0: return 5
    return 0
