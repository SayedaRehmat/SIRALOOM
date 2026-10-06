from __future__ import annotations

from typing import Any


def normalize_annotation_payload(provider_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    provider = provider_id.strip()
    if provider == "GeneBe":
        from backend.app.adapters.annotation.genebe_normalizer import normalize_gene_be_variant
        return normalize_gene_be_variant(raw)
    if provider == "VEP":
        return {
            "genomic": {
                "genome": raw.get("genome"),
                "chromosome": raw.get("chr"),
                "position": raw.get("pos"),
                "reference": raw.get("ref"),
                "alternate": raw.get("alt"),
            },
            "gene": {"symbol": raw.get("gene_symbol"), "gene_id": raw.get("gene")},
            "transcript": raw.get("transcript"),
            "effect": raw.get("effect"),
            "hgvs_consequences": raw.get("consequences") or [],
            "hgvs": {"c": raw.get("hgvsc"), "p": raw.get("hgvsp")},
            "clinical": {},
            "population": {},
            "computational": {},
            "splice": {},
            "provenance": {
                "provider": "VEP",
                "provider_field_schema": "vep-json-transcript-consequence-v1",
            },
        }
    raise ValueError(f"No annotation normalizer registered for provider {provider_id!r}")
