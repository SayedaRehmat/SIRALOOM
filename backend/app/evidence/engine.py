from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID, uuid4

from backend.app.domain.evidence import EvidenceRecord
from backend.app.domain.population import qualified_allele_frequency


class EvidenceEngineError(ValueError):
    """Raised when an annotation/population record is insufficiently structured for evidence extraction."""


EVIDENCE_TYPES = {
    "POPULATION",
    "CLINICAL_DATABASE",
    "COMPUTATIONAL",
    "SPLICING",
    "CONSEQUENCE",
    "PROVIDER_ASSERTION",
    "PHENOTYPE",
    "GENE_DISEASE",
    "LITERATURE",
}

DIRECTIONS = {"SUPPORTS", "REFUTES", "NEUTRAL", "UNKNOWN"}


@dataclass(frozen=True)
class EvidenceContext:
    analysis_id: UUID
    population_resource_versions: dict[str, str] | None = None


class EvidenceEngine:
    """Convert provider observations into traceable evidence records.

    This engine intentionally does NOT perform final ACMG classification. It creates
    auditable evidence assertions and preserves source observations so that a future
    criterion-specific ACMG/ClinGen engine can make a separately versioned decision.
    """

    engine_id = "siraloom-evidence"
    engine_version = "0.1.0"

    def build_from_annotation(
        self,
        *,
        variant_id: UUID,
        annotation: dict[str, Any],
        provider_name: str,
        provider_version: str | None,
        resource_name: str | None,
        resource_version: str | None,
        context: EvidenceContext,
        population_observations: Iterable[dict[str, Any]] = (),
    ) -> list[EvidenceRecord]:
        if not isinstance(annotation, dict):
            raise EvidenceEngineError("Annotation must be an object")

        evidence: list[EvidenceRecord] = []
        evidence.extend(
            self._population(
                variant_id=variant_id,
                annotation=annotation,
                provider_name=provider_name,
                provider_version=provider_version,
                resource_name=resource_name,
                resource_version=resource_version,
                population_observations=population_observations,
            )
        )
        evidence.extend(
            self._clinical(
                variant_id=variant_id,
                annotation=annotation,
                provider_name=provider_name,
                provider_version=provider_version,
                resource_name=resource_name,
                resource_version=resource_version,
            )
        )
        evidence.extend(
            self._computational(
                variant_id=variant_id,
                annotation=annotation,
                provider_name=provider_name,
                provider_version=provider_version,
            )
        )
        evidence.extend(
            self._splicing(
                variant_id=variant_id,
                annotation=annotation,
                provider_name=provider_name,
                provider_version=provider_version,
            )
        )
        evidence.extend(
            self._consequence(
                variant_id=variant_id,
                annotation=annotation,
                provider_name=provider_name,
                provider_version=provider_version,
                resource_name=resource_name,
                resource_version=resource_version,
            )
        )
        evidence.extend(
            self._provider_assertion(
                variant_id=variant_id,
                annotation=annotation,
                provider_name=provider_name,
                provider_version=provider_version,
            )
        )
        return evidence

    def build_from_clinvar_assertions(
        self,
        *,
        variant_id: UUID,
        assertions: Iterable[Any],
        resource_id: UUID,
        resource_name: str,
        resource_version: str,
        request_fingerprint: str,
        execution_metadata: dict[str, Any],
    ) -> list[EvidenceRecord]:
        """Convert directly queried, release-pinned ClinVar assertions into evidence.

        The returned records retain SCV/VCV/RCV identities and the exact resource
        execution context. They are evidence inputs only; they are never final
        classifications.
        """
        out: list[EvidenceRecord] = []
        for assertion in assertions:
            classification = _normalize_text(getattr(assertion, "classification", None))
            low = (classification or "").lower()
            if "pathogenic" in low and "likely pathogenic" not in low:
                direction = "SUPPORTS"
            elif "likely pathogenic" in low:
                direction = "SUPPORTS"
            elif "benign" in low:
                direction = "REFUTES"
            else:
                direction = "NEUTRAL"
            accession = str(getattr(assertion, "accession", "") or "")
            version = _normalize_text(getattr(assertion, "version", None))
            record_type = str(getattr(assertion, "record_type", "") or "")
            source_record_id = f"{record_type}:{accession}.{version}" if version else f"{record_type}:{accession}"
            payload = {
                "record_type": record_type,
                "accession": accession,
                "accession_version": version,
                "variation_id": getattr(assertion, "variation_id", None),
                "vcv": (getattr(assertion, "payload", {}) or {}).get("vcv"),
                "rcv_accessions": list(getattr(assertion, "rcv_accessions", ()) or ()),
                "genome_build": getattr(assertion, "genome_build", None),
                "chromosome": getattr(assertion, "chromosome", None),
                "position": getattr(assertion, "position", None),
                "reference": getattr(assertion, "reference", None),
                "alternate": getattr(assertion, "alternate", None),
                "classification": classification,
                "review_status": getattr(assertion, "review_status", None),
                "condition": getattr(assertion, "condition", None),
                "submitter": getattr(assertion, "submitter", None),
                "assertion_method": getattr(assertion, "assertion_method", None),
                "record_sha256": getattr(assertion, "record_sha256", None),
                "release_provenance": execution_metadata,
                "interpretive_use": "DIRECT_CLINVAR_RELEASE_EVIDENCE_REQUIRES_REVIEW",
            }
            out.append(
                self._record(
                    variant_id=variant_id,
                    evidence_type="CLINICAL_DATABASE",
                    statement=(
                        f"Direct ClinVar {record_type or 'record'} {source_record_id} was retrieved "
                        "from the governed release and preserved as clinical database evidence."
                    ),
                    direction=direction,
                    source_name=resource_name,
                    source_version=resource_version,
                    payload=payload,
                )
            )
            record = out[-1]
            out[-1] = EvidenceRecord(
                **{
                    **record.__dict__,
                    "resource_id": resource_id,
                    "source_record_id": source_record_id,
                    "request_fingerprint": request_fingerprint,
                    "response_sha256": getattr(assertion, "record_sha256", None),
                    "request_metadata": execution_metadata,
                }
            )
        return out

    def build_from_clingen_variant_assertions(
        self,
        *,
        variant_id: UUID,
        assertions: Iterable[Any],
        resource_id: UUID,
        resource_name: str,
        resource_version: str,
        request_fingerprint: str,
        execution_metadata: dict[str, Any],
    ) -> list[EvidenceRecord]:
        out: list[EvidenceRecord] = []
        for assertion in assertions:
            classification = _normalize_text(getattr(assertion, "classification", None))
            low = (classification or "").lower()
            if "conflict" in low or "uncertain" in low:
                direction = "NEUTRAL"
            elif "pathogenic" in low:
                direction = "SUPPORTS"
            elif "benign" in low:
                direction = "REFUTES"
            else:
                direction = "NEUTRAL"
            source_record_id = str(getattr(assertion, "source_record_id", "") or "")
            payload = {
                "classification": classification,
                "condition": getattr(assertion, "condition", None),
                "inheritance": getattr(assertion, "inheritance", None),
                "gene": getattr(assertion, "gene", None),
                "hgvs": list(getattr(assertion, "hgvs", ()) or ()),
                "caid": getattr(assertion, "caid", None),
                "clinvar_id": getattr(assertion, "clinvar_id", None),
                "expert_panel": getattr(assertion, "expert_panel", None),
                "met_codes": list(getattr(assertion, "met_codes", ()) or ()),
                "unmet_codes": list(getattr(assertion, "unmet_codes", ()) or ()),
                "criterion_assertions": [
                    {
                        "code": getattr(item, "code", None),
                        "status": getattr(item, "status", None),
                        "source": getattr(item, "source", None),
                        "rationale": getattr(item, "rationale", None),
                        "pmids": list(getattr(item, "pmids", ()) or ()),
                        "strength": getattr(item, "strength", None),
                    }
                    for item in (getattr(assertion, "criterion_assertions", ()) or ())
                ],
                "criterion_detail_available": bool(
                    (getattr(assertion, "payload", {}) or {}).get("criterion_detail_available")
                ),
                "criterion_detail_note": (getattr(assertion, "payload", {}) or {}).get("criterion_detail_note"),
                "preferred_variant_title": (getattr(assertion, "payload", {}) or {}).get(
                    "preferred_variant_title"
                ),
                "mondo_id": (getattr(assertion, "payload", {}) or {}).get("mondo_id"),
                "version": getattr(assertion, "version", None),
                "published_date": getattr(assertion, "published_date", None),
                "record_sha256": getattr(assertion, "record_sha256", None),
                "interpretive_use": "CLINGEN_VCEP_ASSERTION_REQUIRES_DISEASE_AND_CRITERION_REVIEW",
                "release_provenance": execution_metadata,
            }
            record = self._record(
                variant_id=variant_id,
                evidence_type="CLINICAL_DATABASE",
                statement="ClinGen VCEP evidence repository contains an expert-curated variant-disease pathogenicity assertion; it is preserved as source evidence and is not a SIRALOOM final classification.",
                direction=direction,
                source_name=resource_name,
                source_version=resource_version,
                payload=payload,
            )
            out.append(EvidenceRecord(
                **{
                    **record.__dict__,
                    "resource_id": resource_id,
                    "source_record_id": source_record_id,
                    "request_fingerprint": request_fingerprint,
                    "response_sha256": getattr(assertion, "record_sha256", None),
                    "request_metadata": execution_metadata,
                }
            ))
        return out

    def build_from_clingen_gene_disease_assertions(
        self,
        *,
        variant_id: UUID,
        assertions: Iterable[Any],
        resource_id: UUID,
        resource_name: str,
        resource_version: str,
        request_fingerprint: str,
        execution_metadata: dict[str, Any],
    ) -> list[EvidenceRecord]:
        out: list[EvidenceRecord] = []
        for assertion in assertions:
            classification = _normalize_text(getattr(assertion, "classification", None))
            source_record_id = str(getattr(assertion, "source_record_id", "") or "")
            payload = {
                "gene": getattr(assertion, "gene", None),
                "hgnc_id": getattr(assertion, "hgnc_id", None),
                "disease": getattr(assertion, "disease", None),
                "mondo_id": getattr(assertion, "mondo_id", None),
                "moi": getattr(assertion, "moi", None),
                "sop": getattr(assertion, "sop", None),
                "classification": classification,
                "online_report": getattr(assertion, "online_report", None),
                "classification_date": getattr(assertion, "classification_date", None),
                "expert_panel": getattr(assertion, "expert_panel", None),
                "record_sha256": getattr(assertion, "record_sha256", None),
                "interpretive_use": "GENE_DISEASE_VALIDITY_CONTEXT_NOT_VARIANT_PATHOGENICITY",
                "release_provenance": execution_metadata,
            }
            record = self._record(
                variant_id=variant_id,
                evidence_type="GENE_DISEASE",
                statement="ClinGen Gene-Disease Validity provides a curated validity assessment for the annotated gene-disease pair; it is contextual evidence and does not classify the variant.",
                direction="NEUTRAL",
                source_name=resource_name,
                source_version=resource_version,
                payload=payload,
            )
            out.append(EvidenceRecord(
                **{
                    **record.__dict__,
                    "resource_id": resource_id,
                    "source_record_id": source_record_id,
                    "request_fingerprint": request_fingerprint,
                    "response_sha256": getattr(assertion, "record_sha256", None),
                    "request_metadata": execution_metadata,
                }
            ))
        return out

    def build_case_context_evidence(
        self, *, variant_id: UUID, case_hpo_terms: list[dict[str, Any]], gene: str | None,
        gene_disease_records: list[dict[str, Any]] = (), literature_records: list[dict[str, Any]] = (),
        hpo_ontology: Any | None = None,
        hpo_provenance: dict[str, Any] | None = None,
    ) -> list[EvidenceRecord]:
        """Create contextual evidence without turning phenotype/literature into pathogenicity."""
        out: list[EvidenceRecord] = []
        if case_hpo_terms:
            from backend.app.phenotype import normalize_terms
            terms = normalize_terms(case_hpo_terms)
            present = [t for t in terms if t.status == "PRESENT"]
            absent = [t for t in terms if t.status == "ABSENT"]
            excluded = [t for t in terms if t.status == "EXCLUDED"]
            uncertain = [t for t in terms if t.status == "UNKNOWN"]
            not_assessed = [t for t in terms if t.status == "NOT_ASSESSED"]
            resolution_payload = None
            unresolved_case_terms: list[dict[str, str]] = []
            if hpo_ontology is not None:
                resolution_payload = []
                for term in terms:
                    resolution = hpo_ontology.resolve(term.hpo_id)
                    resolution_payload.append({
                        "hpo_id": term.hpo_id,
                        "phenotype_status": term.status,
                        "status": resolution.status,
                        "canonical_id": resolution.canonical_id,
                        "replacement_candidates": list(resolution.replacement_candidates),
                        "consider": list(resolution.consider),
                        "ambiguous_candidates": list(resolution.ambiguous_candidates),
                    })
                    if resolution.status not in {"CURRENT", "ALTERNATE_ID", "OBSOLETE_REPLACED"}:
                        unresolved_case_terms.append({"hpo_id": term.hpo_id, "status": resolution.status})
            else:
                unresolved_case_terms = [
                    {"hpo_id": term.hpo_id, "status": "ONTOLOGY_UNAVAILABLE"}
                    for term in terms
                ]
            case_payload = {
                "gene": gene,
                "present_terms": [{"hpo_id": t.hpo_id, "label": t.label, "phenotype_status": t.status} for t in present],
                "negative_terms": [{"hpo_id": t.hpo_id, "label": t.label} for t in absent],
                "excluded_terms": [{"hpo_id": t.hpo_id, "label": t.label} for t in excluded],
                "uncertain_terms": [{"hpo_id": t.hpo_id, "label": t.label} for t in uncertain],
                "not_assessed_terms": [{"hpo_id": t.hpo_id, "label": t.label} for t in not_assessed],
                "interpretive_use": "CASE_RELEVANCE_AND_PRIORITIZATION",
                "ontology_release": getattr(hpo_ontology, "release", None),
                "ontology_term_resolutions": resolution_payload,
                "term_validation_status": (
                    "VALIDATED"
                    if hpo_ontology is not None and not unresolved_case_terms
                    else "REQUIRES_REVIEW"
                ),
                "term_validation_reason": (
                    "PINNED_HPO_ONTOLOGY_UNAVAILABLE"
                    if hpo_ontology is None
                    else "UNRESOLVED_TERMS"
                    if unresolved_case_terms
                    else None
                ),
                "unresolved_terms_require_review": unresolved_case_terms,
            }
            case_record = self._record(
                variant_id=variant_id, evidence_type="PHENOTYPE",
                statement="Structured HPO phenotype context is available for case-level relevance and prioritization; it is not pathogenicity evidence by itself.",
                direction="NEUTRAL",
                source_name="HPO" if hpo_provenance else "HPO_CASE_CONTEXT",
                source_version=(hpo_provenance or {}).get("resource_version"),
                payload=case_payload,
                resource_id=(
                    UUID(str(hpo_provenance["resource_id"]))
                    if hpo_provenance and hpo_provenance.get("resource_id")
                    else None
                ),
                request_fingerprint=(hpo_provenance or {}).get("request_fingerprint"),
                response_sha256=(hpo_provenance or {}).get("response_sha256"),
                request_metadata=dict(hpo_provenance or {}),
            )
            out.append(case_record)
        for item in gene_disease_records:
            if gene and item.get("gene") and str(item.get("gene")).upper() != gene.upper():
                continue
            disease = str(item.get("disease") or "").strip()
            if not disease: continue
            payload = dict(item)
            # A caller-provided hierarchy is not authoritative ontology data.
            payload.pop("hpo_ancestor_map", None)
            payload["gene"] = gene or item.get("gene")
            payload["interpretive_use"] = "GENE_DISEASE_RELEVANCE_REVIEW"
            target_hpo = item.get("hpo_terms") or item.get("associated_hpo_terms") or []
            if target_hpo and case_hpo_terms:
                from backend.app.phenotype import match_hpo
                case_unresolved = bool(unresolved_case_terms) if hpo_ontology is not None else False
                target_ids = [
                    str(term.get("hpo_id") or term.get("id") or "") if isinstance(term, dict) else str(term)
                    for term in target_hpo
                ]
                target_resolutions = [hpo_ontology.resolve(term) for term in target_ids] if hpo_ontology is not None else []
                unresolved_targets = [
                    {"hpo_id": term, "status": result.status}
                    for term, result in zip(target_ids, target_resolutions)
                    if result.status not in {"CURRENT", "ALTERNATE_ID", "OBSOLETE_REPLACED"}
                ]
                present_ids = [term.hpo_id for term in present]
                absent_ids = [term.hpo_id for term in [*absent, *excluded]]
                if hpo_ontology is not None:
                    present_ids = [
                        hpo_ontology.resolve(term).canonical_id or term
                        for term in present_ids
                    ]
                    absent_ids = [
                        hpo_ontology.resolve(term).canonical_id or term
                        for term in absent_ids
                    ]
                contradictory_patient_terms = sorted(set(present_ids) & set(absent_ids))
                if contradictory_patient_terms:
                    payload["phenotype_match"] = {
                        "status": "REQUIRES_REVIEW",
                        "reason": "The patient phenotype record marks the same HPO term both present and absent.",
                        "contradictory_patient_terms": contradictory_patient_terms,
                        "ontology_release": getattr(hpo_ontology, "release", None),
                        "ontology_provenance": dict(hpo_provenance or {}),
                    }
                elif not present:
                    payload["phenotype_match"] = {
                        "status": "REQUIRES_REVIEW",
                        "reason": "No positive patient HPO terms are available for similarity calculation.",
                        "negative_patient_terms": [term.hpo_id for term in absent],
                        "excluded_patient_terms": [term.hpo_id for term in excluded],
                        "uncertain_patient_terms": [term.hpo_id for term in uncertain],
                        "not_assessed_patient_terms": [term.hpo_id for term in not_assessed],
                        "ontology_release": getattr(hpo_ontology, "release", None),
                        "ontology_provenance": dict(hpo_provenance or {}),
                    }
                elif hpo_ontology is not None and (case_unresolved or unresolved_targets):
                    payload["phenotype_match"] = {
                        "status": "REQUIRES_REVIEW",
                        "reason": "One or more patient or disease HPO terms do not resolve in the pinned ontology release.",
                        "unresolved_patient_terms": unresolved_case_terms,
                        "unresolved_disease_terms": unresolved_targets,
                        "ontology_release": hpo_ontology.release,
                        "ontology_provenance": dict(hpo_provenance or {}),
                    }
                else:
                    if hpo_ontology is not None:
                        canonical_case_terms = []
                        for term in case_hpo_terms:
                            value = term.get("hpo_id") or term.get("id") if isinstance(term, dict) else term
                            resolution = hpo_ontology.resolve(str(value))
                            canonical_case_terms.append(
                                {
                                    **term,
                                    "hpo_id": resolution.canonical_id,
                                    "original_hpo_id": str(value),
                                    "normalization_status": resolution.status,
                                }
                                if isinstance(term, dict)
                                else resolution.canonical_id
                            )
                        canonical_target_terms = [result.canonical_id for result in target_resolutions]
                        canonical_case_ids = {
                            str(term.get("hpo_id") or term.get("id") or "")
                            if isinstance(term, dict)
                            else str(term)
                            for term in canonical_case_terms
                        }
                        ancestor_map = {
                            term: sorted(hpo_ontology.ancestors(term))
                            for term in canonical_case_ids
                            if term
                        }
                    else:
                        canonical_case_terms = case_hpo_terms
                        canonical_target_terms = target_hpo
                        ancestor_map = None
                    match = match_hpo(canonical_case_terms, canonical_target_terms, ancestor_map=ancestor_map)
                    match_payload = {
                        "matched_terms": list(match.matched),
                        "query_count": match.query_count,
                        "target_count": match.target_count,
                        "ontology_release": getattr(hpo_ontology, "release", None),
                        "ontology_provenance": dict(hpo_provenance or {}),
                    }
                    if hpo_ontology is not None:
                        match_payload.update({
                            "status": "SCORED",
                            "score": match.score,
                            "score_semantics": "fraction_of_present_patient_terms_equal_to_or_more_specific_than_a_disease_phenotype_term",
                            "clinical_prioritization_validated": False,
                            "method": match.method,
                        })
                    else:
                        # Exact string overlap is useful for triage but cannot
                        # validate term status or ontology semantics. Keep it
                        # explicitly non-scientific and out of ranking fields.
                        match_payload.update({
                            "status": "REQUIRES_REVIEW",
                            "reason": "No pinned HPO ontology was available to validate terms or compute ontology-aware similarity.",
                            "exact_overlap_score": match.score,
                            "method": "EXACT_HPO_OVERLAP_UNVALIDATED",
                        })
                    payload["phenotype_match"] = match_payload
            out.append(self._record(
                variant_id=variant_id, evidence_type="GENE_DISEASE",
                statement="A structured gene-disease association is recorded as contextual evidence; validity and strength require source-specific review.",
                direction="NEUTRAL", source_name=item.get("source_name") or "CURATED_GENE_DISEASE", source_version=item.get("source_version"),
                payload=payload,
            ))
        for item in literature_records:
            if gene and item.get("gene") and str(item.get("gene")).upper() != gene.upper():
                continue
            title = str(item.get("title") or "").strip(); summary = str(item.get("evidence_summary") or item.get("summary") or "").strip()
            if not title or not summary: continue
            direction = str(item.get("direction") or "NEUTRAL").upper()
            if direction not in DIRECTIONS: direction = "NEUTRAL"
            out.append(self._record(
                variant_id=variant_id, evidence_type="LITERATURE",
                statement=summary, direction=direction, source_name=item.get("source_name") or "LITERATURE", source_version=item.get("source_version"),
                payload={**dict(item), "interpretive_use":"LITERATURE_EVIDENCE_REVIEW"},
            ))
        return out

    def build_hpoa_disease_phenotype_evidence(
        self,
        *,
        variant_id: UUID,
        gene: str | None,
        gene_disease_records: Iterable[dict[str, Any]],
        annotations_by_disease: dict[str, Iterable[Any]],
        provenance: dict[str, Any],
        patient_hpo_terms: Iterable[Any] = (),
        hpo_ontology: Any | None = None,
    ) -> list[EvidenceRecord]:
        """Persist source assertions without turning frequency into a score.

        HPOA's NOT qualifiers and frequency fields are preserved verbatim. This
        record is contextual evidence for human review and is not an ACMG
        criterion or a calibrated phenotype-prioritization result.
        """
        from dataclasses import asdict, is_dataclass

        out: list[EvidenceRecord] = []
        patient_hpo_material = list(patient_hpo_terms)
        eligible_disease_ids = {
            str(item.get("disease_id") or item.get("disease_identifier") or "").strip()
            for item in gene_disease_records
            if isinstance(item, dict)
            and str(item.get("disease_id") or item.get("disease_identifier") or "").strip()
            and (
                not gene
                or not item.get("gene")
                or str(item["gene"]).upper() == gene.upper()
            )
        }
        for disease_id, disease_assertions in sorted(annotations_by_disease.items()):
            if disease_id not in eligible_disease_ids:
                continue
            material = [
                asdict(annotation) if is_dataclass(annotation) else dict(annotation)
                for annotation in disease_assertions
            ]
            if not material:
                continue
            patient_comparison = self._compare_hpoa_patient_context(
                patient_hpo_terms=patient_hpo_material,
                assertions=material,
                ontology=hpo_ontology,
            )
            out.append(
                self._record(
                    variant_id=variant_id,
                    evidence_type="PHENOTYPE",
                    statement=(
                        "Versioned HPO disease-phenotype assertions are available for review; "
                        "they are not independently validated diagnostic or classification evidence."
                    ),
                    direction="NEUTRAL",
                    source_name="HPOA",
                    source_version=str(provenance.get("resource_version") or ""),
                    payload={
                        "disease_id": disease_id,
                        "gene": gene,
                        "assertions": material,
                        "interpretive_use": "DISEASE_PHENOTYPE_EVIDENCE_REVIEW",
                        "score": None,
                        "clinical_prioritization_validated": False,
                        "patient_comparison": patient_comparison,
                    },
                    resource_id=(
                        UUID(str(provenance["resource_id"]))
                        if provenance.get("resource_id")
                        else None
                    ),
                    request_fingerprint=provenance.get("request_fingerprint"),
                    response_sha256=provenance.get("response_sha256"),
                    request_metadata=dict(provenance),
                )
            )
        return out


    @staticmethod
    def _compare_hpoa_patient_context(
        *, patient_hpo_terms: Iterable[Any], assertions: list[dict[str, Any]], ontology: Any | None
    ) -> dict[str, Any]:
        """Expose limited HPOA/patient discrepancies for review, never as a score.

        Only Phenotypic Abnormality (aspect P) is compared. HPO ``is_a`` ancestry is
        used solely to surface exact/descendant relationships. A source ``NOT``
        assertion, a coded 0% frequency, a textual 0%, and a finite-cohort 0/N
        observation remain distinct in the returned evidence. None changes ACMG
        criteria or ranking.
        """
        from backend.app.phenotype import normalize_terms

        result: dict[str, Any] = {
            "method": "HPOA_ASSERTION_COMPARISON_V1",
            "ontology_release": getattr(ontology, "release", None),
            "ontology_sha256": getattr(ontology, "sha256", None),
            "comparison_scope": "HPOA aspect P; exact or HPO is_a descendant relations only",
            "potential_discordances": [],
            "contradictory_patient_terms": [],
            "unresolved_patient_terms": [],
            "unresolved_assertion_terms": [],
            "non_phenotypic_assertions_skipped": 0,
            "patient_status_counts": {},
            "score": None,
            "clinical_prioritization_validated": False,
            "classification_criterion": None,
            "interpretive_use": "HUMAN_REVIEW_CONTEXT_ONLY",
        }
        if ontology is None:
            result.update({
                "status": "REQUIRES_REVIEW",
                "reason": "PINNED_HPO_ONTOLOGY_UNAVAILABLE",
                "review_required": True,
            })
            return result

        normalized = normalize_terms(patient_hpo_terms)
        patient_terms: list[tuple[str, str]] = []
        patient_status_counts: dict[str, int] = {}
        resolved_statuses: dict[str, set[str]] = {}
        for term in normalized:
            patient_status_counts[term.status] = patient_status_counts.get(term.status, 0) + 1
            resolution = ontology.resolve(term.hpo_id)
            if resolution.status not in {"CURRENT", "ALTERNATE_ID", "OBSOLETE_REPLACED"} or not resolution.canonical_id:
                result["unresolved_patient_terms"].append({
                    "hpo_id": term.hpo_id,
                    "status": resolution.status,
                    "phenotype_status": term.status,
                })
                continue
            if term.status in {"PRESENT", "ABSENT", "EXCLUDED"}:
                patient_terms.append((resolution.canonical_id, term.status))
                resolved_statuses.setdefault(resolution.canonical_id, set()).add(term.status)

        result["patient_status_counts"] = patient_status_counts
        result["contradictory_patient_terms"] = [
            {
                "hpo_id": hpo_id,
                "statuses": sorted(statuses),
            }
            for hpo_id, statuses in sorted(resolved_statuses.items())
            if "PRESENT" in statuses and statuses & {"ABSENT", "EXCLUDED"}
        ]

        if not patient_terms:
            result.update({
                "status": "REQUIRES_REVIEW",
                "reason": "No resolved PRESENT, ABSENT, or EXCLUDED patient terms are available.",
                "review_required": True,
            })
            return result

        for assertion in assertions:
            if str(assertion.get("aspect") or "").strip().upper() != "P":
                result["non_phenotypic_assertions_skipped"] += 1
                continue
            source_hpo_id = str(assertion.get("hpo_id") or "").strip().upper()
            resolution = ontology.resolve(source_hpo_id)
            if resolution.status not in {"CURRENT", "ALTERNATE_ID", "OBSOLETE_REPLACED"} or not resolution.canonical_id:
                result["unresolved_assertion_terms"].append({
                    "hpo_id": source_hpo_id,
                    "status": resolution.status,
                    "reference": assertion.get("reference"),
                })
                continue
            assertion_hpo_id = resolution.canonical_id
            qualifier = str(assertion.get("qualifier") or "").strip().upper()
            frequency = str(assertion.get("frequency") or "").strip()
            frequency_upper = frequency.upper()
            if frequency_upper == "HP:0040285":
                frequency_semantic = "HPO_FREQUENCY_EXCLUDED_0_PERCENT"
            elif frequency == "0%":
                frequency_semantic = "ZERO_PERCENT_FREQUENCY"
            elif re.fullmatch(r"0/[1-9][0-9]*", frequency):
                frequency_semantic = "ZERO_OF_N_COHORT_OBSERVATION"
            else:
                frequency_semantic = None
            frequency_zero = frequency_semantic is not None
            negative_semantics = []
            if qualifier == "NOT":
                negative_semantics.append("SOURCE_NOT")
            if frequency_semantic:
                negative_semantics.append(frequency_semantic)

            for patient_hpo_id, patient_status in patient_terms:
                if patient_status == "PRESENT" and negative_semantics:
                    is_descendant = (
                        patient_hpo_id == assertion_hpo_id
                        or assertion_hpo_id in ontology.ancestors(patient_hpo_id)
                    )
                    if is_descendant:
                        result["potential_discordances"].append({
                            "type": (
                                "PATIENT_PRESENT_VS_SOURCE_NOT_AND_FREQUENCY_CONTEXT"
                                if qualifier == "NOT" and frequency_zero
                                else "PATIENT_PRESENT_VS_SOURCE_NOT_ASSERTION"
                                if qualifier == "NOT"
                                else {
                                    "HPO_FREQUENCY_EXCLUDED_0_PERCENT": "PATIENT_PRESENT_VS_HPO_EXCLUDED_FREQUENCY",
                                    "ZERO_PERCENT_FREQUENCY": "PATIENT_PRESENT_VS_ZERO_PERCENT_FREQUENCY",
                                    "ZERO_OF_N_COHORT_OBSERVATION": "PATIENT_PRESENT_VS_ZERO_OF_N_FREQUENCY",
                                }[frequency_semantic]
                            ),
                            "source_negative_semantics": negative_semantics,
                            "patient_hpo_id": patient_hpo_id,
                            "patient_status": patient_status,
                            "assertion_hpo_id": assertion_hpo_id,
                            "qualifier": qualifier or None,
                            "frequency": frequency or None,
                            "reference": assertion.get("reference"),
                            "evidence": assertion.get("evidence"),
                            "biocuration": assertion.get("biocuration"),
                        })
                elif patient_status in {"ABSENT", "EXCLUDED"} and not negative_semantics:
                    disease_term_is_within_absent_term = (
                        patient_hpo_id == assertion_hpo_id
                        or patient_hpo_id in ontology.ancestors(assertion_hpo_id)
                    )
                    if disease_term_is_within_absent_term:
                        result["potential_discordances"].append({
                            "type": "PATIENT_ABSENT_VS_DISEASE_ANNOTATED_FEATURE",
                            "patient_hpo_id": patient_hpo_id,
                            "patient_status": patient_status,
                            "assertion_hpo_id": assertion_hpo_id,
                            "qualifier": qualifier or None,
                            "frequency": frequency or None,
                            "reference": assertion.get("reference"),
                            "evidence": assertion.get("evidence"),
                            "biocuration": assertion.get("biocuration"),
                        })

        unresolved = bool(
            result["unresolved_patient_terms"] or result["unresolved_assertion_terms"]
        )
        requires_review = bool(
            unresolved
            or result["potential_discordances"]
            or result["contradictory_patient_terms"]
        )
        result.update({
            "status": "REQUIRES_REVIEW" if requires_review else "COMPARISON_COMPLETE",
            "review_required": requires_review,
        })
        return result

    def _record(
        self,
        *,
        variant_id: UUID,
        evidence_type: str,
        statement: str,
        direction: str,
        source_name: str | None,
        source_version: str | None,
        payload: dict[str, Any],
        observation_ids: tuple[UUID, ...] = (),
        resource_id: UUID | None = None,
        request_fingerprint: str | None = None,
        response_sha256: str | None = None,
        request_metadata: dict[str, Any] | None = None,
    ) -> EvidenceRecord:
        if evidence_type not in EVIDENCE_TYPES:
            raise EvidenceEngineError(f"Unsupported evidence type: {evidence_type}")
        if direction not in DIRECTIONS:
            raise EvidenceEngineError(f"Unsupported evidence direction: {direction}")
        return EvidenceRecord(
            evidence_id=uuid4(),
            variant_id=variant_id,
            evidence_type=evidence_type,
            statement=statement,
            direction=direction,
            source_name=source_name,
            source_version=source_version,
            observation_ids=observation_ids,
            payload=payload,
            resource_id=resource_id,
            request_fingerprint=request_fingerprint,
            response_sha256=response_sha256,
            request_metadata=request_metadata,
        )

    def _population(
        self,
        *,
        variant_id: UUID,
        annotation: dict[str, Any],
        provider_name: str,
        provider_version: str | None,
        resource_name: str | None,
        resource_version: str | None,
        population_observations: Iterable[dict[str, Any]],
    ) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []

        # Prefer persisted/direct population observations because they carry an
        # explicit population code and resource provenance.
        for obs in population_observations:
            availability = _normalize_text(obs.get("availability"))
            if availability not in {None, "AVAILABLE"}:
                continue
            allele_number = _int(obs.get("allele_number"))
            af = qualified_allele_frequency(obs.get("allele_frequency"), allele_number)
            if all(value in (None, "") for value in (af, obs.get("allele_count"), obs.get("allele_number"), obs.get("homozygote_count"))):
                continue
            population_code = _normalize_text(obs.get("population_code")) or "UNKNOWN"
            label = _normalize_text(obs.get("population_label")) or population_code
            source = _normalize_text(obs.get("resource_name")) or resource_name or provider_name
            version = _normalize_text(obs.get("resource_version")) or resource_version or provider_version
            records.append(
                self._record(
                    variant_id=variant_id,
                    evidence_type="POPULATION",
                    statement=(
                        f"Population observation is available for {label}; the evidence layer preserves the observation "
                        "without assigning an ACMG criterion strength."
                    ),
                    direction="NEUTRAL",
                    source_name=source,
                    source_version=version,
                    payload={
                        "population_code": population_code,
                        "population_label": label,
                        "allele_frequency": af,
                        "allele_count": _int(obs.get("allele_count")),
                        "allele_number": allele_number,
                        "homozygote_count": _int(obs.get("homozygote_count")),
                        "quality_status": obs.get("quality_status"),
                        "availability": availability,
                        "interpretive_use": "OBSERVATION_ONLY_UNTIL_RULE_EVALUATION",
                    },
                    observation_ids=_uuid_tuple(obs.get("observation_id")),
                )
            )

        # Also preserve provider-derived aggregate frequencies that may not be
        # persisted as direct population observations yet.
        population = annotation.get("population") or {}
        for label_key, af_key, an_key, ac_key, hom_key in (
            ("GLOBAL", "reference_population_af", "reference_population_an", "reference_population_ac", "reference_population_hom"),
            ("GNOMAD_EXOMES", "gnomad_exomes_af", "gnomad_exomes_an", "gnomad_exomes_ac", "gnomad_exomes_homalt"),
            ("GNOMAD_GENOMES", "gnomad_genomes_af", "gnomad_genomes_an", "gnomad_genomes_ac", "gnomad_genomes_homalt"),
        ):
            an = _int(population.get(an_key))
            af = qualified_allele_frequency(population.get(af_key), an)
            ac = _int(population.get(ac_key))
            hom = _int(population.get(hom_key))
            if af is None and ac is None and hom is None:
                continue
            records.append(
                self._record(
                    variant_id=variant_id,
                    evidence_type="POPULATION",
                    statement=f"Provider-derived population observation is available for {label_key}; no ACMG criterion strength is assigned by the evidence layer.",
                    direction="NEUTRAL",
                    source_name=resource_name or provider_name,
                    source_version=resource_version or provider_version,
                    payload={
                        "population_code": label_key,
                        "allele_frequency": af,
                        "allele_count": ac,
                        "allele_number": an,
                        "homozygote_count": hom,
                        "interpretive_use": "OBSERVATION_ONLY_UNTIL_RULE_EVALUATION",
                    },
                )
            )
        return records

    def _clinical(self, *, variant_id: UUID, annotation: dict[str, Any], provider_name: str, provider_version: str | None, resource_name: str | None, resource_version: str | None) -> list[EvidenceRecord]:
        clinical = annotation.get("clinical") or {}
        classification = _normalize_text(clinical.get("clinvar_classification"))
        if not classification:
            return []
        low = classification.lower()
        if "conflict" in low or "uncertain" in low or "unknown" in low:
            direction = "NEUTRAL"
        elif "pathogenic" in low or "likely pathogenic" in low:
            direction = "SUPPORTS"
        elif "benign" in low or "likely benign" in low:
            direction = "REFUTES"
        else:
            direction = "NEUTRAL"
        # These fields are returned inside the GeneBe annotation payload. They are
        # ClinVar-derived provider output, not a direct ClinVar resource execution.
        return [
            self._record(
                variant_id=variant_id,
                evidence_type="PROVIDER_ASSERTION",
                statement="The annotation provider returned a ClinVar-derived clinical significance assertion for this variant; it is preserved as provider output and requires source-specific review before clinical use.",
                direction=direction,
                source_name=resource_name or provider_name,
                source_version=resource_version or provider_version,
                payload={
                    "upstream_source": "ClinVar",
                    "clinical_significance": clinical.get("clinvar_classification"),
                    "disease": clinical.get("clinvar_disease"),
                    "review_status": clinical.get("clinvar_review_status"),
                    "submissions_summary": clinical.get("clinvar_submissions_summary"),
                    "direct_resource_execution": False,
                    "requires_review": True,
                    "interpretive_use": "PROVIDER_OUTPUT_NOT_DIRECT_CLINVAR_EVIDENCE",
                },
            )
        ]

    def _computational(self, *, variant_id: UUID, annotation: dict[str, Any], provider_name: str, provider_version: str | None) -> list[EvidenceRecord]:
        computational = annotation.get("computational") or {}
        populated = {k: v for k, v in computational.items() if v not in (None, "", [], {})}
        if not populated:
            return []
        return [
            self._record(
                variant_id=variant_id,
                evidence_type="COMPUTATIONAL",
                statement="Computational predictor observations are available; they require criterion-specific and gene/disease-appropriate interpretation before clinical use.",
                direction="NEUTRAL",
                source_name=provider_name,
                source_version=provider_version,
                payload={
                    "predictors": populated,
                    "interpretive_use": "REVIEW_REQUIRED",
                },
            )
        ]

    def _splicing(self, *, variant_id: UUID, annotation: dict[str, Any], provider_name: str, provider_version: str | None) -> list[EvidenceRecord]:
        splice = annotation.get("splice") or {}
        populated = {k: v for k, v in splice.items() if v not in (None, "", [], {})}
        if not populated:
            return []
        return [
            self._record(
                variant_id=variant_id,
                evidence_type="SPLICING",
                statement="Splicing prediction observations are available; these observations do not by themselves establish a clinical splicing criterion.",
                direction="NEUTRAL",
                source_name=provider_name,
                source_version=provider_version,
                payload={"predictors": populated, "interpretive_use": "REVIEW_REQUIRED"},
            )
        ]

    def _consequence(self, *, variant_id: UUID, annotation: dict[str, Any], provider_name: str, provider_version: str | None, resource_name: str | None, resource_version: str | None) -> list[EvidenceRecord]:
        gene = annotation.get("gene") or {}
        transcript = annotation.get("transcript") or {}
        effect = annotation.get("effect")
        consequences = annotation.get("hgvs_consequences") or []
        if not gene.get("symbol") and not transcript and not effect and not consequences:
            return []
        return [
            self._record(
                variant_id=variant_id,
                evidence_type="CONSEQUENCE",
                statement="Gene, transcript, and consequence annotations describe the predicted molecular consequence of the variant.",
                direction="NEUTRAL",
                source_name=resource_name or provider_name,
                source_version=resource_version or provider_version,
                payload={
                    "gene": gene,
                    "transcript": transcript,
                    "effect": effect,
                    "hgvs_consequences": consequences,
                    "interpretive_use": "ANNOTATION_FACT",
                },
            )
        ]

    def _provider_assertion(self, *, variant_id: UUID, annotation: dict[str, Any], provider_name: str, provider_version: str | None) -> list[EvidenceRecord]:
        provider_acmg = annotation.get("provider_acmg") or {}
        if not provider_acmg:
            return []
        if not any(provider_acmg.get(k) not in (None, "", [], {}) for k in ("score", "classification", "criteria", "by_gene")):
            return []
        return [
            self._record(
                variant_id=variant_id,
                evidence_type="PROVIDER_ASSERTION",
                statement="The annotation provider returned an ACMG-oriented assertion. SIRALOOM preserves it as provider output and does not equate it with a reviewed final classification.",
                direction="NEUTRAL",
                source_name=provider_name,
                source_version=provider_version,
                payload={
                    "provider_acmg": provider_acmg,
                    "interpretive_use": "PROVIDER_OUTPUT_NOT_FINAL",
                },
            )
        ]



def _uuid_tuple(value: Any) -> tuple[UUID, ...]:
    if value in (None, ""):
        return tuple()
    try:
        return (UUID(str(value)),)
    except (ValueError, TypeError):
        return tuple()

def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
