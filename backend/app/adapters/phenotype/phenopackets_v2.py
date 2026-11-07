"""Loss-aware GA4GH Phenopackets v2 export for SIRALOOM clinical intake.

The GA4GH protobuf schema is the serialization authority. Local clinical states
and attributes that cannot be represented without semantic loss are reported;
strict export rejects them unless the caller explicitly opts into a lossy
exchange. The caller must separately retain the SIRALOOM clinical snapshot.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5


class PhenopacketExportError(ValueError):
    """The case cannot be represented faithfully as a GA4GH Phenopacket."""


_SCHEMA_VERSION = "2.0"
_HPO_RESOURCE = {
    "id": "hp",
    "name": "Human Phenotype Ontology",
    "url": "http://purl.obolibrary.org/obo/hp.obo",
    "namespacePrefix": "HP",
    "iriPrefix": "http://purl.obolibrary.org/obo/HP_",
}
_SEX_VALUES = {"MALE", "FEMALE", "OTHER_SEX", "UNKNOWN_SEX"}
_SEX_NUMBERS = {"UNKNOWN": 0, "UNKNOWN_SEX": 0, "FEMALE": 1, "MALE": 2, "OTHER": 3, "OTHER_SEX": 3}
_AFFECTED_VALUES = {"UNKNOWN": "MISSING", "UNAFFECTED": "UNAFFECTED", "AFFECTED": "AFFECTED"}


def _value(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


def _member_id(member: Any) -> str:
    # Deterministic pseudonym: do not expose the database primary key or the
    # human-entered member identifier in the standards document.
    opaque_id = uuid5(NAMESPACE_URL, f"siraloom:pedigree-member:{_value(member, 'id')}")
    return f"SIRALOOM:{opaque_id}"


def _case_id(case: Any) -> str:
    opaque_id = uuid5(NAMESPACE_URL, f"siraloom:case:{_value(case, 'id')}")
    return f"SIRALOOM:{opaque_id}"


def _normalize_sex(value: Any) -> str | None:
    normalized = str(value or "").upper()
    normalized = {"UNKNOWN": "UNKNOWN_SEX", "OTHER": "OTHER_SEX"}.get(normalized, normalized)
    return normalized if normalized in _SEX_VALUES else None


def _hpo_version_iri(release: Any) -> str | None:
    value = str(release or "")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    if parsed.isoformat() != value:
        return None
    return f"http://purl.obolibrary.org/obo/hp/releases/{value}/hp.obo"


def _term_resolution(row: Any) -> dict[str, Any]:
    resolution = _value(row, "ontology_resolution", {}) or {}
    primary = resolution.get("primary_term") if isinstance(resolution, dict) else None
    return primary if isinstance(primary, dict) else {}


def _canonical_or_submitted(row: Any) -> str:
    primary = _term_resolution(row)
    if primary.get("status") in {"CURRENT", "ALTERNATE_ID"} and primary.get("canonical_id"):
        return str(primary["canonical_id"])
    return str(_value(row, "hpo_id"))


def _collect_loss_warnings(
    rows: list[Any], clinical_intake_revision: Any | None = None
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for row_index, row in enumerate(rows):
        status = str(_value(row, "phenotype_status", "PRESENT")).upper()
        observation_ref = str(_value(row, "record_fingerprint") or f"phenotype-record-{row_index + 1}")
        if status in {"UNKNOWN", "NOT_ASSESSED"}:
            warnings.append({
                "observation_ref": observation_ref,
                "field": "phenotype_status",
                "reason": f"GA4GH Phenopackets v2 cannot preserve the SIRALOOM {status} state distinctly.",
            })
        elif status == "EXCLUDED":
            warnings.append({
                "observation_ref": observation_ref,
                "field": "phenotype_status",
                "reason": "Phenopackets v2 excluded=true cannot distinguish SIRALOOM EXCLUDED from ABSENT.",
            })
        attributes = _value(row, "clinical_attributes", {}) or {}
        supported_attributes = {
            "onset_age_iso8601", "resolution_age_iso8601", "severity_hpo_id",
            "modifier_hpo_ids", "clinical_course_hpo_id",
        }
        for field, value in attributes.items():
            if value is not None and field not in supported_attributes:
                warnings.append({
                    "observation_ref": observation_ref,
                    "field": f"clinical_attributes.{field}",
                    "reason": f"{field} has no semantically equivalent PhenotypicFeature v2 field and is retained in the SIRALOOM sidecar.",
                })
        if _value(row, "onset"):
            warnings.append({
                "observation_ref": observation_ref,
                "field": "onset",
                "reason": "Free-text onset cannot be converted to a Phenopackets TimeElement without interpretation.",
            })
        if _value(row, "severity"):
            warnings.append({
                "observation_ref": observation_ref,
                "field": "severity",
                "reason": "Free-text severity is not an ontology-coded Phenopackets severity.",
            })
        related_terms = {
            str(item.get("input_id")): item
            for item in (_value(row, "ontology_resolution", {}) or {}).get("related_terms", [])
            if isinstance(item, dict) and item.get("input_id")
        }
        related_ids = list(attributes.get("modifier_hpo_ids", []) or [])
        related_ids.extend(
            term_id for term_id in (
                attributes.get("severity_hpo_id"),
                attributes.get("clinical_course_hpo_id"),
            ) if term_id
        )
        for term_id in related_ids:
            resolution = related_terms.get(str(term_id), {})
            if resolution.get("status") not in {"CURRENT", "ALTERNATE_ID"} or not resolution.get("canonical_id"):
                warnings.append({
                    "observation_ref": observation_ref,
                    "field": "related_hpo_term_resolution",
                    "reason": f"Related HPO term {term_id} is not resolved as CURRENT or ALTERNATE_ID and is omitted from the Phenopackets feature.",
                })
        if _value(row, "observed_at"):
            warnings.append({
                "observation_ref": observation_ref,
                "field": "observed_at",
                "reason": "PhenotypicFeature v2 does not carry the SIRALOOM observation timestamp; it is retained in the sidecar.",
            })
        if _value(row, "record_fingerprint"):
            warnings.append({
                "observation_ref": observation_ref,
                "field": "record_fingerprint",
                "reason": "The SIRALOOM source-record fingerprint is retained in the sidecar, not the base Phenopacket.",
            })
        if _value(row, "evidence", {}) or {}:
            warnings.append({
                "observation_ref": observation_ref,
                "field": "evidence",
                "reason": "SIRALOOM evidence payload is not mapped without an explicitly supported ECO code and reference.",
            })
        primary = _term_resolution(row)
        if primary.get("status") not in {"CURRENT", "ALTERNATE_ID"} or not primary.get("canonical_id"):
            warnings.append({
                "observation_ref": observation_ref,
                "field": "ontology_term_resolution",
                "reason": "The submitted HPO identifier is not resolved as CURRENT or ALTERNATE_ID; it is exported unchanged and must not be treated as ontology-validated.",
            })
        resource = (_value(row, "ontology_resolution", {}) or {}).get("resource")
        if (
            not isinstance(resource, dict)
            or not resource.get("ontology_release")
            or _hpo_version_iri(resource.get("ontology_release")) is None
        ):
            warnings.append({
                "observation_ref": observation_ref,
                "field": "ontology_provenance",
                "reason": "No pinned HPO release is recorded; the submitted HPO identifier is exported without a release claim.",
            })

    if clinical_intake_revision is not None:
        context = _value(clinical_intake_revision, "context", {}) or {}
        for field in (
            "referral_indication", "referral_question", "clinical_summary",
            "prior_testing", "differential_diagnoses", "source_document_references",
        ):
            if context.get(field):
                warnings.append({
                    "observation_id": "clinical-intake",
                    "field": f"clinical_intake.{field}",
                    "reason": "This clinical intake field has no equivalent in the base GA4GH Phenopacket v2 model; it is retained in the SIRALOOM response sidecar.",
                })
        age = context.get("age_at_assessment")
        if age:
            warnings.append({
                "observation_id": "clinical-intake",
                "field": "clinical_intake.age_at_assessment",
                "reason": "The GA4GH Individual.time_at_last_encounter field specifically represents age at the last encounter; SIRALOOM age_at_assessment is not assumed to be that encounter and is retained exactly in the SIRALOOM response sidecar.",
            })
        for field in (
            "intake_status", "phenotype_review_status", "family_history_review_status",
            "phenotype_review_note", "family_history_review_note", "completion_note",
        ):
            if _value(clinical_intake_revision, field):
                warnings.append({
                    "observation_id": "clinical-intake",
                    "field": f"clinical_intake.{field}",
                    "reason": "SIRALOOM review attestation/revision state has no equivalent in the base GA4GH Phenopacket v2 model; it is retained in the SIRALOOM response sidecar.",
                })
    return warnings


def _phenotypic_feature(row: Any) -> dict[str, Any] | None:
    status = str(_value(row, "phenotype_status", "PRESENT")).upper()
    if status in {"UNKNOWN", "NOT_ASSESSED"}:
        return None
    attributes = _value(row, "clinical_attributes", {}) or {}
    ontology_type = {"id": _canonical_or_submitted(row)}
    label = _value(row, "label")
    if label:
        ontology_type["label"] = str(label)
    feature: dict[str, Any] = {
        "type": ontology_type,
        "excluded": str(_value(row, "phenotype_status", "PRESENT")).upper() in {"ABSENT", "EXCLUDED"},
    }

    related = {
        str(item.get("input_id")): item
        for item in (_value(row, "ontology_resolution", {}) or {}).get("related_terms", [])
        if isinstance(item, dict) and item.get("input_id")
    }
    severity_id = attributes.get("severity_hpo_id")
    if severity_id:
        resolution = related.get(str(severity_id), {})
        if resolution.get("status") in {"CURRENT", "ALTERNATE_ID"} and resolution.get("canonical_id"):
            feature["severity"] = {
                "id": str(resolution["canonical_id"]),
                **({"label": str(resolution["label"])} if resolution.get("label") else {}),
            }

    modifiers: list[dict[str, str]] = []
    modifier_ids = list(attributes.get("modifier_hpo_ids", []) or [])
    course_id = attributes.get("clinical_course_hpo_id")
    if course_id:
        modifier_ids.append(course_id)
    for term_id in modifier_ids:
        resolution = related.get(str(term_id), {})
        if resolution.get("status") in {"CURRENT", "ALTERNATE_ID"} and resolution.get("canonical_id"):
            modifier = {"id": str(resolution["canonical_id"])}
            if resolution.get("label"):
                modifier["label"] = str(resolution["label"])
            modifiers.append(modifier)
    if modifiers:
        feature["modifiers"] = modifiers

    onset = attributes.get("onset_age_iso8601")
    if onset:
        feature["onset"] = {"age": {"iso8601duration": str(onset)}}
    resolution_age = attributes.get("resolution_age_iso8601")
    if resolution_age:
        feature["resolution"] = {"age": {"iso8601duration": str(resolution_age)}}
    return feature


def _metadata(rows: list[Any]) -> dict[str, Any]:
    releases: set[str] = set()
    for row in rows:
        resource = (_value(row, "ontology_resolution", {}) or {}).get("resource")
        if isinstance(resource, dict) and resource.get("ontology_release"):
            releases.add(str(resource["ontology_release"]))
    resource = dict(_HPO_RESOURCE)
    if len(releases) == 1:
        version_iri = _hpo_version_iri(next(iter(releases)))
        if version_iri:
            resource["version"] = version_iri
    return {
        "created": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "createdBy": "SIRALOOM",
        "submittedBy": "SIRALOOM",
        "resources": [resource],
        "phenopacketSchemaVersion": _SCHEMA_VERSION,
    }


def _packet(
    *,
    packet_id: str,
    subject_id: str,
    rows: list[Any],
    sex: str | None = None,
) -> dict[str, Any]:
    subject: dict[str, Any] = {"id": subject_id}
    normalized_sex = _normalize_sex(sex)
    if normalized_sex:
        subject["sex"] = normalized_sex
    return {
        "id": packet_id,
        "subject": subject,
        "phenotypicFeatures": [
            feature for row in rows
            if (feature := _phenotypic_feature(row)) is not None
        ],
        "metaData": _metadata(rows),
    }


def _explicit_consanguinous_parents(
    *,
    case: Any,
    members: list[Any],
    relationships: list[Any],
    clinical_intake_revision: Any | None,
) -> bool | None:
    candidates: list[bool] = []
    sources = [_value(case, "clinical_context", {}) or {}]
    sources.extend(_value(member, "metadata_json", {}) or {} for member in members)
    sources.extend(_value(relationship, "metadata_json", {}) or {} for relationship in relationships)
    sources.append(_value(clinical_intake_revision, "context", {}) or {})
    for source in sources:
        if isinstance(source, dict) and "consanguinous_parents" in source:
            value = source["consanguinous_parents"]
            if not isinstance(value, bool):
                raise PhenopacketExportError(
                    "consanguinous_parents must be an explicitly recorded boolean; string/number coercion is prohibited."
                )
            candidates.append(value)
    if len(set(candidates)) > 1:
        raise PhenopacketExportError("Conflicting explicit consanguinous_parents assertions exist in the case pedigree.")
    return candidates[0] if candidates else None


def _family_pedigree(*, case: Any, members: list[Any], relationships: list[Any]) -> dict[str, Any]:
    by_id = {str(_value(member, "id")): member for member in members}
    parent_ids: dict[str, dict[str, str]] = defaultdict(dict)
    for relationship in relationships:
        relationship_type = str(_value(relationship, "relationship_type") or "").upper()
        if relationship_type != "PARENT_CHILD":
            raise PhenopacketExportError(
                f"Relationship type {relationship_type!r} has no equivalent in the GA4GH Pedigree parentage fields."
            )
        parent_id = str(_value(relationship, "parent_member_id"))
        child_id = str(_value(relationship, "child_member_id"))
        if parent_id not in by_id or child_id not in by_id or parent_id == child_id:
            raise PhenopacketExportError("Pedigree relationship contains a member outside this case.")
        parent = by_id[parent_id]
        sex = str(_value(parent, "sex") or "").upper()
        role = "paternalId" if sex == "MALE" else "maternalId" if sex == "FEMALE" else None
        if role is None:
            raise PhenopacketExportError(
                "Cannot encode a parent-child edge in GA4GH Pedigree without a recorded MALE/FEMALE parent sex; "
                "the source relationship is not guessed."
            )
        if role in parent_ids[child_id]:
            raise PhenopacketExportError(
                "Pedigree has multiple recorded parents of the same sex for one child; "
                "GA4GH Pedigree cannot represent this unambiguously."
            )
        parent_ids[child_id][role] = _member_id(parent)

    persons = []
    family_id = _case_id(case)
    for member in members:
        sex = str(_value(member, "sex") or "").upper()
        affected = str(_value(member, "affected_status", "UNKNOWN") or "UNKNOWN").upper()
        if affected not in _AFFECTED_VALUES:
            raise PhenopacketExportError(f"Unsupported affected status for pedigree member {_member_id(member)}.")
        # GA4GH Pedigree.Person requires both parent identifiers. The
        # Phenopacket specification uses "0" for a founder whose parent is
        # not represented in this pedigree; this is not a sex/role inference.
        person: dict[str, Any] = {
            "familyId": family_id,
            "individualId": _member_id(member),
            "paternalId": "0",
            "maternalId": "0",
            "affectedStatus": _AFFECTED_VALUES[affected],
        }
        if sex in _SEX_NUMBERS:
            person["sex"] = ("UNKNOWN_SEX", "FEMALE", "MALE", "OTHER_SEX")[_SEX_NUMBERS[sex]]
        person.update(parent_ids.get(str(_value(member, "id")), {}))
        persons.append(person)
    return {"persons": persons}


def build_phenopackets_v2(
    *,
    case: Any,
    phenotype_observations: list[Any],
    pedigree_members: list[Any] | None = None,
    pedigree_relationships: list[Any] | None = None,
    clinical_intake_revision: Any | None = None,
    allow_lossy: bool = False,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build a schema-validated Phenopacket or Family JSON document."""
    members = list(pedigree_members or [])
    relationships = list(pedigree_relationships or [])
    rows = list(phenotype_observations)
    member_ids = {str(_value(member, "id")) for member in members}
    if any(
        _value(row, "subject_member_id") is not None
        and str(_value(row, "subject_member_id")) not in member_ids
        for row in rows
    ):
        raise PhenopacketExportError("A phenotype observation references a family member outside this case.")
    warnings = _collect_loss_warnings(rows, clinical_intake_revision)
    for member in members:
        member_identifier = _member_id(member)
        raw_sex = str(_value(member, "sex") or "").upper()
        if raw_sex and _normalize_sex(raw_sex) is None:
            warnings.append({
                "observation_id": member_identifier,
                "field": "pedigree.sex",
                "reason": f"Recorded pedigree sex value {raw_sex!r} is not in the GA4GH Pedigree sex enum and is retained only in the SIRALOOM sidecar.",
            })
        if _value(member, "relationship_to_proband"):
            warnings.append({
                "observation_id": member_identifier,
                "field": "pedigree.relationship_to_proband",
                "reason": "The free-text relationship-to-proband assertion is retained in the SIRALOOM pedigree sidecar; GA4GH Pedigree only encodes paternal/maternal parentage.",
            })
        if bool(_value(member, "sampled", False)):
            warnings.append({
                "observation_id": member_identifier,
                "field": "pedigree.sampled",
                "reason": "The sampled flag is retained in the SIRALOOM pedigree sidecar and has no direct GA4GH Pedigree person field.",
            })
        if _value(member, "specimen_id"):
            warnings.append({
                "observation_id": member_identifier,
                "field": "pedigree.specimen_id",
                "reason": "The specimen linkage is retained as a SIRALOOM sidecar reference; GA4GH Biosample export requires a complete specimen record.",
            })
        member_metadata = _value(member, "metadata_json", {}) or {}
        unrepresented_member_metadata = (
            {key: value for key, value in member_metadata.items() if key != "consanguinous_parents"}
            if isinstance(member_metadata, dict) else member_metadata
        )
        if unrepresented_member_metadata:
            warnings.append({
                "observation_id": member_identifier,
                "field": "pedigree.member_metadata",
                "reason": "Local pedigree member metadata beyond the explicitly mapped consanguinity assertion is retained in the SIRALOOM sidecar and is not interpreted as GA4GH pedigree semantics.",
            })
    for relationship in relationships:
        relationship_metadata = _value(relationship, "metadata_json", {}) or {}
        unrepresented_relationship_metadata = (
            {
                key: value
                for key, value in relationship_metadata.items()
                if key != "consanguinous_parents"
            }
            if isinstance(relationship_metadata, dict) else relationship_metadata
        )
        if unrepresented_relationship_metadata:
            warnings.append({
                "observation_id": "pedigree-relationship",
                "field": "pedigree.relationship_metadata",
                "reason": "Local pedigree relationship metadata beyond the explicitly mapped consanguinity assertion is retained in the SIRALOOM sidecar and is not interpreted as GA4GH parentage semantics.",
            })
    releases = {
        str(resource["ontology_release"])
        for row in rows
        if isinstance((resource := (_value(row, "ontology_resolution", {}) or {}).get("resource")), dict)
        and resource.get("ontology_release")
    }
    if len(releases) > 1:
        warnings.append({
            "observation_id": "case",
            "field": "ontology_provenance",
            "reason": "The case contains observations resolved against multiple HPO releases; one Phenopacket metadata resource cannot preserve per-observation release identity.",
        })
    intake_context = _value(clinical_intake_revision, "context", {}) or {}
    probands = [member for member in members if bool(_value(member, "is_proband", False))]
    if len(probands) > 1:
        raise PhenopacketExportError("A case with multiple designated probands cannot be exported as one Family.")
    if members and len(probands) != 1:
        raise PhenopacketExportError(
            "A family export requires exactly one explicitly designated proband; no proband is inferred."
        )

    if not members:
        case_rows = [row for row in rows if _value(row, "subject_member_id") is None]
        if warnings and not allow_lossy:
            fields = sorted({item["field"] for item in warnings})
            raise PhenopacketExportError(
                "Strict Phenopackets export would lose clinical semantics in: " + ", ".join(fields)
                + ". Re-run with allow_lossy=true only after reviewing the warnings."
            )
        packet = _packet(
            packet_id=f"{_case_id(case)}:phenopacket",
            subject_id=_case_id(case),
            rows=case_rows,
        )
        return _validate_message(packet, family=False), warnings

    proband = probands[0]
    proband_rows = [
        row for row in rows
        if _value(row, "subject_member_id") is None
        or str(_value(row, "subject_member_id")) == str(_value(proband, "id"))
    ]
    proband_packet = _packet(
        packet_id=f"{_case_id(case)}:proband",
        subject_id=_member_id(proband),
        rows=proband_rows,
        sex=_value(proband, "sex"),
    )
    relative_packets = []
    for member in members:
        if str(_value(member, "id")) == str(_value(proband, "id")):
            continue
        member_rows = [
            row for row in rows
            if str(_value(row, "subject_member_id")) == str(_value(member, "id"))
        ]
        if member_rows:
            relative_packets.append(
                _packet(
                    packet_id=f"{_member_id(member)}:relative",
                    subject_id=_member_id(member),
                    rows=member_rows,
                    sex=_value(member, "sex"),
                )
            )

    consanguinous_parents = _explicit_consanguinous_parents(
        case=case,
        members=members,
        relationships=relationships,
        clinical_intake_revision=clinical_intake_revision,
    )
    if consanguinous_parents is None:
        warnings.append({
            "observation_id": "pedigree",
            "field": "pedigree.consanguinous_parents",
            "reason": "The GA4GH Family boolean cannot distinguish unknown/not-recorded from false; an explicit boolean is required for strict export.",
        })
    family = {
        "id": f"{_case_id(case)}:family",
        "proband": proband_packet,
        "relatives": relative_packets,
        "pedigree": _family_pedigree(case=case, members=members, relationships=relationships),
        "metaData": _metadata(rows),
    }
    if consanguinous_parents is not None:
        family["consanguinousParents"] = consanguinous_parents
    if warnings and not allow_lossy:
        fields = sorted({item["field"] for item in warnings})
        raise PhenopacketExportError(
            "Strict Phenopackets export would lose clinical semantics in: " + ", ".join(fields)
            + ". Re-run with allow_lossy=true only after reviewing the warnings."
        )
    return _validate_message(family, family=True), warnings


def _validate_message(payload: dict[str, Any], *, family: bool) -> dict[str, Any]:
    """Validate using the official GA4GH-generated Protobuf descriptors."""
    try:
        from google.protobuf.json_format import MessageToDict, ParseDict
        import phenopackets.schema.v2 as pps2
    except ImportError as exc:
        raise RuntimeError(
            "GA4GH Phenopackets v2 export requires the pinned 'phenopackets' runtime dependency."
        ) from exc

    message_type = pps2.Family if family else pps2.Phenopacket
    try:
        message = ParseDict(payload, message_type())
    except Exception as exc:
        raise PhenopacketExportError(f"GA4GH Phenopackets v2 protobuf validation failed: {exc}") from exc
    if not message.id or not message.meta_data.created_by or not message.meta_data.phenopacket_schema_version:
        raise PhenopacketExportError("GA4GH Phenopackets v2 required id/metadata fields are missing.")
    if family and (not message.proband.id or not message.pedigree.persons):
        raise PhenopacketExportError("GA4GH Family requires a proband and pedigree persons.")
    if not family and not message.subject.id:
        raise PhenopacketExportError("GA4GH Phenopacket requires a subject identifier.")
    return MessageToDict(message, preserving_proto_field_name=False)
