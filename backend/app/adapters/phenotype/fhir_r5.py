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


def _iso(value: Any, *, assume_utc: bool = False) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        if not assume_utc:
            raise FHIRExportError(
                "Cannot export a timezone-naive clinical timestamp as FHIR dateTime/instant; "
                "the source timezone must be supplied rather than inferred."
            )
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _extension(url: str, value_key: str, value: Any) -> dict[str, Any]:
    return {"url": f"{EXTENSION_BASE}/{url}", value_key: value}


def _sub_extension(url: str, value_key: str, value: Any) -> dict[str, Any]:
    """Build a child of a complex extension using its required relative URL."""
    return {"url": url, value_key: value}


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


def _explicit_consanguinous_parents(
    *,
    case: Any,
    members: list[Any],
    relationships: list[Any],
    clinical_intake_revision: Any | None,
) -> bool | None:
    sources = [_get(case, "clinical_context", {}) or {}]
    sources.extend(_get(member, "metadata_json", {}) or {} for member in members)
    sources.extend(_get(relationship, "metadata_json", {}) or {} for relationship in relationships)
    sources.append(_get(clinical_intake_revision, "context", {}) or {})
    values = []
    for source in sources:
        if isinstance(source, dict) and "consanguinous_parents" in source:
            value = source["consanguinous_parents"]
            if not isinstance(value, bool):
                raise FHIRExportError(
                    "consanguinous_parents must be an explicitly recorded boolean; string/number coercion is prohibited."
                )
            values.append(value)
    if len(set(values)) > 1:
        raise FHIRExportError("Conflicting explicit consanguinous_parents assertions exist in the case pedigree.")
    return values[0] if values else None


def _clinical_intake_extension(revision: Any | None) -> dict[str, Any] | None:
    if revision is None:
        return None
    context = _get(revision, "context", {}) or {}
    children: list[dict[str, Any]] = []
    for field, url in (
        ("revision_fingerprint", "revision-fingerprint"),
        ("intake_status", "intake-status"),
        ("phenotype_review_status", "phenotype-review-status"),
        ("family_history_review_status", "family-history-review-status"),
        ("phenotype_review_note", "phenotype-review-note"),
        ("family_history_review_note", "family-history-review-note"),
        ("completion_note", "completion-note"),
    ):
        value = _get(revision, field)
        if value is not None:
            value_type = "valueCode" if field.endswith("_status") else "valueString"
            children.append(_sub_extension(url, value_type, str(value)))
    version = _get(revision, "version")
    if version is not None:
        children.append(_sub_extension("revision-version", "valueInteger", int(version)))
    schema_version = _get(revision, "schema_version")
    if schema_version is not None:
        children.append(_sub_extension("revision-schema-version", "valueInteger", int(schema_version)))
    recorded_at = _iso(_get(revision, "recorded_at"), assume_utc=True)
    if recorded_at:
        children.append(_sub_extension("revision-recorded-at", "valueDateTime", recorded_at))

    for field in ("referral_indication", "referral_question", "clinical_summary"):
        if context.get(field):
            children.append(_sub_extension(field.replace("_", "-"), "valueString", str(context[field])))

    age = context.get("age_at_assessment")
    if isinstance(age, dict):
        age_children = []
        if age.get("value") is not None:
            age_children.append({"url": "value", "valueDecimal": float(age["value"])})
        if age.get("unit") is not None:
            age_children.append({"url": "unit", "valueCode": str(age["unit"])})
        if age.get("as_of_date") is not None:
            age_children.append({"url": "as-of-date", "valueDate": str(age["as_of_date"])})
        if age_children:
            children.append({
                "url": "age-at-assessment",
                "extension": age_children,
            })

    for item in context.get("prior_testing", []) or []:
        if not isinstance(item, dict):
            continue
        test_children = []
        for field, url, value_type in (
            ("test_type", "test-type", "valueString"),
            ("performed_at", "performed-at", "valueDate"),
            ("laboratory", "laboratory", "valueString"),
            ("accession_reference", "accession-reference", "valueString"),
            ("result_status", "result-status", "valueCode"),
            ("result_summary", "result-summary", "valueString"),
            ("source_reference", "source-reference", "valueString"),
        ):
            if item.get(field) is not None:
                test_children.append(_sub_extension(url, value_type, str(item[field])))
        if item.get("artifact_id"):
            test_children.append(_sub_extension("artifact-reference-present", "valueBoolean", True))
        if test_children:
            children.append({
                "url": "prior-testing",
                "extension": test_children,
            })

    for item in context.get("differential_diagnoses", []) or []:
        if not isinstance(item, dict):
            continue
        diagnosis_children = []
        for field, url in (
            ("system", "system"),
            ("code", "code"),
            ("display", "display"),
            ("certainty", "certainty"),
            ("clinical_status", "clinical-status"),
        ):
            if item.get(field) is not None:
                diagnosis_children.append(_sub_extension(url, "valueString", str(item[field])))
        if diagnosis_children:
            children.append({
                "url": "differential-diagnosis",
                "extension": diagnosis_children,
            })

    for reference in context.get("source_document_references", []) or []:
        children.append(_sub_extension("source-document-reference", "valueString", str(reference)))

    if not children:
        return None
    return {
        "url": f"{EXTENSION_BASE}/clinical-intake-revision",
        "extension": children,
    }


_INTERNAL_EXPORT_KEYS = {
    "case_id", "analysis_id", "member_id", "parent_member_id", "child_member_id",
    "specimen_id", "artifact_id", "user_id", "recorded_by", "created_by",
    "revision_id", "resource_id", "qualification_id", "execution_id", "provider_id",
}


def _sanitize_export_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_export_metadata(item)
            for key, item in value.items()
            if key not in _INTERNAL_EXPORT_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_export_metadata(item) for item in value]
    return value


def _safe_ontology_resolution(resolution: Any) -> Any:
    return _sanitize_export_metadata(resolution)


def _observation_resource_id(case: Any, row: Any, index: int) -> str:
    fingerprint = _get(row, "record_fingerprint")
    identity = str(fingerprint) if fingerprint else f"{index}:{_get(row, 'hpo_id')}:{_get(row, 'phenotype_status')}"
    return str(uuid5(
        NAMESPACE_URL,
        f"siraloom:fhir-r5:phenotype-observation:{_get(case, 'id')}:{identity}",
    ))


def _observation(
    row: Any,
    *,
    patient_id: str,
    relative_id: str | None,
    observation_id: str,
) -> dict[str, Any]:
    status = str(_get(row, "phenotype_status", "PRESENT")).upper()
    if status not in {"PRESENT", "ABSENT", "EXCLUDED", "UNKNOWN", "NOT_ASSESSED"}:
        raise FHIRExportError(f"Unsupported phenotype status {status!r}.")

    code, display = _hpo_code(row)
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": observation_id,
        "identifier": [{
            "system": "https://siraloom.org/identifier/phenotype-observation",
            "value": str(_get(row, "record_fingerprint") or observation_id),
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
    elif status == "ABSENT":
        resource["valueBoolean"] = False
    elif status == "EXCLUDED":
        # EXCLUDED is not a negative phenotype finding. Preserve it as an
        # explicit coded assertion rather than valueBoolean=false.
        resource["valueCodeableConcept"] = {
            "coding": [{
                "system": "https://siraloom.org/fhir/CodeSystem/phenotype-observation-status",
                "code": "EXCLUDED",
                "display": "Excluded finding",
            }]
        }
    elif status == "UNKNOWN":
        resource["dataAbsentReason"] = {
            "coding": [_coding("http://terminology.hl7.org/CodeSystem/data-absent-reason", "unknown")]
        }
    else:
        resource["dataAbsentReason"] = {
            "coding": [_coding("http://terminology.hl7.org/CodeSystem/data-absent-reason", "not-asked")]
        }

    observed_at = _iso(_get(row, "observed_at"))
    issued = _iso(_get(row, "created_at"), assume_utc=True)
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
            _sub_extension("input-id", "valueString", str(_get(row, "hpo_id"))),
            *(
                [_sub_extension("status", "valueCode", str(primary["status"]))]
                if isinstance(primary, dict) and primary.get("status") else []
            ),
            *(
                [_sub_extension("canonical-id", "valueString", str(primary["canonical_id"]))]
                if isinstance(primary, dict) and primary.get("canonical_id") else []
            ),
        ],
    })
    resource["extension"].append(_extension(
        "ontology-resolution-detail",
        "valueString",
        json.dumps(_safe_ontology_resolution(resolution), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    ))
    if _get(row, "record_fingerprint"):
        resource["extension"].append(
            _extension("record-fingerprint", "valueString", str(_get(row, "record_fingerprint")))
        )
    if isinstance(resolution, dict) and resolution.get("resource"):
        resource["extension"].append(_extension(
            "ontology-resource-provenance",
            "valueString",
            json.dumps(_safe_ontology_resolution({"resource": resolution["resource"]})["resource"], sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        ))
    evidence = _get(row, "evidence", {}) or {}
    if evidence:
        resource["extension"].append(_extension(
            "source-evidence",
            "valueString",
            json.dumps(_sanitize_export_metadata(evidence), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        ))
    return resource


def _validate_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entry", [])
    full_urls = [entry.get("fullUrl") for entry in entries]
    if len(full_urls) != len(set(full_urls)):
        raise FHIRExportError("FHIR Bundle contains duplicate fullUrl values.")
    resource_full_urls = {
        f"{entry['resource']['resourceType']}/{entry['resource']['id']}": entry["fullUrl"]
        for entry in entries
    }
    if len(resource_full_urls) != len(entries):
        raise FHIRExportError("FHIR Bundle contains duplicate resource type/id identities.")
    full_url_set = set(full_urls)
    internal_resource_types = {
        "Patient", "RelatedPerson", "FamilyMemberHistory", "Observation",
        "Provenance", "Organization", "CodeSystem",
    }

    def normalize_and_validate_references(value: Any) -> None:
        if isinstance(value, dict):
            reference = value.get("reference")
            if isinstance(reference, str):
                if reference in resource_full_urls:
                    # A collection Bundle with urn:uuid fullUrls must use those
                    # identities for intra-Bundle references. Relative
                    # ResourceType/id references cannot be resolved from a URN.
                    value["reference"] = resource_full_urls[reference]
                elif reference.startswith("urn:uuid:") and reference not in full_url_set:
                    raise FHIRExportError(
                        f"FHIR Bundle contains an unresolved UUID reference: {reference}"
                    )
                elif "/" in reference and reference.split("/", 1)[0] in internal_resource_types:
                    raise FHIRExportError(
                        f"FHIR Bundle contains an unresolved internal reference: {reference}"
                    )
            for nested in value.values():
                normalize_and_validate_references(nested)
        elif isinstance(value, list):
            for nested in value:
                normalize_and_validate_references(nested)

    normalize_and_validate_references(entries)
    try:
        from fhir.resources.bundle import Bundle
    except ImportError as exc:
        raise RuntimeError("FHIR R5 export requires the pinned fhir.resources dependency.") from exc
    try:
        bundle = Bundle.model_validate(payload)
    except Exception as exc:
        raise FHIRExportError(f"FHIR R5 Bundle validation failed: {exc}") from exc
    return bundle.model_dump(mode="json", by_alias=True, exclude_none=True)


def build_fhir_r5_bundle(
    *,
    case: Any,
    phenotype_observations: list[Any],
    pedigree_members: list[Any] | None = None,
    pedigree_relationships: list[Any] | None = None,
    clinical_intake_revision: Any | None = None,
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
    patient_seed = (
        f"proband:{_get(case, 'id')}:{_get(proband, 'id')}"
        if proband else f"case:{_get(case, 'id')}"
    )
    patient_id = str(uuid5(NAMESPACE_URL, f"siraloom:fhir-r5:patient:{patient_seed}"))
    proband_member_id = str(_get(proband, "id")) if proband else None
    related_person_ids = {
        str(_get(member, "id")): str(uuid5(
            NAMESPACE_URL,
            f"siraloom:fhir-r5:related-person:{_get(case, 'id')}:{_get(member, 'id')}",
        ))
        for member in members
        if proband and str(_get(member, "id")) != proband_member_id
    }
    patient: dict[str, Any] = {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [{
            "system": "https://siraloom.org/identifier/case-pseudonym",
            "value": patient_id,
        }],
    }
    if proband:
        sex = str(_get(proband, "sex") or "").upper()
        patient["extension"] = [
            _extension("family-affected-status", "valueCode", str(_get(proband, "affected_status", "UNKNOWN"))),
            _extension("pedigree-sex", "valueCode", sex or "UNKNOWN"),
            _extension("sampled", "valueBoolean", bool(_get(proband, "sampled", False))),
        ]
        if _get(proband, "specimen_id"):
            patient["extension"].append(
                _extension("specimen-reference-present", "valueBoolean", True)
            )
        if _get(proband, "metadata_json", {}) or {}:
            patient["extension"].append(_extension(
                "pedigree-member-metadata",
                "valueString",
                json.dumps(_sanitize_export_metadata(_get(proband, "metadata_json", {})), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            ))

    intake_extension = _clinical_intake_extension(clinical_intake_revision)
    if intake_extension is not None:
        patient.setdefault("extension", []).append(intake_extension)
    if members:
        consanguinous_parents = _explicit_consanguinous_parents(
            case=case,
            members=members,
            relationships=relationships,
            clinical_intake_revision=clinical_intake_revision,
        )
        consanguinity_children = [
            _sub_extension(
                "status",
                "valueCode",
                "CONSANGUINOUS" if consanguinous_parents is True
                else "NOT_CONSANGUINOUS" if consanguinous_parents is False
                else "NOT_RECORDED",
            )
        ]
        if consanguinous_parents is not None:
            consanguinity_children.append(
                _sub_extension("consanguinous-parents", "valueBoolean", consanguinous_parents)
            )
        patient.setdefault("extension", []).append({
            "url": f"{EXTENSION_BASE}/consanguinity-assessment",
            "extension": consanguinity_children,
        })

    resources: list[dict[str, Any]] = [patient]
    relative_ids: set[str] = set()
    member_references: dict[str, str] = {}
    if proband:
        member_references[proband_member_id] = f"Patient/{patient_id}"
        for member in members:
            if str(_get(member, "id")) == proband_member_id:
                continue
            member_key = str(_get(member, "id"))
            relative_id = related_person_ids[member_key]
            relative_ids.add(member_key)
            member_references[member_key] = f"RelatedPerson/{relative_id}"
            related: dict[str, Any] = {
                "resourceType": "RelatedPerson",
                "id": relative_id,
                "patient": {"reference": f"Patient/{patient_id}"},
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
                    _extension("specimen-reference-present", "valueBoolean", True)
                )
            if _get(member, "metadata_json", {}) or {}:
                related["extension"].append(_extension(
                    "pedigree-member-metadata",
                    "valueString",
                    json.dumps(_sanitize_export_metadata(_get(member, "metadata_json", {})), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                ))
            resources.append(related)
            if relationship:
                resources.append({
                    "resourceType": "FamilyMemberHistory",
                    "id": str(uuid5(NAMESPACE_URL, f"siraloom:fhir-r5:family-member-history:{relative_id}")),
                    "status": "partial",
                    "patient": {"reference": f"Patient/{patient_id}"},
                    "relationship": {"text": str(relationship)},
                    "extension": [
                        _extension("family-affected-status", "valueCode", str(_get(member, "affected_status", "UNKNOWN"))),
                        _extension("pedigree-sex", "valueCode", str(_get(member, "sex", "UNKNOWN"))),
                    ],
                })

    # Preserve the directed parent-child graph. FHIR RelatedPerson describes
    # each relative in relation to the proband, so explicit relative-to-relative
    # links use named SIRALOOM extensions rather than being discarded.
    resources_by_member = {
        str(_get(member, "id")): (
            patient if str(_get(member, "id")) == proband_member_id
            else next(resource for resource in resources
                      if resource.get("resourceType") == "RelatedPerson"
                      and resource.get("id") == related_person_ids[str(_get(member, "id"))])
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
        relationship_metadata = _get(relationship, "metadata_json", {}) or {}
        if relationship_metadata:
            resources_by_member[child_id].setdefault("extension", []).append({
                "url": f"{EXTENSION_BASE}/pedigree-relationship-metadata",
                "extension": [
                    _sub_extension("relationship-type", "valueCode", "PARENT_CHILD"),
                    _sub_extension("parent-member", "valueReference", {"reference": member_references[parent_id]}),
                    _sub_extension("child-member", "valueReference", {"reference": member_references[child_id]}),
                    _sub_extension(
                        "metadata",
                        "valueString",
                        json.dumps(_sanitize_export_metadata(relationship_metadata), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                    ),
                ],
            })

    observation_ids: list[str] = []
    for index, row in enumerate(rows):
        subject_member_id = _get(row, "subject_member_id")
        member_key = str(subject_member_id) if subject_member_id is not None else None
        if member_key is not None and member_key != proband_member_id and member_key not in relative_ids:
            raise FHIRExportError("A family phenotype does not resolve to an exported RelatedPerson.")
        relative_id = related_person_ids.get(member_key) if member_key is not None and member_key != proband_member_id else None
        observation_id = _observation_resource_id(case, row, index)
        observation_ids.append(observation_id)
        resources.append(_observation(
            row,
            patient_id=patient_id,
            relative_id=relative_id,
            observation_id=observation_id,
        ))

    organization_id = str(uuid5(NAMESPACE_URL, "siraloom:fhir-r5:organization"))
    organization = {
        "resourceType": "Organization",
        "id": organization_id,
        "active": True,
        "name": "SIRALOOM",
    }
    resources.append(organization)
    status_code_system_id = str(uuid5(NAMESPACE_URL, "siraloom:fhir-r5:phenotype-observation-status"))
    resources.append({
        "resourceType": "CodeSystem",
        "id": status_code_system_id,
        "url": "https://siraloom.org/fhir/CodeSystem/phenotype-observation-status",
        "version": "1.0.0",
        "name": "SIRALOOMPhenotypeObservationStatus",
        "title": "SIRALOOM Phenotype Observation Status",
        "status": "active",
        "caseSensitive": True,
        "content": "complete",
        "concept": [{
            "code": "EXCLUDED",
            "display": "Excluded finding",
            "definition": "The finding was explicitly excluded from the current phenotype assertion; this is not equivalent to an absent or not-assessed finding.",
        }],
    })
    recorded = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for observation_id in observation_ids:
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
                "who": {"reference": f"Organization/{organization_id}"},
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
