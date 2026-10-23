from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

HPO_RE = re.compile(r"^HP:\d{7}$")

@dataclass(frozen=True)
class PhenotypeTerm:
    hpo_id: str
    label: str | None = None
    status: str = "PRESENT"

    @property
    def present(self) -> bool:
        return self.status == "PRESENT"


PHENOTYPE_STATUSES = frozenset({"PRESENT", "ABSENT", "EXCLUDED", "UNKNOWN", "NOT_ASSESSED"})

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
    seen: set[tuple[str, str]] = set()
    for item in values:
        if isinstance(item, str):
            hpo = normalize_hpo_id(item); label = None; status = "PRESENT"
        elif isinstance(item, dict):
            hpo = normalize_hpo_id(item.get("hpo_id") or item.get("id"))
            label = str(item.get("label")).strip() if item.get("label") else None
            status_value = item.get("phenotype_status") or item.get("status")
            if status_value is None:
                status = "PRESENT" if bool(item.get("present", True)) else "ABSENT"
            else:
                status = str(status_value).strip().upper()
                if status not in PHENOTYPE_STATUSES:
                    raise ValueError(f"Unsupported phenotype status: {status_value!r}")
                if "present" in item and bool(item["present"]) != (status == "PRESENT"):
                    raise ValueError("Phenotype status conflicts with legacy present flag")
        else:
            raise TypeError("HPO terms must be strings or objects")
        key = (hpo, status)
        if key not in seen:
            seen.add(key); out.append(PhenotypeTerm(hpo, label, status))
    return tuple(out)

def match_hpo(query_terms: Iterable[Any], target_terms: Iterable[Any], *, ancestor_map: dict[str, list[str]] | None = None) -> PhenotypeMatch:
    query = {t.hpo_id for t in normalize_terms(query_terms) if t.status == "PRESENT"}
    target = {t.hpo_id for t in normalize_terms(target_terms) if t.status == "PRESENT"}
    expanded = set(target)
    method = "EXACT_HPO_OVERLAP"
    if ancestor_map:
        method = "HPO_OVERLAP_WITH_ANCESTORS"
        for term in list(target):
            expanded.update(normalize_hpo_id(x) for x in ancestor_map.get(term, []))
    matched = tuple(sorted(query & expanded))
    score = len(matched) / len(query) if query else 0.0
    return PhenotypeMatch(matched, len(query), len(target), round(score, 6), method)
