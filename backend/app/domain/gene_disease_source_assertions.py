"""Provider-model adapters for source-preserving gene-disease reconciliation."""
from __future__ import annotations

from typing import Any, Iterable

from backend.app.domain.gene_disease_reconciliation import (
    GeneDiseaseSource,
    GeneDiseaseSourceAssertion,
)
from backend.app.domain.hgnc_crosswalk import HGNCResolutionStatus, HGNCResolver
from backend.app.domain.inheritance_review_context import normalize_clingen_moi_label


_RESOLVABLE_HGNC_STATUSES = frozenset({
    HGNCResolutionStatus.HGNC_ID,
    HGNCResolutionStatus.APPROVED_SYMBOL,
    HGNCResolutionStatus.ALIAS_SYMBOL,
    HGNCResolutionStatus.PREVIOUS_SYMBOL,
    HGNCResolutionStatus.ENSEMBL_GENE_ID,
    HGNCResolutionStatus.WITHDRAWN_MERGED,
})


def _resolve_hgnc_identifier(
    resolver: HGNCResolver | None,
    identifier: str | None,
    *,
    native_hgnc_id: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    raw_identifier = str(identifier or "").strip()
    if resolver is None:
        return native_hgnc_id, {
            "provider": "HGNC",
            "status": "NOT_CONFIGURED",
            "input": raw_identifier or native_hgnc_id,
            "resolved_hgnc_id": native_hgnc_id,
        }
    if not raw_identifier:
        return None, {
            "provider": "HGNC",
            "release": resolver.release,
            "complete_set_sha256": resolver.complete_sha256,
            "withdrawn_sha256": resolver.withdrawn_sha256,
            "status": "INVALID",
            "input": raw_identifier,
            "resolved_hgnc_id": None,
            "candidate_hgnc_ids": [],
        }
    resolution = resolver.resolve(raw_identifier)
    canonical_hgnc_id = (
        resolution.hgnc_id
        if resolution.status in _RESOLVABLE_HGNC_STATUSES and resolution.resolved
        else None
    )
    return canonical_hgnc_id, {
        "provider": "HGNC",
        "release": resolver.release,
        "complete_set_sha256": resolver.complete_sha256,
        "withdrawn_sha256": resolver.withdrawn_sha256,
        "input": raw_identifier,
        "status": resolution.status,
        "matched_field": resolution.matched_field,
        "resolved_hgnc_id": canonical_hgnc_id,
        "candidate_hgnc_ids": list(resolution.candidate_hgnc_ids),
    }


def build_gene_disease_source_assertions(
    *,
    g2p_models: Iterable[Any],
    clingen_assertions: Iterable[Any],
    g2p_resource_id: str | None,
    g2p_resource_name: str | None,
    g2p_resource_version: str | None,
    g2p_resource_sha256: str | None,
    clingen_resource_id: str | None,
    clingen_resource_name: str | None,
    clingen_resource_version: str | None,
    clingen_resource_sha256: str | None,
    g2p_request_fingerprint: str | None = None,
    g2p_response_sha256: str | None = None,
    clingen_request_fingerprint: str | None = None,
    clingen_response_sha256: str | None = None,
    hgnc_resolver: HGNCResolver | None = None,
) -> tuple[GeneDiseaseSourceAssertion, ...]:
    """Adapt source records without equating gene namespaces or MOI labels implicitly.

    G2P symbols are mapped to HGNC only through the exact, qualified resolver
    supplied by the analysis resource plan. ClinGen native HGNC accessions are
    validated against that same release. If the resolver is unavailable, native
    ClinGen IDs remain source-local and G2P assertions remain symbol-namespaced.
    """
    result: list[GeneDiseaseSourceAssertion] = []
    for model in g2p_models:
        if not all((g2p_resource_name, g2p_resource_version, g2p_resource_sha256)):
            raise ValueError("G2P release provenance is incomplete")
        hgnc_id, identifier_resolution = _resolve_hgnc_identifier(
            hgnc_resolver,
            model.gene_symbol,
        )
        raw_modes = tuple(model.inheritance_modes)
        unmapped_modes = ()
        if "UNKNOWN" in raw_modes:
            unmapped_modes = (str(model.allelic_requirement or "UNKNOWN"),)
        result.append(GeneDiseaseSourceAssertion(
            source=GeneDiseaseSource.G2P,
            source_record_id=model.source_record_id,
            gene_symbol=model.gene_symbol,
            hgnc_id=hgnc_id,
            mondo_id=model.disease_mondo,
            resource_id=g2p_resource_id,
            resource_name=g2p_resource_name,
            resource_version=g2p_resource_version,
            resource_sha256=g2p_resource_sha256,
            raw_assertion=dict(model.raw),
            source_record_sha256=getattr(model, "record_sha256", None),
            request_fingerprint=g2p_request_fingerprint,
            response_sha256=g2p_response_sha256,
            allelic_requirement=model.allelic_requirement,
            inheritance_modes=tuple(mode for mode in raw_modes if mode != "UNKNOWN"),
            molecular_mechanism=model.molecular_mechanism,
            gene_identifier_resolution=identifier_resolution,
            unmapped_inheritance_modes=unmapped_modes,
        ))

    for assertion in clingen_assertions:
        if not all((clingen_resource_name, clingen_resource_version, clingen_resource_sha256)):
            raise ValueError("ClinGen release provenance is incomplete")
        native_hgnc_id = assertion.hgnc_id
        hgnc_id, identifier_resolution = _resolve_hgnc_identifier(
            hgnc_resolver,
            native_hgnc_id or assertion.gene,
            native_hgnc_id=native_hgnc_id,
        )
        normalized_moi = normalize_clingen_moi_label(assertion.moi)
        unmapped_moi = (
            (str(assertion.moi).strip(),)
            if assertion.moi and normalized_moi is None
            else ()
        )
        result.append(GeneDiseaseSourceAssertion(
            source=GeneDiseaseSource.CLINGEN_GDV,
            source_record_id=assertion.source_record_id,
            gene_symbol=assertion.gene,
            hgnc_id=hgnc_id,
            mondo_id=assertion.mondo_id,
            resource_id=clingen_resource_id,
            resource_name=clingen_resource_name,
            resource_version=clingen_resource_version,
            resource_sha256=clingen_resource_sha256,
            raw_assertion=dict(assertion.payload),
            source_record_sha256=getattr(assertion, "record_sha256", None),
            request_fingerprint=clingen_request_fingerprint,
            response_sha256=clingen_response_sha256,
            validity=assertion.classification,
            inheritance_modes=(normalized_moi,) if normalized_moi else (),
            gene_identifier_resolution=identifier_resolution,
            unmapped_inheritance_modes=unmapped_moi,
        ))
    return tuple(result)
