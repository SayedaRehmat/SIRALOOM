from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID, uuid4

from backend.app.domain.evidence import EvidenceRecord


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

    def build_case_context_evidence(
        self, *, variant_id: UUID, case_hpo_terms: list[dict[str, Any]], gene: str | None,
        gene_disease_records: list[dict[str, Any]] = (), literature_records: list[dict[str, Any]] = (),
    ) -> list[EvidenceRecord]:
        """Create contextual evidence without turning phenotype/literature into pathogenicity."""
        out: list[EvidenceRecord] = []
        if case_hpo_terms:
            from backend.app.phenotype import normalize_terms
            terms = normalize_terms(case_hpo_terms)
            present = [t for t in terms if t.present]
            absent = [t for t in terms if not t.present]
            out.append(self._record(
                variant_id=variant_id, evidence_type="PHENOTYPE",
                statement="Structured HPO phenotype context is available for case-level relevance and prioritization; it is not pathogenicity evidence by itself.",
                direction="NEUTRAL", source_name="HPO_CASE_CONTEXT", source_version=None,
                payload={"gene": gene, "present_terms":[{"hpo_id":t.hpo_id,"label":t.label} for t in present],
                         "negative_terms":[{"hpo_id":t.hpo_id,"label":t.label} for t in absent],
                         "interpretive_use":"CASE_RELEVANCE_AND_PRIORITIZATION"},
            ))
        for item in gene_disease_records:
            if gene and item.get("gene") and str(item.get("gene")).upper() != gene.upper():
                continue
            disease = str(item.get("disease") or "").strip()
            if not disease: continue
            payload = dict(item)
            payload["gene"] = gene or item.get("gene")
            payload["interpretive_use"] = "GENE_DISEASE_RELEVANCE_REVIEW"
            target_hpo = item.get("hpo_terms") or item.get("associated_hpo_terms") or []
            if target_hpo and case_hpo_terms:
                from backend.app.phenotype import match_hpo, priority_adjustment
                match = match_hpo(case_hpo_terms, target_hpo, ancestor_map=item.get("hpo_ancestor_map"))
                payload["phenotype_match"] = {"score": match.score, "matched_terms": list(match.matched), "query_count": match.query_count, "target_count": match.target_count, "method": match.method, "priority_adjustment": priority_adjustment(match.score)}
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
            if all(obs.get(k) in (None, "") for k in ("allele_frequency", "allele_count", "allele_number", "homozygote_count")):
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
                        "allele_frequency": _float(obs.get("allele_frequency")),
                        "allele_count": _int(obs.get("allele_count")),
                        "allele_number": _int(obs.get("allele_number")),
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
        for label_key, af_key, ac_key, hom_key in (
            ("GLOBAL", "reference_population_af", "reference_population_ac", "reference_population_hom"),
            ("GNOMAD_EXOMES", "gnomad_exomes_af", "gnomad_exomes_ac", "gnomad_exomes_homalt"),
            ("GNOMAD_GENOMES", "gnomad_genomes_af", "gnomad_genomes_ac", "gnomad_genomes_homalt"),
        ):
            af = _float(population.get(af_key))
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
                        "allele_number": None,
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
        return [
            self._record(
                variant_id=variant_id,
                evidence_type="CLINICAL_DATABASE",
                statement="ClinVar provides an existing clinical significance assertion for this variant; the assertion is preserved as source evidence and is not treated as an automatic final SIRALOOM classification.",
                direction=direction,
                source_name=resource_name or "ClinVar via provider",
                source_version=resource_version or provider_version,
                payload={
                    "clinical_significance": clinical.get("clinvar_classification"),
                    "disease": clinical.get("clinvar_disease"),
                    "review_status": clinical.get("clinvar_review_status"),
                    "submissions_summary": clinical.get("clinvar_submissions_summary"),
                    "requires_review": True,
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

    def _consequence(self, *, variant_id: UUID, annotation: dict[str, Any], provider_name: str, provider_version: str | None) -> list[EvidenceRecord]:
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
                source_name=provider_name,
                source_version=provider_version,
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
