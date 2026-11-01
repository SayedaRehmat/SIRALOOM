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
    return str(_value(member, "member_identifier") or _value(member, "id"))


def _term_resolution(row: Any) -> dict[str, Any]:
    resolution = _value(row, "ontology_resolution", {}) or {}
    primary = resolution.get("primary_term") if isinstance(resolution, dict) else None
    return primary if isinstance(primary, dict) else {}


def _canonical_or_submitted(row: Any) -> str:
    primary = _term_resolution(row)
    if primary.get("status") in {"CURRENT", "ALTERNATE_ID"} and primary.get("canonical_id"):
        return str(primary["canonical_id"])
    return str(_value(row, "hpo_id"))


def _collect_loss_warnings(rows: list[Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for row in rows:
        status = str(_value(row, "phenotype_status", "PRESENT")).upper()
        observation_id = str(_value(row, "id"))
        if status in {"UNKNOWN", "NOT_ASSESSED"}:
            warnings.append({
                "observation_id": observation_id,
                "field": "phenotype_status",
                "reason": f"GA4GH Phenopackets v2 cannot preserve the SIRALOOM {status} state distinctly.",
            })
        elif status == "EXCLUDED":
            warnings.append({
                "observation_id": observation_id,
                "field": "phenotype_status",
                "reason": "Phenopackets v2 excluded=true cannot distinguish SIRALOOM EXCLUDED from ABSENT.",
            })
        attributes = _value(row, "clinical_attributes", {}) or {}
        for field in ("laterality", "anatomical_site", "temporal_pattern", "episode_frequency"):
            if attributes.get(field) is not None:
                warnings.append({
                    "observation_id": observation_id,
                    "field": field,
                    "reason": f"{field} has no semantically equivalent PhenotypicFeature v2 field.",
                })
        if _value(row, "onset") and not attributes.get("onset_age_iso8601"):
            warnings.append({
                "observation_id": observation_id,
                "field": "onset",
                "reason": "Free-text onset cannot be converted to a Phenopackets TimeElement without interpretation.",
            })
        if _value(row, "severity") and not attributes.get("severity_hpo_id"):
            warnings.append({
                "observation_id": observation_id,
                "field": "severity",
                "reason": "Free-text severity is not an ontology-coded Phenopackets severity.",
            })
        if _value(row, "evidence", {}) or {}:
            warnings.append({
                "observation_id": observation_id,
                "field": "evidence",
                "reason": "SIRALOOM evidence payload is not mapped without an explicitly supported ECO code and reference.",
            })
        resource = (_value(row, "ontology_resolution", {}) or {}).get("resource")
        if not isinstance(resource, dict) or not resource.get("ontology_release"):
            warnings.append({
                "observation_id": observation_id,
                "field": "ontology_provenance",
                "reason": "No pinned HPO release is recorded; the submitted HPO identifier is exported without a release claim.",
            })
    return warnings


def _phenotypic_feature(row: Any) -> dict[str, Any]:
    attributes = _value(row, "clinical_attributes", {}) or {}
    feature: dict[str, Any] = {
        "type": {"id": _canonical_or_submitted(row)},
        "excluded": str(_value(row, "phenotype_status", "PRESENT")).upper() in {"ABSENT", "EXCLUDED"},
    }
    label = _value(row, "label")
    if label:
        feature["description"] = str(label)

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
        resource["version"] = next(iter(releases))
    return {
        "created": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "createdBy": "SIRALOOM",
        "submittedBy": "SIRALOOM",
        "resources": [resource],
        "phenopacketSchemaVersion": _SCHEMA_VERSION,
    }


def _packet(*, packet_id: str, subject_id: str, rows: list[Any], sex: str | None = None) -> dict[str, Any]:
    subject: dict[str, Any] = {"id": subject_id}
    normalized_sex = str(sex or "").upper()
    if normalized_sex in _SEX_VALUES:
        subject["sex"] = normalized_sex
    return {
        "id": packet_id,
        "subject": subject,
        "phenotypicFeatures": [_phenotypic_feature(row) for row in rows],
        "metaData": _metadata(rows),
    }


def _family_pedigree(*, case: Any, members: list[Any], relationships: list[Any]) -> dict[str, Any]:
    by_id = {str(_value(member, "id")): member for member in members}
    parent_ids: dict[str, dict[str, str]] = defaultdict(dict)
    for relationship in relationships:
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
    family_id = str(_value(case, "case_identifier") or _value(case, "id"))
    for member in members:
        sex = str(_value(member, "sex") or "").upper()
        affected = str(_value(member, "affected_status", "UNKNOWN") or "UNKNOWN").upper()
        if affected not in _AFFECTED_VALUES:
            raise PhenopacketExportError(f"Unsupported affected status for pedigree member {_member_id(member)}.")
        person: dict[str, Any] = {
            "familyId": family_id,
            "individualId": _member_id(member),
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
    warnings = _collect_loss_warnings(rows)
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
    if warnings and not allow_lossy:
        fields = sorted({item["field"] for item in warnings})
        raise PhenopacketExportError(
            "Strict Phenopackets export would lose clinical semantics in: " + ", ".join(fields)
            + ". Re-run with allow_lossy=true only after reviewing the warnings."
        )

    probands = [member for member in members if bool(_value(member, "is_proband", False))]
    if len(probands) > 1:
        raise PhenopacketExportError("A case with multiple designated probands cannot be exported as one Family.")
    if members and len(probands) != 1:
        raise PhenopacketExportError(
            "A family export requires exactly one explicitly designated proband; no proband is inferred."
        )

    if not members:
        case_rows = [row for row in rows if _value(row, "subject_member_id") is None]
        packet = _packet(
            packet_id=f"SIRALOOM:{_value(case, 'id')}",
            subject_id=f"SIRALOOM:{_value(case, 'id')}",
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
        packet_id=f"SIRALOOM:{_value(case, 'id')}:proband",
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
                    packet_id=f"SIRALOOM:{_value(case, 'id')}:{_member_id(member)}",
                    subject_id=_member_id(member),
                    rows=member_rows,
                    sex=_value(member, "sex"),
                )
            )

    family = {
        "id": f"SIRALOOM:{_value(case, 'id')}:family",
        "proband": proband_packet,
        "relatives": relative_packets,
        "pedigree": _family_pedigree(case=case, members=members, relationships=relationships),
        "metaData": _metadata(rows),
    }
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
