from __future__ import annotations
from typing import Any


def normalize_gene_be_variant(raw: dict[str, Any]) -> dict[str, Any]:
    """Map current GeneBe variant API fields to a SIRALOOM-neutral representation.

    GeneBe documents frequency_reference_population as a current gnomAD total
    (exome + genome) population frequency. It is stored as provider-derived global
    population evidence; it is not labeled as Middle Eastern/country-specific.
    """
    consequences = raw.get("consequences") or []
    return {
        "genomic": {
            "genome": raw.get("genome"),
            "chromosome": raw.get("chr"),
            "position": raw.get("pos"),
            "reference": raw.get("ref"),
            "alternate": raw.get("alt"),
        },
        "gene": {"symbol": raw.get("gene_symbol"), "hgnc_id": raw.get("gene_hgnc_id")},
        "transcript": raw.get("transcript"),
        "effect": raw.get("effect"),
        "dbsnp": raw.get("dbsnp"),
        "hgvs_consequences": consequences,
        "population": {
            "reference_population_af": raw.get("frequency_reference_population"),
            "reference_population_ac": raw.get("allele_count_reference_population"),
            "reference_population_hom": raw.get("hom_count_reference_population"),
            "gnomad_exomes_af": raw.get("gnomad_exomes_af"),
            "gnomad_genomes_af": raw.get("gnomad_genomes_af"),
            "gnomad_exomes_ac": raw.get("gnomad_exomes_ac"),
            "gnomad_genomes_ac": raw.get("gnomad_genomes_ac"),
            "gnomad_exomes_homalt": raw.get("gnomad_exomes_homalt"),
            "gnomad_genomes_homalt": raw.get("gnomad_genomes_homalt"),
        },
        "computational": {
            "selected_score": raw.get("computational_score_selected"),
            "selected_prediction": raw.get("computational_prediction_selected"),
            "selected_source": raw.get("computational_source_selected"),
            "revel": raw.get("revel_score"),
            "revel_prediction": raw.get("revel_prediction"),
            "alphamissense": raw.get("alphamissense_score"),
            "alphamissense_prediction": raw.get("alphamissense_prediction"),
            "bayesdelnoaf": raw.get("bayesdelnoaf_score"),
            "bayesdelnoaf_prediction": raw.get("bayesdelnoaf_prediction"),
            "phylop100way": raw.get("phylop100way_score"),
            "phylop100way_prediction": raw.get("phylop100way_prediction"),
            "dbscsnv_ada_score": raw.get("dbscsnv_ada_score"),
            "dbscsnv_ada_prediction": raw.get("dbscsnv_ada_prediction"),
        },
        "splice": {
            "selected_score": raw.get("splice_score_selected"),
            "selected_prediction": raw.get("splice_prediction_selected"),
            "selected_source": raw.get("splice_source_selected"),
            "spliceai_max_score": raw.get("spliceai_max_score"),
            "spliceai_max_prediction": raw.get("spliceai_max_prediction"),
        },
        "clinical": {
            "clinvar_disease": raw.get("clinvar_disease"),
            "clinvar_classification": raw.get("clinvar_classification"),
            "clinvar_review_status": raw.get("clinvar_review_status"),
            "clinvar_submissions_summary": raw.get("clinvar_submissions_summary"),
        },
        "provider_acmg": {
            "score": raw.get("acmg_score"),
            "classification": raw.get("acmg_classification"),
            "criteria": raw.get("acmg_criteria"),
            "by_gene": raw.get("acmg_by_gene", []),
        },
        "provenance": {
            "provider": "GeneBe",
            "provider_field_schema": "current-api-response-fields",
        },
    }
