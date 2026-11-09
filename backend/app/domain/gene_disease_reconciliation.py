"""Source-preserving gene–disease assertion reconciliation.

Reconciliation is contextual evidence only. It never upgrades validity, infers
penetrance, or emits variant/inheritance compatibility conclusions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping


class GeneDiseaseSource(StrEnum):
    G2P = "G2P"
    CLINGEN_GDV = "CLINGEN_GDV"


class GeneIdentifierNamespace(StrEnum):
    HGNC = "HGNC"
    SYMBOL = "SYMBOL"


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    G2P_ONLY = "G2P_ONLY"
    CLINGEN_ONLY = "CLINGEN_ONLY"
    UNMATCHABLE_MISSING_MONDO = "UNMATCHABLE_MISSING_MONDO"
    UNMATCHABLE_IDENTIFIER_NAMESPACE = "UNMATCHABLE_IDENTIFIER_NAMESPACE"


class DimensionStatus(StrEnum):
    AGREE = "AGREE"
    CONFLICT = "CONFLICT"
    G2P_ONLY = "G2P_ONLY"
    CLINGEN_ONLY = "CLINGEN_ONLY"
    NOT_PROVIDED = "NOT_PROVIDED"
    UNMAPPED = "UNMAPPED"


@dataclass(frozen=True, slots=True)
class GeneDiseaseSourceAssertion:
    """One unmodified source assertion plus its acquisition provenance."""

    source: GeneDiseaseSource
    source_record_id: str
    gene_symbol: str | None
    hgnc_id: str | None
    mondo_id: str | None
    resource_id: str | None
    resource_name: str
    resource_version: str
    resource_sha256: str
    raw_assertion: Mapping[str, Any]
    source_record_sha256: str | None = None
    request_fingerprint: str | None = None
    response_sha256: str | None = None
    validity: str | None = None
    allelic_requirement: str | None = None
    inheritance_modes: tuple[str, ...] = ()
    molecular_mechanism: str | None = None
    penetrance: str | None = None

    def __post_init__(self) -> None:
        if not self.source_record_id.strip():
            raise ValueError("source_record_id is required")
        if not self.resource_name.strip() or not self.resource_version.strip():
            raise ValueError("resource name and version are required")
        digest = self.resource_sha256.lower().removeprefix("sha256:")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("resource_sha256 must be a SHA-256 hex digest")
        if self.hgnc_id and not self.hgnc_id.upper().startswith("HGNC:"):
            raise ValueError("hgnc_id must use the HGNC: identifier namespace")
        if self.mondo_id and not self.mondo_id.upper().startswith("MONDO:"):
            raise ValueError("mondo_id must use the MONDO: identifier namespace")


@dataclass(frozen=True, slots=True)
class DimensionReconciliation:
    status: DimensionStatus
    g2p_values: tuple[str, ...] = ()
    clingen_values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GeneDiseaseReconciliation:
    reconciliation_id: str
    status: ReconciliationStatus
    gene_identifier_namespace: GeneIdentifierNamespace | None
    gene_identifier: str | None
    mondo_id: str | None
    g2p_assertions: tuple[GeneDiseaseSourceAssertion, ...]
    clingen_assertions: tuple[GeneDiseaseSourceAssertion, ...]
    dimensions: Mapping[str, DimensionReconciliation]
    requires_human_review: bool
    review_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip().casefold() for value in values if str(value).strip()}))


def _dimension(g2p: tuple[str, ...], clingen: tuple[str, ...]) -> DimensionReconciliation:
    left, right = _canonical(g2p), _canonical(clingen)
    if left and right:
        status = DimensionStatus.AGREE if left == right else DimensionStatus.CONFLICT
    elif left:
        status = DimensionStatus.G2P_ONLY
    elif right:
        status = DimensionStatus.CLINGEN_ONLY
    else:
        status = DimensionStatus.NOT_PROVIDED
    return DimensionReconciliation(status=status, g2p_values=left, clingen_values=right)


def _gene_key(assertion: GeneDiseaseSourceAssertion):
    # Never equate an HGNC identifier with a symbol-only assertion. A
    # cross-namespace mapping requires a separately governed HGNC crosswalk.
    if assertion.hgnc_id:
        return GeneIdentifierNamespace.HGNC, assertion.hgnc_id.upper()
    if assertion.gene_symbol:
        return GeneIdentifierNamespace.SYMBOL, assertion.gene_symbol.strip().upper()
    return None, None


def _stable_id(namespace, gene_id, mondo, g2p, clingen, status) -> str:
    import hashlib
    import json

    payload = {
        "namespace": namespace.value if namespace else None,
        "gene": gene_id,
        "mondo": mondo,
        "g2p": sorted(item.source_record_id for item in g2p),
        "clingen": sorted(item.source_record_id for item in clingen),
        "status": status.value,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def reconcile_gene_disease_assertions(
    assertions: tuple[GeneDiseaseSourceAssertion, ...] | list[GeneDiseaseSourceAssertion],
) -> tuple[GeneDiseaseReconciliation, ...]:
    """Group exact identifier pairs and preserve all unmatched source records."""
    buckets: dict[tuple[Any, ...], dict[GeneDiseaseSource, list[GeneDiseaseSourceAssertion]]] = {}
    for item in assertions:
        namespace, gene_id = _gene_key(item)
        if not item.mondo_id:
            key = ("MISSING_MONDO", item.source, item.source_record_id)
        elif namespace is None:
            key = ("MISSING_GENE", item.source, item.source_record_id)
        else:
            key = (namespace, gene_id, item.mondo_id.upper())
        buckets.setdefault(key, {GeneDiseaseSource.G2P: [], GeneDiseaseSource.CLINGEN_GDV: []})[item.source].append(item)

    results = []
    for key, grouped in buckets.items():
        g2p = tuple(sorted(grouped[GeneDiseaseSource.G2P], key=lambda x: x.source_record_id))
        clingen = tuple(sorted(grouped[GeneDiseaseSource.CLINGEN_GDV], key=lambda x: x.source_record_id))
        if key[0] == "MISSING_MONDO":
            status = ReconciliationStatus.UNMATCHABLE_MISSING_MONDO
            namespace = None
            gene_id = None
            mondo = None
        elif key[0] == "MISSING_GENE":
            status = ReconciliationStatus.UNMATCHABLE_IDENTIFIER_NAMESPACE
            namespace = None
            gene_id = None
            mondo = g2p[0].mondo_id if g2p else (clingen[0].mondo_id if clingen else None)
        else:
            namespace, gene_id, mondo = key
            if g2p and clingen:
                status = ReconciliationStatus.MATCHED
            elif g2p:
                status = ReconciliationStatus.G2P_ONLY
            else:
                status = ReconciliationStatus.CLINGEN_ONLY

        dimensions = {
            "validity": _dimension(
                tuple(x.validity for x in g2p if x.validity),
                tuple(x.validity for x in clingen if x.validity),
            ),
            "allelic_requirement": _dimension(
                tuple(x.allelic_requirement for x in g2p if x.allelic_requirement),
                tuple(x.allelic_requirement for x in clingen if x.allelic_requirement),
            ),
            "inheritance_mode": _dimension(
                tuple(mode for x in g2p for mode in x.inheritance_modes),
                tuple(mode for x in clingen for mode in x.inheritance_modes),
            ),
            "molecular_mechanism": _dimension(
                tuple(x.molecular_mechanism for x in g2p if x.molecular_mechanism),
                tuple(x.molecular_mechanism for x in clingen if x.molecular_mechanism),
            ),
        }
        reasons = []
        if status != ReconciliationStatus.MATCHED:
            reasons.append(f"ASSOCIATION_{status.value}")
        if any(value.status == DimensionStatus.CONFLICT for value in dimensions.values()):
            reasons.append("SOURCE_DIMENSION_CONFLICT")
        if any(value.status in {DimensionStatus.G2P_ONLY, DimensionStatus.CLINGEN_ONLY} for value in dimensions.values()):
            reasons.append("SOURCE_DIMENSION_INCOMPLETE")
        if any(not x.hgnc_id for x in (*g2p, *clingen)):
            reasons.append("CANONICAL_HGNC_IDENTIFIER_INCOMPLETE")
        if any(not x.mondo_id for x in (*g2p, *clingen)):
            reasons.append("CANONICAL_MONDO_IDENTIFIER_INCOMPLETE")
        # Penetrance is deliberately not reconciled into an inferred value.
        if any(x.penetrance for x in (*g2p, *clingen)):
            reasons.append("PENETRANCE_REQUIRES_SEPARATE_SOURCE_POLICY")
        results.append(GeneDiseaseReconciliation(
            reconciliation_id=_stable_id(namespace, gene_id, mondo, g2p, clingen, status),
            status=status,
            gene_identifier_namespace=namespace,
            gene_identifier=gene_id,
            mondo_id=mondo,
            g2p_assertions=g2p,
            clingen_assertions=clingen,
            dimensions=dimensions,
            requires_human_review=bool(reasons),
            review_reasons=tuple(sorted(set(reasons))),
        ))
    return tuple(sorted(results, key=lambda x: (x.gene_identifier_namespace.value if x.gene_identifier_namespace else "", x.gene_identifier or "", x.mondo_id or "", x.reconciliation_id)))
