"""ClinGen specification selection and immutable snapshotting.

A specification is activated only when explicitly selected/configured. The
registry can store an externally fetched CSpec entity, but it never upgrades a
baseline ACMG assessment merely because a ClinGen record exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.app.adapters.clingen.cspec import CSpecClient, CSpecEntity
from backend.app.acmg.specifications import CriterionSpecification


@dataclass(frozen=True)
class ClinGenSpecificationSnapshot:
    specification_id: str
    version: str
    provider: str
    framework: str
    source_iri: str | None
    modified_at: str | None
    gene_scope: tuple[str, ...]
    disease_scope: tuple[str, ...]
    criteria: dict[str, dict[str, Any]]
    raw_entity: dict[str, Any]
    retrieved_at: str

    def to_criterion_specification(self) -> CriterionSpecification:
        return CriterionSpecification(
            specification_id=self.specification_id,
            version=self.version,
            provider=self.provider,
            framework=self.framework,
            criteria=self.criteria,
            scope={
                "genes": list(self.gene_scope),
                "diseases": list(self.disease_scope),
                "source_iri": self.source_iri,
                "modified_at": self.modified_at,
            },
        )


def snapshot_ruleset(entity: CSpecEntity) -> ClinGenSpecificationSnapshot:
    if entity.ent_type != "RuleSet":
        raise ValueError(f"Expected RuleSet entity, got {entity.ent_type}")
    content = entity.content
    version = _first_text(content, "version", "versionString", "release")
    if not version:
        raise ValueError("ClinGen RuleSet is missing a version")
    framework = _first_text(content, "framework", "frameworkName") or "ACMG/AMP"
    genes = tuple(_extract_labels(content.get("genes") or content.get("gene")))
    diseases = tuple(_extract_labels(content.get("diseases") or content.get("disease")))
    criteria = _extract_criteria(content)
    return ClinGenSpecificationSnapshot(
        specification_id=entity.ent_id,
        version=version,
        provider="ClinGen",
        framework=framework,
        source_iri=entity.ent_iri,
        modified_at=entity.modified,
        gene_scope=genes,
        disease_scope=diseases,
        criteria=criteria,
        raw_entity=entity.raw,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )


def fetch_ruleset(client: CSpecClient, ruleset_id: str) -> ClinGenSpecificationSnapshot:
    return snapshot_ruleset(client.get_entity("RuleSet", ruleset_id, detail="high"))


def _first_text(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def _extract_labels(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for item in value:
        if isinstance(item, str):
            labels.append(item)
        elif isinstance(item, dict):
            for key in ("label", "symbol", "name", "entId", "id"):
                v = item.get(key)
                if isinstance(v, str) and v:
                    labels.append(v)
                    break
    return labels


def _extract_criteria(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract only clearly structured criterion dictionaries.

    CSpec content is evolving. The adapter does not invent criteria from free
    text. If the response shape does not expose structured criterion data, the
    snapshot is still stored but has an empty criteria mapping and therefore
    cannot be activated for automated criterion assessment.
    """
    candidates = content.get("criteria") or content.get("criteriaSpecifications") or content.get("criteriaCode")
    if not isinstance(candidates, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        code = item.get("criterion") or item.get("code") or item.get("label")
        if not isinstance(code, str) or code not in _ACMG_CODES:
            continue
        result[code] = dict(item)
    return result


_ACMG_CODES = {
    "PVS1", "PS1", "PS2", "PS3", "PS4", "PM1", "PM2", "PM3", "PM4", "PM5", "PM6",
    "PP1", "PP2", "PP3", "PP4", "PP5", "BA1", "BS1", "BS2", "BS3", "BS4", "BP1",
    "BP2", "BP3", "BP4", "BP5", "BP6", "BP7",
}
