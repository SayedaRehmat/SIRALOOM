"""Provider-model adapters for source-preserving gene-disease reconciliation."""
from __future__ import annotations
from typing import Any, Iterable
from backend.app.domain.gene_disease_reconciliation import GeneDiseaseSource, GeneDiseaseSourceAssertion


def build_gene_disease_source_assertions(
    *, g2p_models: Iterable[Any], clingen_assertions: Iterable[Any],
    g2p_resource_id: str | None, g2p_resource_name: str | None,
    g2p_resource_version: str | None, g2p_resource_sha256: str | None,
    clingen_resource_id: str | None, clingen_resource_name: str | None,
    clingen_resource_version: str | None, clingen_resource_sha256: str | None,
) -> tuple[GeneDiseaseSourceAssertion, ...]:
    """Adapt actual provider records; never infer cross-namespace identifiers."""
    result: list[GeneDiseaseSourceAssertion] = []
    for model in g2p_models:
        if not all((g2p_resource_name, g2p_resource_version, g2p_resource_sha256)):
            raise ValueError("G2P release provenance is incomplete")
        result.append(GeneDiseaseSourceAssertion(
            source=GeneDiseaseSource.G2P, source_record_id=model.source_record_id,
            gene_symbol=model.gene_symbol, hgnc_id=None, mondo_id=model.disease_mondo,
            resource_id=g2p_resource_id, resource_name=g2p_resource_name,
            resource_version=g2p_resource_version, resource_sha256=g2p_resource_sha256,
            raw_assertion=dict(model.raw), allelic_requirement=model.allelic_requirement,
            inheritance_modes=tuple(model.inheritance_modes), molecular_mechanism=model.molecular_mechanism,
        ))
    for assertion in clingen_assertions:
        if not all((clingen_resource_name, clingen_resource_version, clingen_resource_sha256)):
            raise ValueError("ClinGen release provenance is incomplete")
        result.append(GeneDiseaseSourceAssertion(
            source=GeneDiseaseSource.CLINGEN_GDV, source_record_id=assertion.source_record_id,
            gene_symbol=assertion.gene, hgnc_id=assertion.hgnc_id, mondo_id=assertion.mondo_id,
            resource_id=clingen_resource_id, resource_name=clingen_resource_name,
            resource_version=clingen_resource_version, resource_sha256=clingen_resource_sha256,
            raw_assertion=dict(assertion.payload), validity=assertion.classification,
            inheritance_modes=(assertion.moi,) if assertion.moi else (),
        ))
    return tuple(result)
