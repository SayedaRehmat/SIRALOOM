"""Explainable, non-clinical phenotype context ordering.

This module deliberately emits no similarity score, disease diagnosis, inheritance
compatibility conclusion, ACMG criterion, or clinical classification. Candidate
ordering is an inspectable evidence-navigation aid and remains unqualified until
an independently reviewed known-answer cohort and laboratory policy approve it.
"""
from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable


class PhenotypePrioritizationError(ValueError):
    """Input evidence is malformed or lacks the provenance needed for review."""


def _materialize(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    raise PhenotypePrioritizationError("Phenotype and disease assertions must be structured records")


def _required_text(record: dict[str, Any], field: str, label: str) -> str:
    value = str(record.get(field) or "").strip()
    if not value:
        raise PhenotypePrioritizationError(f"{label} is missing {field}")
    return value


def _term_matches(patient_term: str, disease_term: str, ontology: Any) -> tuple[bool, str]:
    if patient_term == disease_term:
        return True, "EXACT"
    if ontology is None:
        return False, "NO_ONTOLOGY"
    ancestors = ontology.ancestors(patient_term)
    if disease_term in ancestors:
        return True, "PATIENT_TERM_IS_DESCENDANT_OF_DISEASE_TERM"
    return False, "NO_MATCH"


def prioritize_disease_context(
    *,
    patient_observations: Iterable[Any],
    gene_disease_records: Iterable[dict[str, Any]],
    annotations_by_disease: dict[str, Iterable[Any]],
    hpoa_provenance: dict[str, Any],
    hpo_ontology: Any,
    proband_member_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Order gene–disease candidates by transparent HPOA assertion coverage.

    Only PRESENT proband observations participate in matching. ABSENT, EXCLUDED,
    UNKNOWN and NOT_ASSESSED are retained as non-matching context states; they are
    never converted into negative disease evidence. HPOA NOT assertions are
    surfaced as potential discordances, not treated as proof against a disease.
    HPOA frequency/onset/sex/modifier/evidence fields remain source assertions
    and are not numerically interpreted.
    """
    if not isinstance(annotations_by_disease, dict):
        raise PhenotypePrioritizationError("annotations_by_disease must be a disease-keyed object")
    if not isinstance(hpoa_provenance, dict):
        raise PhenotypePrioritizationError("hpoa_provenance must be an object")
    hpoa_resource_id = _required_text(hpoa_provenance, "resource_id", "HPOA provenance")
    hpoa_release = _required_text(hpoa_provenance, "resource_version", "HPOA provenance")
    hpoa_sha256 = _required_text(hpoa_provenance, "resource_sha256", "HPOA provenance").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", hpoa_sha256):
        raise PhenotypePrioritizationError("HPOA provenance resource_sha256 must be SHA-256")
    if hpo_ontology is None:
        raise PhenotypePrioritizationError("A governed HPO ontology release is required")
    ontology_release = _required_text({"release": getattr(hpo_ontology, "release", None)}, "release", "HPO ontology")
    ontology_sha256 = _required_text({"sha256": getattr(hpo_ontology, "sha256", None)}, "sha256", "HPO ontology").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", ontology_sha256):
        raise PhenotypePrioritizationError("HPO ontology sha256 must be SHA-256")
    annotation_index = {str(key).strip().casefold(): list(value) for key, value in annotations_by_disease.items()}

    observed: dict[str, dict[str, Any]] = {}
    non_matching_states: list[dict[str, Any]] = []
    allowed_proband_ids = {str(value) for value in proband_member_ids if str(value).strip()}
    for raw in patient_observations:
        item = _materialize(raw)
        subject = item.get("subject_member_id")
        if subject not in (None, "") and str(subject) not in allowed_proband_ids:
            continue
        status = str(item.get("phenotype_status") or "").strip().upper()
        submitted = str(item.get("canonical_hpo_id") or item.get("hpo_id") or "").strip().upper()
        if status == "PRESENT" and submitted:
            observed.setdefault(submitted, {"hpo_id": submitted, "observation_ids": [], "status": status})
            observation_id = str(item.get("id") or "")
            if observation_id and observation_id not in observed[submitted]["observation_ids"]:
                observed[submitted]["observation_ids"].append(observation_id)
        else:
            non_matching_states.append({
                "hpo_id": str(item.get("canonical_hpo_id") or item.get("hpo_id") or ""),
                "status": status or "UNSPECIFIED",
                "observation_id": str(item.get("id") or ""),
                "subject_member_id": str(subject) if subject not in (None, "") else None,
                "reason": "STATE_NOT_USED_AS_POSITIVE_MATCH_EVIDENCE",
            })

    associations: dict[str, list[dict[str, Any]]] = {}
    for raw in gene_disease_records:
        if not isinstance(raw, dict):
            raise PhenotypePrioritizationError("Gene–disease associations must be objects")
        association = dict(raw)
        gene = _required_text(association, "gene", "Gene–disease association").upper()
        disease_id = _required_text(association, "disease_id", "Gene–disease association")
        resource_id = _required_text(association, "resource_id", "Gene–disease association")
        resource_version = _required_text(association, "resource_version", "Gene–disease association")
        association_sha256 = _required_text(association, "resource_sha256", "Gene–disease association").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", association_sha256):
            raise PhenotypePrioritizationError("Gene–disease association resource_sha256 must be SHA-256")
        source_record_id = _required_text(association, "source_record_id", "Gene–disease association")
        modes = association.get("inheritance_modes")
        if not isinstance(modes, list) or not modes or any(not str(mode).strip() for mode in modes):
            raise PhenotypePrioritizationError(
                f"Gene–disease association {gene}/{disease_id} requires explicit inheritance_modes"
            )
        penetrance = association.get("penetrance")
        if not isinstance(penetrance, dict) or not str(penetrance.get("status") or "").strip():
            raise PhenotypePrioritizationError(
                f"Gene–disease association {gene}/{disease_id} requires an explicit penetrance status"
            )
        association["_normalized_gene"] = gene
        association["_normalized_disease_id"] = disease_id
        association["_provenance"] = {
            "resource_id": resource_id,
            "resource_name": association.get("resource_name"),
            "resource_version": resource_version,
            "source_record_id": source_record_id,
            "resource_sha256": association_sha256,
        }
        associations.setdefault(disease_id.casefold(), []).append(association)

    candidates: list[dict[str, Any]] = []
    for disease_key in sorted(associations):
        disease_associations = associations[disease_key]
        source_rows = annotation_index.get(disease_key, [])
        if not source_rows:
            # Disease IDs are exact identifiers. Do not guess crosswalks or aliases.
            continue
        assertions = [_materialize(row) for row in source_rows]
        disease_id = disease_associations[0]["_normalized_disease_id"]
        matched: list[dict[str, Any]] = []
        not_asserted: list[dict[str, Any]] = []
        for assertion in assertions:
            if str(assertion.get("aspect") or "").upper() != "P":
                continue
            disease_term = str(assertion.get("hpo_id") or "").strip().upper()
            if not disease_term:
                continue
            for patient_term in sorted(observed):
                is_match, match_type = _term_matches(patient_term, disease_term, hpo_ontology)
                if not is_match:
                    continue
                record = {
                    "patient_hpo_id": patient_term,
                    "patient_observation_ids": sorted(observed[patient_term]["observation_ids"]),
                    "disease_hpo_id": disease_term,
                    "match_type": match_type,
                    "hpoa_qualifier": str(assertion.get("qualifier") or "").upper(),
                    "hpoa_frequency": assertion.get("frequency"),
                    "hpoa_onset": assertion.get("onset"),
                    "hpoa_sex": assertion.get("sex"),
                    "hpoa_evidence": assertion.get("evidence"),
                    "hpoa_reference": assertion.get("reference"),
                    "hpoa_biocuration": assertion.get("biocuration"),
                }
                if record["hpoa_qualifier"] == "NOT":
                    not_asserted.append(record)
                else:
                    matched.append(record)
        matched_patient_terms = sorted({item["patient_hpo_id"] for item in matched})
        for association in disease_associations:
            candidates.append({
                "gene": association["_normalized_gene"],
                "disease_id": disease_id,
                "disease_name": association.get("disease_name"),
                "association_validity": association.get("validity_status") or "NOT_RECORDED",
                "association_validity_provenance": association.get("validity_provenance"),
                "clingen_validity_assertions": association.get("clingen_validity_assertions") or [],
                "g2p_confidence": association.get("g2p_confidence"),
                "g2p_allelic_requirement": association.get("g2p_allelic_requirement"),
                "molecular_mechanism": association.get("molecular_mechanism"),
                "inheritance": {
                    "modes": sorted({str(mode).strip().upper() for mode in association["inheritance_modes"]}),
                    "mode_sources": association.get("inheritance_mode_sources") or {},
                    "mode_conflict": bool(association.get("inheritance_mode_conflict")),
                    "penetrance": dict(association["penetrance"]),
                    "penetrance_provenance": {
                        "status": "NOT_RECORDED",
                        "source": "NOT_PROVIDED_BY_G2P_OR_CLINGEN_GDV",
                        "g2p_resource_id": resource_id,
                        "clingen_resource_id": (
                            association.get("validity_provenance", {}).get("resource_id")
                            if isinstance(association.get("validity_provenance"), dict)
                            else None
                        ),
                    },
                    "qualification_status": (
                        "REQUIRES_REVIEW_FOR_SOURCE_CONFLICT"
                        if association.get("inheritance_mode_conflict")
                        else "REQUIRES_INDEPENDENT_QUALIFICATION"
                    ),
                },
                "matched_patient_term_count": len(matched_patient_terms),
                "matched_terms": matched,
                "potential_discordances": not_asserted,
                "unmatched_present_patient_terms": sorted(set(observed) - set(matched_patient_terms)),
                "association_provenance": association["_provenance"],
                "hpoa_provenance": {
                    "resource_id": hpoa_resource_id,
                    "resource_release": hpoa_release,
                    "resource_sha256": hpoa_sha256,
                    "ontology_release": ontology_release,
                    "ontology_sha256": ontology_sha256,
                },
                "interpretive_use": "CONTEXTUAL_CANDIDATE_ORDERING_ONLY",
                "clinical_prioritization_validated": False,
                "human_review_required": True,
            })

    # This is deterministic navigation ordering, not a calibrated score. Ties
    # are stable and fully explained by the matched term list above.
    candidates.sort(key=lambda row: (
        -row["matched_patient_term_count"], row["gene"], row["disease_id"],
        row["association_provenance"]["source_record_id"],
    ))
    for index, candidate in enumerate(candidates, start=1):
        candidate["contextual_order"] = index

    return {
        "schema_version": 1,
        "method": "HPOA_EXACT_AND_IS_A_CONTEXT_ORDER_V1",
        "status": "CONTEXTUAL_UNQUALIFIED" if candidates else "NO_QUALIFIED_CANDIDATES",
        "observed_proband_present_terms": sorted(observed),
        "non_matching_phenotype_states": non_matching_states,
        "candidates": candidates,
        "limitations": [
            "Contextual order is not a calibrated similarity score or diagnostic probability.",
            "HPOA frequency, onset, sex and evidence fields are preserved but not interpreted numerically.",
            "HPOA NOT assertions are potential discordances requiring human review.",
            "Family-member phenotypes are not merged into the proband phenotype vector.",
            "Disease-specific inheritance compatibility is not calculated by this method.",
            "Independent known-answer qualification and laboratory approval are required before clinical prioritization use.",
        ],
        "clinical_prioritization_validated": False,
        "human_review_required": True,
    }
