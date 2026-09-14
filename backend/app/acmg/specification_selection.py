from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import ClinGenSpecification

@dataclass(frozen=True)
class SpecificationCandidate:
    id: str
    specification_id: str
    version: str
    genes: tuple[str, ...]
    diseases: tuple[str, ...]
    score: int

@dataclass(frozen=True)
class SelectionResult:
    status: str
    selected: SpecificationCandidate | None
    candidates: tuple[SpecificationCandidate, ...]
    reason: str

class ClinGenSpecificationSelector:
    """Select only imported, explicitly validated ClinGen snapshots.

    Matching is deterministic and fail-closed. A tie among equally specific
    applicable specifications is not resolved silently.
    """
    @staticmethod
    def _norm(value: str) -> str:
        return " ".join(value.strip().casefold().split())

    def candidates(
        self,
        db: Session,
        *,
        gene: str,
        disease: str | None = None,
    ) -> list[SpecificationCandidate]:
        if not gene.strip():
            raise ValueError("gene is required")
        rows = db.scalars(
            select(ClinGenSpecification).where(
                ClinGenSpecification.provider == "ClinGen",
                ClinGenSpecification.validated_for_automation.is_(True),
            )
        ).all()
        ngene = self._norm(gene)
        ndisease = self._norm(disease) if disease else None
        results: list[SpecificationCandidate] = []
        for row in rows:
            genes = tuple(str(x) for x in (row.gene_scope or []) if isinstance(x, str))
            diseases = tuple(str(x) for x in (row.disease_scope or []) if isinstance(x, str))
            gene_match = ngene in {self._norm(x) for x in genes}
            if not gene_match:
                continue
            disease_match = bool(ndisease and ndisease in {self._norm(x) for x in diseases})
            # More specific context outranks gene-only context. A specification
            # with explicit disease scope must not be treated as gene-only when
            # the requested disease does not match.
            if diseases and not disease_match:
                continue
            score = 2 if disease_match else 1
            results.append(SpecificationCandidate(str(row.id), row.specification_id, row.version, genes, diseases, score))
        results.sort(key=lambda x: (-x.score, x.specification_id, x.version, x.id))
        return results

    def select(self, db: Session, *, gene: str, disease: str | None = None) -> SelectionResult:
        candidates = self.candidates(db, gene=gene, disease=disease)
        if not candidates:
            return SelectionResult("NOT_FOUND", None, (), "No validated ClinGen specification is applicable to the supplied gene/disease context.")
        top = candidates[0]
        tied = tuple(c for c in candidates if c.score == top.score)
        if len(tied) > 1:
            return SelectionResult("AMBIGUOUS", None, tuple(candidates), "Multiple equally specific validated ClinGen specifications apply; human/configuration selection is required.")
        return SelectionResult("SELECTED", top, tuple(candidates), "A single validated ClinGen specification matched the supplied context.")


def validate_snapshot_for_automation(row: ClinGenSpecification, *, approved_by: str, reason: str, validation_reference: str | None = None) -> dict[str, Any]:
    """Strict structural validation; this is not a clinical validation study."""
    if not approved_by.strip():
        raise ValueError("approved_by is required")
    if not reason.strip():
        raise ValueError("validation reason is required")
    if row.provider != "ClinGen":
        raise ValueError("Only ClinGen snapshots can be activated by this validator")
    if row.framework.casefold() != "acmg/amp":
        raise ValueError("Only ACMG/AMP ClinGen specifications are supported by this activation path")
    if not row.version.strip():
        raise ValueError("Specification version is required")
    if not row.gene_scope:
        raise ValueError("Specification must have a non-empty gene scope")
    if not row.criteria:
        raise ValueError("Specification must contain structured criterion data")
    return {
        "approved_by": approved_by,
        "reason": reason,
        "validation_reference": validation_reference,
        "validation_kind": "STRUCTURAL_AND_CONFIGURATION_REVIEW",
    }
