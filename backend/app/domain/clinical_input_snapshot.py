"""Stable capture of clinical inputs consumed by a scientific analysis stage."""

from __future__ import annotations

import hashlib
from copy import deepcopy
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    Analysis,
    Case,
    ClinicalIntakeRevision,
    Artifact,
    PhenotypeObservation,
    PhenotypeObservationAmendment,
    PedigreeMember,
    PedigreeRelationship,
    Specimen,
    WorkflowStep,
)

SNAPSHOT_SCHEMA_VERSION = 3


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_case_clinical_input_snapshot(db: Session, analysis: Analysis) -> dict[str, Any]:
    """Build the input snapshot used by the evidence stage for this analysis.

    Case-level observations are intentionally captured alongside analysis-level
    observations because the current evidence stage consumes both.
    """
    case = db.scalar(
        select(Case).where(Case.id == analysis.case_id).with_for_update()
    )
    if case is None:
        raise ValueError("Cannot snapshot clinical inputs for a missing case")
    rows = db.scalars(
        select(PhenotypeObservation)
        .where(
            PhenotypeObservation.case_id == analysis.case_id,
            (PhenotypeObservation.analysis_id == analysis.id)
            | (PhenotypeObservation.analysis_id.is_(None)),
        )
        .order_by(PhenotypeObservation.created_at, PhenotypeObservation.id)
    ).all()
    amendments = db.scalars(
        select(PhenotypeObservationAmendment).where(
            PhenotypeObservationAmendment.observation_id.in_([row.id for row in rows])
        )
    ).all() if rows else []
    amendment_by_observation = {item.observation_id: item for item in amendments}
    phenotype_by_id = {row.id: row for row in rows}
    context = case.clinical_context if isinstance(case.clinical_context, dict) else {}
    gene_disease_evidence = context.get("gene_disease_evidence") or []
    literature_evidence = context.get("literature_evidence") or []
    if not isinstance(gene_disease_evidence, list) or not all(
        isinstance(item, dict) for item in gene_disease_evidence
    ):
        raise ValueError("Case gene-disease evidence must be a list of records")
    if not isinstance(literature_evidence, list) or not all(
        isinstance(item, dict) for item in literature_evidence
    ):
        raise ValueError("Case literature evidence must be a list of records")
    intake_revision = db.scalar(
        select(ClinicalIntakeRevision)
        .where(ClinicalIntakeRevision.case_id == analysis.case_id)
        .order_by(ClinicalIntakeRevision.version.desc())
        .limit(1)
    )
    intake_revision_snapshot = None
    if intake_revision is not None:
        intake_context = intake_revision.context or {}
        prior_testing = intake_context.get("prior_testing") or []
        artifact_ids = {
            UUID(str(item["artifact_id"]))
            for item in prior_testing
            if isinstance(item, dict) and item.get("artifact_id")
        }
        if artifact_ids:
            source_artifacts = {
                artifact.id: artifact
                for artifact in db.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids)))
            }
            if any(
                artifact_id not in source_artifacts
                or source_artifacts[artifact_id].case_id != analysis.case_id
                for artifact_id in artifact_ids
            ):
                raise ValueError("Clinical prior-testing evidence references an artifact outside the case")
        intake_revision_snapshot = {
            "revision_id": str(intake_revision.id),
            "version": intake_revision.version,
            "schema_version": intake_revision.schema_version,
            "revision_fingerprint": intake_revision.revision_fingerprint,
            "intake_status": intake_revision.intake_status,
            "phenotype_review_status": intake_revision.phenotype_review_status,
            "family_history_review_status": intake_revision.family_history_review_status,
            "context": intake_context,
            "phenotype_review_note": intake_revision.phenotype_review_note,
            "family_history_review_note": intake_revision.family_history_review_note,
            "completion_note": intake_revision.completion_note,
            "recorded_by": str(intake_revision.recorded_by),
            "recorded_at": intake_revision.recorded_at.isoformat(),
        }

    members = db.scalars(
        select(PedigreeMember)
        .where(PedigreeMember.case_id == analysis.case_id)
        .order_by(PedigreeMember.member_identifier, PedigreeMember.id)
    ).all()
    member_by_id = {member.id: member for member in members}
    relationships = db.scalars(
        select(PedigreeRelationship)
        .where(PedigreeRelationship.case_id == analysis.case_id)
        .order_by(PedigreeRelationship.parent_member_id, PedigreeRelationship.child_member_id)
    ).all()
    if sum(1 for member in members if member.is_proband) > 1:
        raise ValueError("Pedigree contains more than one member marked as the proband")
    if any(
        relationship.parent_member_id not in member_by_id
        or relationship.child_member_id not in member_by_id
        or relationship.parent_member_id == relationship.child_member_id
        for relationship in relationships
    ):
        raise ValueError("Pedigree relationships reference invalid members in the case")
    children_by_parent: dict[UUID, set[UUID]] = {}
    for relationship in relationships:
        children_by_parent.setdefault(relationship.parent_member_id, set()).add(
            relationship.child_member_id
        )
    visiting: set[UUID] = set()
    visited: set[UUID] = set()

    def visit(member_id: UUID) -> None:
        if member_id in visiting:
            raise ValueError("Pedigree relationships contain an ancestry cycle")
        if member_id in visited:
            return
        visiting.add(member_id)
        for child_id in children_by_parent.get(member_id, set()):
            visit(child_id)
        visiting.remove(member_id)
        visited.add(member_id)

    for member_id in member_by_id:
        visit(member_id)
    if any(
        row.subject_member_id is not None and row.subject_member_id not in member_by_id
        for row in rows
    ):
        raise ValueError("Phenotype observation subject does not belong to the case pedigree")
    specimen_ids = {member.specimen_id for member in members if member.specimen_id}
    specimens = {
        specimen.id: specimen
        for specimen in db.scalars(select(Specimen).where(Specimen.id.in_(specimen_ids)))
    } if specimen_ids else {}
    if any(
        member.specimen_id is not None
        and (member.specimen_id not in specimens or specimens[member.specimen_id].case_id != analysis.case_id)
        for member in members
    ):
        raise ValueError("Pedigree member specimen does not belong to the case")

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "clinical_context": context,
        "clinical_context_revision": intake_revision_snapshot,
        "pedigree_context": {
            "members": [
                {
                    "member_id": str(member.id),
                    "member_identifier": member.member_identifier,
                    "relationship_to_proband": member.relationship_to_proband,
                    "sex": member.sex,
                    "affected_status": member.affected_status,
                    "is_proband": member.is_proband,
                    "sampled": member.sampled,
                    "specimen_id": str(member.specimen_id) if member.specimen_id else None,
                    "specimen_identifier": (
                        specimens[member.specimen_id].specimen_identifier
                        if member.specimen_id in specimens else None
                    ),
                    "specimen_type": (
                        specimens[member.specimen_id].specimen_type
                        if member.specimen_id in specimens else None
                    ),
                    "metadata": member.metadata_json or {},
                }
                for member in members
            ],
            "relationships": [
                {
                    "parent_member_id": str(relationship.parent_member_id),
                    "child_member_id": str(relationship.child_member_id),
                    "relationship_type": relationship.relationship_type,
                    "metadata": relationship.metadata_json or {},
                }
                for relationship in relationships
            ],
        },
        "phenotype_observations": [
            {
                "phenotype_id": str(row.id),
                "case_id": str(row.case_id),
                "analysis_id": str(row.analysis_id) if row.analysis_id else None,
                "scope": "CASE" if row.analysis_id is None else "ANALYSIS",
                "record_lifecycle_status": amendment_by_observation[row.id].amendment_type if row.id in amendment_by_observation else "ACTIVE",
                "amendment_id": str(amendment_by_observation[row.id].id) if row.id in amendment_by_observation else None,
                "amendment_reason": amendment_by_observation[row.id].reason if row.id in amendment_by_observation else None,
                "replacement_observation_id": str(amendment_by_observation[row.id].replacement_observation_id) if row.id in amendment_by_observation and amendment_by_observation[row.id].replacement_observation_id else None,
                "replacement_observation_fingerprint": (
                    phenotype_by_id[amendment_by_observation[row.id].replacement_observation_id].record_fingerprint
                    if row.id in amendment_by_observation
                    and amendment_by_observation[row.id].replacement_observation_id in phenotype_by_id
                    else None
                ),
                "amendment_recorded_by": str(amendment_by_observation[row.id].recorded_by) if row.id in amendment_by_observation else None,
                "amendment_recorded_at": amendment_by_observation[row.id].recorded_at.isoformat() if row.id in amendment_by_observation else None,
                "hpo_id": row.hpo_id,
                "canonical_hpo_id": row.canonical_hpo_id,
                "subject_member_id": str(row.subject_member_id) if row.subject_member_id else None,
                "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                "clinical_attributes": row.clinical_attributes or {},
                "ontology_resolution": row.ontology_resolution or {},
                "label": row.label,
                "present": row.present,
                "phenotype_status": row.phenotype_status,
                "onset": row.onset,
                "severity": row.severity,
                "source": row.source,
                "evidence": row.evidence or {},
            }
            for row in rows
        ],
        "gene_disease_evidence": gene_disease_evidence,
        "literature_evidence": literature_evidence,
    }


def validate_case_clinical_input_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") not in {1, 2, SNAPSHOT_SCHEMA_VERSION}:
        raise ValueError("Persisted clinical input snapshot has an unsupported schema")
    if not isinstance(value.get("phenotype_observations"), list):
        raise ValueError("Persisted clinical input snapshot has invalid phenotype observations")
    if "clinical_context" in value and not isinstance(value["clinical_context"], dict):
        raise ValueError("Persisted clinical input snapshot has invalid clinical context")
    if "clinical_context_revision" in value and value["clinical_context_revision"] is not None and not isinstance(value["clinical_context_revision"], dict):
        raise ValueError("Persisted clinical input snapshot has invalid clinical context revision")
    if "pedigree_context" in value and (
        not isinstance(value["pedigree_context"], dict)
        or not isinstance(value["pedigree_context"].get("members"), list)
        or not isinstance(value["pedigree_context"].get("relationships"), list)
    ):
        raise ValueError("Persisted clinical input snapshot has invalid pedigree context")
    if "pedigree_context" in value:
        member_ids = {
            str(member.get("member_id"))
            for member in value["pedigree_context"]["members"]
            if isinstance(member, dict) and member.get("member_id")
        }
        proband_count = sum(
            1 for member in value["pedigree_context"]["members"]
            if isinstance(member, dict) and member.get("is_proband")
        )
        if proband_count > 1:
            raise ValueError("Persisted clinical input snapshot has multiple probands")
        for row in value["phenotype_observations"]:
            subject_id = row.get("subject_member_id") if isinstance(row, dict) else None
            if subject_id is not None and str(subject_id) not in member_ids:
                raise ValueError("Persisted phenotype observation references a missing pedigree member")
    for key in ("gene_disease_evidence", "literature_evidence"):
        if not isinstance(value.get(key), list) or not all(
            isinstance(item, dict) for item in value[key]
        ):
            raise ValueError(f"Persisted clinical input snapshot has invalid {key}")
    for row in value["phenotype_observations"]:
        if (
            not isinstance(row, dict)
            or row.get("scope") not in {"CASE", "ANALYSIS"}
            or not isinstance(row.get("hpo_id"), str)
            or not isinstance(row.get("phenotype_status"), str)
            or (row.get("clinical_attributes") is not None and not isinstance(row.get("clinical_attributes"), dict))
            or (row.get("ontology_resolution") is not None and not isinstance(row.get("ontology_resolution"), dict))
            or (row.get("subject_member_id") is not None and not isinstance(row.get("subject_member_id"), str))
            or row.get("record_lifecycle_status", "ACTIVE") not in {"ACTIVE", "SUPERSEDED", "RETRACTED"}
            or (
                row.get("record_lifecycle_status") == "SUPERSEDED"
                and (not row.get("replacement_observation_id") or not row.get("replacement_observation_fingerprint"))
            )
            or (row.get("record_lifecycle_status") == "RETRACTED" and not row.get("amendment_reason"))
        ):
            raise ValueError("Persisted clinical input snapshot contains an invalid phenotype row")
    return value


def patient_phenotype_observations(value: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only primary-patient observations for patient phenotype interpretation.

    Family-member findings remain in the same immutable snapshot but must not be
    silently mixed into the proband's phenotype vector.
    """
    validated = validate_case_clinical_input_snapshot(value)
    pedigree = validated.get("pedigree_context") or {}
    proband_ids = {
        str(member.get("member_id"))
        for member in pedigree.get("members", [])
        if isinstance(member, dict) and member.get("is_proband") and member.get("member_id")
    }
    return [
        row for row in validated["phenotype_observations"]
        if row.get("record_lifecycle_status", "ACTIVE") == "ACTIVE"
        and (row.get("subject_member_id") is None or str(row.get("subject_member_id")) in proband_ids)
    ]


def family_phenotype_observations(value: dict[str, Any]) -> list[dict[str, Any]]:
    """Return explicitly family-member observations, excluding the proband."""
    validated = validate_case_clinical_input_snapshot(value)
    pedigree = validated.get("pedigree_context") or {}
    proband_ids = {
        str(member.get("member_id"))
        for member in pedigree.get("members", [])
        if isinstance(member, dict) and member.get("is_proband") and member.get("member_id")
    }
    return [
        row for row in validated["phenotype_observations"]
        if row.get("record_lifecycle_status", "ACTIVE") == "ACTIVE"
        and row.get("subject_member_id") is not None
        and str(row.get("subject_member_id")) not in proband_ids
    ]


def _semantic_snapshot_for_digest(value: dict[str, Any]) -> dict[str, Any]:
    """Remove database-generated identifiers while retaining clinical meaning and lifecycle state."""
    semantic = deepcopy(value)

    clinical_context = semantic.get("clinical_context")
    if isinstance(clinical_context, dict):
        pointer = clinical_context.get("clinical_intake_revision")
        if isinstance(pointer, dict):
            pointer.pop("revision_id", None)
        intake = clinical_context.get("clinical_intake")
        if isinstance(intake, dict):
            for test in intake.get("prior_testing", []) if isinstance(intake.get("prior_testing"), list) else []:
                if isinstance(test, dict):
                    test.pop("artifact_id", None)

    revision = semantic.get("clinical_context_revision")
    if isinstance(revision, dict):
        for key in ("revision_id", "revision_fingerprint", "recorded_by", "recorded_at"):
            revision.pop(key, None)
        intake = revision.get("context")
        if isinstance(intake, dict):
            for test in intake.get("prior_testing", []) if isinstance(intake.get("prior_testing"), list) else []:
                if isinstance(test, dict):
                    test.pop("artifact_id", None)

    pedigree = semantic.get("pedigree_context")
    member_identifiers: dict[str, str] = {}
    if isinstance(pedigree, dict):
        for member in pedigree.get("members", []):
            if not isinstance(member, dict):
                continue
            member_id = member.pop("member_id", None)
            if member_id is not None and member.get("member_identifier"):
                member_identifiers[str(member_id)] = str(member["member_identifier"])
            member.pop("specimen_id", None)
        pedigree["members"] = sorted(
            pedigree.get("members", []), key=_canonical_json
        )
        for relationship in pedigree.get("relationships", []):
            if not isinstance(relationship, dict):
                continue
            for key in ("parent_member_id", "child_member_id"):
                member_id = relationship.pop(key, None)
                if member_id is not None:
                    relationship[key.replace("_id", "_identifier")] = member_identifiers.get(
                        str(member_id), str(member_id)
                    )
        pedigree["relationships"] = sorted(
            pedigree.get("relationships", []), key=_canonical_json
        )

    phenotype_rows = semantic.get("phenotype_observations", [])
    for row in phenotype_rows:
        if not isinstance(row, dict):
            continue
        subject_id = row.pop("subject_member_id", None)
        if subject_id is not None:
            row["subject_member_identifier"] = member_identifiers.get(
                str(subject_id), str(subject_id)
            )
        for key in (
            "phenotype_id", "case_id", "analysis_id", "amendment_id",
            "replacement_observation_id", "amendment_recorded_by", "amendment_recorded_at",
        ):
            row.pop(key, None)
    semantic["phenotype_observations"] = sorted(phenotype_rows, key=_canonical_json)
    return semantic


def clinical_input_snapshot_digest(value: dict[str, Any]) -> str:
    validated = validate_case_clinical_input_snapshot(value)
    semantic = _semantic_snapshot_for_digest(validated)
    return hashlib.sha256(_canonical_json(semantic).encode("utf-8")).hexdigest()


def capture_or_reuse_case_clinical_input_snapshot(
    db: Session, analysis: Analysis, evidence_step: WorkflowStep
) -> dict[str, Any]:
    """Persist the evidence stage's clinical inputs once and reuse on retries."""
    metadata = dict(evidence_step.metadata_json or {})
    snapshot = metadata.get("clinical_input_snapshot")
    if snapshot is None:
        snapshot = build_case_clinical_input_snapshot(db, analysis)
        metadata["clinical_input_snapshot"] = snapshot
        metadata["clinical_input_snapshot_sha256"] = clinical_input_snapshot_digest(snapshot)
        evidence_step.metadata_json = metadata
        db.add(evidence_step)
        # The snapshot must be durable before external queries or evidence writes.
        db.commit()
        return snapshot

    snapshot = validate_case_clinical_input_snapshot(snapshot)
    if metadata.get("clinical_input_snapshot_sha256") != clinical_input_snapshot_digest(snapshot):
        raise ValueError("Persisted clinical input snapshot checksum does not match")
    return snapshot


def inherit_reused_case_clinical_input_snapshot(
    parent_step: WorkflowStep, child_step: WorkflowStep
) -> dict[str, Any] | None:
    """Copy and validate frozen clinical inputs when an evidence stage is reused."""
    parent_metadata = parent_step.metadata_json or {}
    snapshot = parent_metadata.get("clinical_input_snapshot")
    if snapshot is None:
        return None
    snapshot = validate_case_clinical_input_snapshot(snapshot)
    digest = clinical_input_snapshot_digest(snapshot)
    if parent_metadata.get("clinical_input_snapshot_sha256") != digest:
        raise ValueError("Parent clinical input snapshot checksum does not match")

    child_metadata = dict(child_step.metadata_json or {})
    existing = child_metadata.get("clinical_input_snapshot")
    if existing is not None:
        existing = validate_case_clinical_input_snapshot(existing)
        if child_metadata.get("clinical_input_snapshot_sha256") != clinical_input_snapshot_digest(existing):
            raise ValueError("Child clinical input snapshot checksum does not match")
        if existing != snapshot:
            raise ValueError("Child clinical inputs conflict with reused parent evidence")
    child_metadata["clinical_input_snapshot"] = snapshot
    child_metadata["clinical_input_snapshot_sha256"] = digest
    child_step.metadata_json = child_metadata
    return snapshot


def saved_case_clinical_input_snapshot(
    db: Session, analysis_id: UUID
) -> dict[str, Any] | None:
    step = db.scalar(
        select(WorkflowStep).where(
            WorkflowStep.analysis_id == analysis_id,
            WorkflowStep.step_id == "build_evidence",
        )
    )
    metadata = step.metadata_json or {} if step else {}
    snapshot = metadata.get("clinical_input_snapshot")
    if snapshot is None:
        return None
    snapshot = validate_case_clinical_input_snapshot(snapshot)
    if metadata.get("clinical_input_snapshot_sha256") != clinical_input_snapshot_digest(snapshot):
        raise ValueError("Persisted clinical input snapshot checksum does not match")
    return snapshot
