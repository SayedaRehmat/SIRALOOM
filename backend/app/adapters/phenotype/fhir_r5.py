"""HL7 FHIR R5 export for SIRALOOM clinical phenotype records.

FHIR resources are validated with the R5 models from fhir.resources. SIRALOOM
clinical states and provenance not fully represented by base FHIR elements are
retained through documented, versioned SIRALOOM extensions. Phenotypes remain
Observations and are never promoted to Condition diagnoses.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5


class FHIRExportError(ValueError):
    """Clinical records cannot be represented safely in the FHIR R5 bundle."""


FHIR_VERSION = "5.0.0"
HPO_SYSTEM = "http://purl.obolibrary.org/obo/hp.owl"
EXTENSION_BASE = "https://siraloom.org/fhir/StructureDefinition"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _extension(url: str, value_key: str, value: Any) -> dict[str, Any]:
    return {"url": f"{EXTENSION_BASE}/{url}", value_key: value}


def _coding(system: str, code: str, display: str | None = None) -> dict[str, Any]:
    result = {"system": system, "code": code}
    if display:
        result["display"] = display
    return result


def _hpo_code(row: Any) -> tuple[str, str | None]:
    resolution = _get(row, "ontology_resolution", {}) or {}
    primary = resolution.get("primary_term") if isinstance(resolution, dict) else None
    if isinstance(primary, dict) and primary.get("status") in {"CURRENT", "ALTERNATE_ID"} and primary.get("canonical_id"):
        return str(primary["canonical_id"]), primary.get("label") or _get(row, "label")
    return str(_get(row, "hpo_id")), _get(row, "label")


def _clinical_attribute_extensions(row: Any) -> list[dict[str, Any]]:
    attributes = _get(row, "clinical_attributes", {}) or {}
    result: list[dict[str, Any]] = []
    for field, extension_name in (
        ("onset_age_iso8601", "onset-age"),
        ("resolution_age_iso8601", "resolution-age"),
        ("laterality", "laterality"),
        ("temporal_pattern", "temporal-pattern"),
    ):
        if attributes.get(field) is not None:
            result.append(_extension(extension_name, "valueString", str(attributes[field])))

    for field, extension_name in (
        ("severity_hpo_id", "severity"),
        ("clinical_course_hpo_id", "clinical-course"),
    ):
        term_id = attributes.get(field)
        if term_id:
            result.append({
                "url": f"{EXTENSION_BASE}/{extension_name}",
                "valueCodeableConcept": {"coding": [_coding(HPO_SYSTEM, str(term_id))]},
            })

    for term_id in attributes.get("modifier_hpo_ids", []) or []:
        result.append({
            "url": f"{EXTENSION_BASE}/modifier",
            "valueCodeableConcept": {"coding": [_coding(HPO_SYSTEM, str(term_id))]},
        })

    site = attributes.get("anatomical_site")
    if isinstance(site, dict) and site.get("system") and site.get("code"):
        result.append({
            "url": f"{EXTENSION_BASE}/anatomical-site",
            "valueCodeableConcept": {
                "coding": [_coding(str(site["system"]), str(site["code"]), site.get("display"))]
            },
        })

    frequency = attributes.get("episode_frequency")
    if isinstance(frequency, dict):
        children = []
        if frequency.get("count") is not None:
            children.append({"url": "count", "valueInteger": int(frequency["count"])})
        if frequency.get("period_value") is not None:
            children.append({"url": "period-value", "valueDecimal": float(frequency["period_value"])})
        if frequency.get("period_unit") is not None:
            children.append({"url": "period-unit", "valueCode": str(frequency["period_unit"])})
        if children:
            result.append({
                "url": f"{EXTENSION_BASE}/episode-frequency",
                "extension": children,
            })

    if _get(row, "onset") and not attributes.get("onset_age_iso8601"):
        result.append(_extension("source-onset-text", "valueString", str(_get(row, "onset"))))
    if _get(row, "severity") and not attributes.get("severity_hpo_id"):
        result.append(_extension("source-severity-text", "valueString", str(_get(row, "severity"))))
    return result


def _observation(row: Any, *, patient_id: str, relative_id: str | None) -> dict[str, Any]:
    status = str(_get(row, "phenotype_status", "PRESENT")).upper()
    if status not in {"PRESENT", "ABSENT", "EXCLUDED", "UNKNOWN", "NOT_ASSESSED"}:
        raise FHIRExportError(f"Unsupported phenotype status {status!r}.")

    code, display = _hpo_code(row)
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": str(_get(row, "id")),
        "identifier": [{
            "system": "https://siraloom.org/identifier/phenotype-observation",
            "value": str(_get(row, "id")),
        }],
        "status": "preliminary",
        "code": {"coding": [_coding(HPO_SYSTEM, code, display)]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "extension": [
            _extension("phenotype-status", "valueCode", status),
            _extension("source", "valueString", str(_get(row, "source", "CLINICAL_INPUT"))),
        ],
    }
    if relative_id:
        resource["focus"] = [{"reference": f"RelatedPerson/{relative_id}"}]
    if status == "PRESENT":
        resource["valueBoolean"] = True
    elif status in {"ABSENT", "EXCLUDED"}:
        resource["valueBoolean"] = False
    elif status == "UNKNOWN":
        resource["dataAbsentReason"] = {
            "coding": [_coding("http://terminology.hl7.org/CodeSystem/data-absent-reason", "unknown")]
        }
    else:
        resource["dataAbsentReason"] = {
            "coding": [_coding("http://terminology.hl7.org/CodeSystem/data-absent-reason", "not-performed")]
        }

    observed_at = _iso(_get(row, "observed_at"))
    issued = _iso(_get(row, "created_at"))
    if observed_at:
        resource["effectiveDateTime"] = observed_at
    if issued:
        resource["issued"] = issued

    resource["extension"].extend(_clinical_attribute_extensions(row))
    resolution = _get(row, "ontology_resolution", {}) or {}
    primary = resolution.get("primary_term") if isinstance(resolution, dict) else None
    resource["extension"].append({
        "url": f"{EXTENSION_BASE}/ontology-resolution",
        "extension": [
            _extension("input-id", "valueString", str(_get(row, "hpo_id"))),
            *(
                [_extension("status", "valueCode", str(primary["status"]))]
                if isinstance(primary, dict) and primary.get("status") else []
            ),
            *(
                [_extension("canonical-id", "valueString", str(primary["canonical_id"]))]
                if isinstance(primary, dict) and primary.get("canonical_id") else []
            ),
        ],
    })
    if isinstance(resolution, dict) and resolution.get("resource"):
        resource["extension"].append(_extension(
            "ontology-resource-provenance",
            "valueString",
            json.dumps(resolution["resource"], sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        ))
    evidence = _get(row, "evidence", {}) or {}
    if evidence:
        resource["extension"].append(_extension(
            "source-evidence",
            "valueString",
            json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        ))
    return resource


def _validate_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from fhir.resources.bundle import Bundle
    except ImportError as exc:
        raise RuntimeError("FHIR R5 export requires the pinned fhir.resources dependency.") from exc
    try:
        bundle = Bundle.model_validate(payload)
    except Exception as exc:
        raise FHIRExportError(f"FHIR R5 Bundle validation failed: {exc}") from exc
    return bundle.model_dump(by_alias=True, exclude_none=True)


def build_fhir_r5_bundle(
    *,
    case: Any,
    phenotype_observations: list[Any],
    pedigree_members: list[Any] | None = None,
    pedigree_relationships: list[Any] | None = None,
) -> dict[str, Any]:
    """Build a FHIR R5 collection Bundle with explicit proband/family attribution."""
    members = list(pedigree_members or [])
    relationships = list(pedigree_relationships or [])
    rows = list(phenotype_observations)
    members_by_id = {str(_get(member, "id")): member for member in members}
    if any(
        _get(row, "subject_member_id") is not None
        and str(_get(row, "subject_member_id")) not in members_by_id
        for row in rows
    ):
        raise FHIRExportError("A phenotype observation references a family member outside this case.")

    probands = [member for member in members if bool(_get(member, "is_proband", False))]
    if len(probands) > 1 or (members and len(probands) != 1):
        raise FHIRExportError("FHIR family export requires exactly one explicitly designated proband.")

    proband = probands[0] if probands else None
    patient_id = str(_get(proband, "id")) if proband else str(_get(case, "id"))
    patient: dict[str, Any] = {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [{
            "system": "https://siraloom.org/identifier/case",
            "value": str(_get(case, "id")),
        }],
    }
    if proband:
        sex = str(_get(proband, "sex") or "").upper()
        if sex in {"MALE", "FEMALE", "OTHER_SEX"}:
            patient["gender"] = {"MALE": "male", "FEMALE": "female", "OTHER_SEX": "other"}[sex]

    resources: list[dict[str, Any]] = [patient]
    relative_ids: set[str] = set()
    member_references: dict[str, str] = {}
    if proband:
        member_references[patient_id] = f"Patient/{patient_id}"
        for member in members:
            if str(_get(member, "id")) == patient_id:
                continue
            relative_id = str(_get(member, "id"))
            relative_ids.add(relative_id)
            member_references[relative_id] = f"RelatedPerson/{relative_id}"
            related: dict[str, Any] = {
                "resourceType": "RelatedPerson",
                "id": relative_id,
                "patient": {"reference": f"Patient/{patient_id}"},
                "identifier": [{
                    "system": "https://siraloom.org/identifier/pedigree-member",
                    "value": str(_get(member, "member_identifier")),
                }],
                "extension": [
                    _extension("family-affected-status", "valueCode", str(_get(member, "affected_status", "UNKNOWN"))),
                    _extension("pedigree-sex", "valueCode", str(_get(member, "sex", "UNKNOWN"))),
                    _extension("sampled", "valueBoolean", bool(_get(member, "sampled", False))),
                ],
            }
            relationship = _get(member, "relationship_to_proband")
            if relationship:
                related["relationship"] = [{"text": str(relationship)}]
            if _get(member, "specimen_id"):
                related["extension"].append(
                    _extension("specimen-reference-id", "valueString", str(_get(member, "specimen_id")))
                )
            resources.append(related)
            if relationship:
                sex = str(_get(member, "sex") or "").upper()
                gender = {"MALE": "male", "FEMALE": "female", "OTHER_SEX": "other"}.get(sex, "unknown")
                resources.append({
                    "resourceType": "FamilyMemberHistory",
                    "id": relative_id,
                    "status": "partial",
                    "patient": {"reference": f"Patient/{patient_id}"},
                    "relationship": {"text": str(relationship)},
                    "sex": {
                        "coding": [_coding("http://hl7.org/fhir/administrative-gender", gender)]
                    },
                    "extension": [
                        _extension("family-affected-status", "valueCode", str(_get(member, "affected_status", "UNKNOWN")))
                    ],
                })

    # Preserve the directed parent-child graph. FHIR RelatedPerson describes
    # each relative in relation to the proband, so explicit relative-to-relative
    # links use named SIRALOOM extensions rather than being discarded.
    resources_by_member = {
        str(_get(member, "id")): (
            patient if str(_get(member, "id")) == patient_id
            else next(resource for resource in resources
                      if resource.get("resourceType") == "RelatedPerson"
                      and resource.get("id") == str(_get(member, "id")))
        )
        for member in members
    }
    for relationship in relationships:
        if str(_get(relationship, "relationship_type") or "").upper() != "PARENT_CHILD":
            raise FHIRExportError("FHIR pedigree export currently requires explicit PARENT_CHILD relationship records.")
        parent_id = str(_get(relationship, "parent_member_id"))
        child_id = str(_get(relationship, "child_member_id"))
        if parent_id not in member_references or child_id not in member_references or parent_id == child_id:
            raise FHIRExportError("Pedigree relationship references a member outside this case.")
        resources_by_member[parent_id].setdefault("extension", []).append({
            "url": f"{EXTENSION_BASE}/pedigree-child",
            "valueReference": {"reference": member_references[child_id]},
        })
        resources_by_member[child_id].setdefault("extension", []).append({
            "url": f"{EXTENSION_BASE}/pedigree-parent",
            "valueReference": {"reference": member_references[parent_id]},
        })

    for row in rows:
        subject_member_id = _get(row, "subject_member_id")
        relative_id = str(subject_member_id) if subject_member_id is not None else None
        if relative_id and relative_id not in relative_ids:
            raise FHIRExportError("A family phenotype does not resolve to an exported RelatedPerson.")
        resources.append(_observation(row, patient_id=patient_id, relative_id=relative_id))

    organization = {
        "resourceType": "Organization",
        "id": "siraloom",
        "active": True,
        "name": "SIRALOOM",
    }
    resources.append(organization)
    recorded = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for row in rows:
        observation_id = str(_get(row, "id"))
        provenance_id = str(uuid5(NAMESPACE_URL, f"siraloom:fhir-r5:export:{observation_id}"))
        resources.append({
            "resourceType": "Provenance",
            "id": provenance_id,
            "target": [{"reference": f"Observation/{observation_id}"}],
            "recorded": recorded,
            "agent": [{
                "type": {
                    "coding": [_coding(
                        "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                        "assembler",
                    )]
                },
                "who": {"reference": "Organization/siraloom"},
            }],
        })

    entries = [
        {"fullUrl": f"urn:uuid:{resource['id']}", "resource": resource}
        for resource in resources
    ]
    payload = {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": recorded,
        "entry": entries,
    }
    return _validate_bundle(payload)
