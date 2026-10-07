"""Governed ClinGen CSpec provider.

Retrieves official ClinGen SequenceVariantInterpretation specifications through
the documented CSpec REST API. The provider returns a normalized specification
snapshot with raw/provenance data; it never produces a SIRALOOM classification.

Current-version resolution requires a governed HGNC or MONDO identifier in the
execution contract. A plain gene symbol is not treated as an undocumented
search parameter.
"""
from __future__ import annotations

from typing import Any

from backend.app.acmg.clingen_registry import (
    ClinGenSpecificationSnapshot,
    fetch_current_sequence_variant_interpretation,
    fetch_sequence_variant_interpretation,
)
from backend.app.adapters.clingen.cspec import CSpecClient, CSpecClientError


class ClinGenCSpecProviderError(RuntimeError):
    pass


class ClinGenCSpecProvider:
    provider_id = "ClinGen CSpec"
    provider_version = "CSpec"
    supported_builds = frozenset({"GRCh37", "GRCh38"})

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 20.0,
        toolchain: dict[str, Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.toolchain = dict(toolchain or {})

    @classmethod
    def from_execution_contract(cls, resolved: Any) -> "ClinGenCSpecProvider":
        contract = resolved.contract
        if contract.access_method not in {
            "HTTPS",
            "HTTP",
            "API",
            "HTTP_API",
            "REMOTE_API",
        }:
            raise ClinGenCSpecProviderError(
                "ClinGen CSpec requires a governed HTTP(S) API execution contract"
            )
        endpoint = contract.endpoint or contract.location
        if not endpoint:
            raise ClinGenCSpecProviderError(
                "ClinGen CSpec execution contract requires endpoint/location"
            )
        return cls(
            base_url=str(endpoint),
            timeout_seconds=float(
                (contract.toolchain or {}).get("timeout_seconds", 20.0)
            ),
            toolchain=contract.toolchain,
        )

    def get_specification(
        self,
        *,
        specification_id: str,
        version: str,
    ) -> ClinGenSpecificationSnapshot:
        try:
            return fetch_sequence_variant_interpretation(
                CSpecClient(
                    base_url=self.base_url,
                    timeout_seconds=self.timeout_seconds,
                ),
                specification_id,
                version,
            )
        except (CSpecClientError, ValueError) as exc:
            raise ClinGenCSpecProviderError(str(exc)) from exc

    def get_current_specification(
        self,
        *,
        gene_id: str | None = None,
        disease_id: str | None = None,
    ) -> ClinGenSpecificationSnapshot:
        configured_gene = gene_id or self.toolchain.get("gene_id")
        configured_disease = disease_id or self.toolchain.get("disease_id")
        if bool(configured_gene) == bool(configured_disease):
            raise ClinGenCSpecProviderError(
                "CSpec current-version resolution requires exactly one governed "
                "gene_id (HGNC) or disease_id (MONDO)"
            )
        try:
            return fetch_current_sequence_variant_interpretation(
                CSpecClient(
                    base_url=self.base_url,
                    timeout_seconds=self.timeout_seconds,
                ),
                gene_id=str(configured_gene) if configured_gene else None,
                disease_id=str(configured_disease) if configured_disease else None,
            )
        except (CSpecClientError, ValueError) as exc:
            raise ClinGenCSpecProviderError(str(exc)) from exc
