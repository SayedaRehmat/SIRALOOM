from __future__ import annotations

from typing import Any


def _object_list(raw: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = raw.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"VEP {field} must be a list of objects when present")
    return value


def normalize_annotation_payload(provider_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    provider = provider_id.strip()
    if provider == "GeneBe":
        from backend.app.adapters.annotation.genebe_normalizer import normalize_gene_be_variant
        return normalize_gene_be_variant(raw)
    if provider == "VEP":
        transcript_consequences = _object_list(raw, "transcript_consequences" if raw.get("transcript_consequences") is not None else "consequences" if raw.get("consequences") is not None else "hgvs_consequences")
        intergenic = _object_list(raw, "intergenic_consequences")
        regulatory = _object_list(raw, "regulatory_feature_consequences")
        motif = _object_list(raw, "motif_feature_consequences")
        selected_transcript = raw.get("selected_transcript")
        if selected_transcript is not None and not isinstance(selected_transcript, dict):
            raise ValueError("VEP selected_transcript must be an object when present")
        transcript_selection = raw.get("transcript_selection")
        if transcript_selection is not None and not isinstance(transcript_selection, dict):
            raise ValueError("VEP transcript_selection must be an object when present")
        most_severe = raw.get("most_severe_consequence")
        if most_severe is not None and not isinstance(most_severe, str):
            raise ValueError("VEP most_severe_consequence must be a string when present")
        return {
            "genomic": {
                "genome": raw.get("genome"),
                "assembly_name": raw.get("assembly_name"),
                "chromosome": raw.get("chr"),
                "position": raw.get("pos"),
                "reference": raw.get("ref"),
                "alternate": raw.get("alt"),
                "variant_class": raw.get("variant_class"),
            },
            "gene": {"symbol": raw.get("gene_symbol"), "gene_id": raw.get("gene")},
            "transcript": raw.get("transcript"),
            "transcript_details": selected_transcript,
            "transcript_selection": transcript_selection,
            "effect": raw.get("effect"),
            "most_severe_consequence": most_severe,
            "transcript_consequences": transcript_consequences,
            # Retain the historical field while consumers migrate to the
            # explicit transcript_consequences name.
            "hgvs_consequences": transcript_consequences,
            "noncoding_consequences": {
                "intergenic": intergenic,
                "regulatory_features": regulatory,
                "motif_features": motif,
            },
            "colocated_variants": _object_list(raw, "colocated_variants"),
            "annotation_completeness": {
                "transcript_selection_status": (
                    transcript_selection.get("status")
                    if transcript_selection is not None
                    else "NOT_PROVIDED"
                ),
                "transcript_consequence_count": len(transcript_consequences),
                "intergenic_consequence_count": len(intergenic),
                "regulatory_feature_consequence_count": len(regulatory),
                "motif_feature_consequence_count": len(motif),
            },
            "hgvs": {"c": raw.get("hgvsc"), "p": raw.get("hgvsp")},
            "clinical": {},
            "population": {},
            "computational": {},
            "splice": {},
            "provenance": {
                "provider": "VEP",
                "provider_field_schema": "vep-json-variant-consequence-v2",
            },
        }
    raise ValueError(f"No annotation normalizer registered for provider {provider_id!r}")
