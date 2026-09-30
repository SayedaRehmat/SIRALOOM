from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    evidence_type: str
    statement: str
    source_name: str | None
    source_version: str | None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InterpretationContext:
    variant_id: str
    genome_build: str
    gene: str | None
    disease: str | None
    evidence: tuple[EvidenceItem, ...]
    phenotype_terms: tuple[dict[str, Any], ...] = ()
    existing_classification: str | None = None


@dataclass(frozen=True)
class AISummary:
    summary: str
    evidence_ids: tuple[str, ...]
    uncertainties: tuple[str, ...]
    review_questions: tuple[str, ...]
    model_provider: str
    model_version: str
    prompt_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "evidence_ids": list(self.evidence_ids),
            "uncertainties": list(self.uncertainties),
            "review_questions": list(self.review_questions),
            "model_provider": self.model_provider,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
        }
