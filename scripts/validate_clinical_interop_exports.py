"""Generate deterministic synthetic clinical export fixtures for external validators.

These fixtures contain no real patient data. They exercise the production export
builders and write GA4GH Phenopacket/Family and HL7 FHIR R5 Bundle JSON.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from backend.app.adapters.phenotype.fhir_r5 import build_fhir_r5_bundle
from backend.app.adapters.phenotype.phenopackets_v2 import build_phenopackets_v2


CASE_ID = UUID("00000000-0000-4000-8000-000000000001")
FATHER_ID = UUID("00000000-0000-4000-8000-000000000002")
MOTHER_ID = UUID("00000000-0000-4000-8000-000000000003")
PROBAND_ID = UUID("00000000-0000-4000-8000-000000000004")
OBSERVATION_ID = UUID("00000000-0000-4000-8000-000000000005")
RECORDED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def fixtures() -> tuple[dict, dict, dict]:
    case = SimpleNamespace(
        id=CASE_ID,
        case_identifier="SYNTHETIC-INTEROP-CASE",
        clinical_context={"consanguinous_parents": False},
    )
    father = SimpleNamespace(
        id=FATHER_ID, member_identifier="SYNTHETIC-FATHER", sex="MALE",
        affected_status="UNAFFECTED", is_proband=False,
        relationship_to_proband=None, sampled=False, specimen_id=None,
        metadata_json={},
    )
    mother = SimpleNamespace(
        id=MOTHER_ID, member_identifier="SYNTHETIC-MOTHER", sex="FEMALE",
        affected_status="UNAFFECTED", is_proband=False,
        relationship_to_proband=None, sampled=False, specimen_id=None,
        metadata_json={},
    )
    proband = SimpleNamespace(
        id=PROBAND_ID, member_identifier="SYNTHETIC-PROBAND", sex="UNKNOWN",
        affected_status="AFFECTED", is_proband=True,
        relationship_to_proband=None, sampled=False, specimen_id=None,
        metadata_json={},
    )
    relationships = [
        SimpleNamespace(
            parent_member_id=FATHER_ID, child_member_id=PROBAND_ID,
            relationship_type="PARENT_CHILD", metadata_json={},
        ),
        SimpleNamespace(
            parent_member_id=MOTHER_ID, child_member_id=PROBAND_ID,
            relationship_type="PARENT_CHILD", metadata_json={},
        ),
    ]
    observation = SimpleNamespace(
        id=OBSERVATION_ID, case_id=CASE_ID, subject_member_id=None,
        hpo_id="HP:0001250", canonical_hpo_id="HP:0001250",
        label="Seizures", phenotype_status="PRESENT", onset=None, severity=None,
        observed_at=RECORDED_AT, created_at=RECORDED_AT,
        clinical_attributes={},
        ontology_resolution={
            "primary_term": {
                "input_id": "HP:0001250", "status": "CURRENT",
                "canonical_id": "HP:0001250", "label": "Seizures",
            },
            "related_terms": [],
            "resource": {
                "resource_id": "synthetic-hpo", "ontology_release": "2026-10-01",
                "resource_checksum": "a" * 64, "ontology_sha256": "a" * 64,
                "qualification_id": "synthetic-qualification",
                "contract_hash": "b" * 64,
            },
        },
        source="CLINICAL_INPUT", evidence={},
    )

    # GA4GH PhenotypicFeature v2 has no observation timestamp field. Keep the
    # timestamp on the FHIR source row, but do not invent a GA4GH mapping for it.
    packet_observation_data = vars(observation).copy()
    packet_observation_data["observed_at"] = None
    packet_observation = SimpleNamespace(**packet_observation_data)
    phenopacket, packet_warnings = build_phenopackets_v2(
        case=case, phenotype_observations=[packet_observation],
    )
    if packet_warnings:
        raise RuntimeError(f"Synthetic Phenopacket unexpectedly has loss warnings: {packet_warnings}")

    family, family_warnings = build_phenopackets_v2(
        case=case, phenotype_observations=[packet_observation],
        pedigree_members=[father, mother, proband],
        pedigree_relationships=relationships,
    )
    if family_warnings:
        raise RuntimeError(f"Synthetic GA4GH Family unexpectedly has loss warnings: {family_warnings}")

    bundle = build_fhir_r5_bundle(
        case=case, phenotype_observations=[observation],
        pedigree_members=[father, mother, proband],
        pedigree_relationships=relationships,
    )
    return phenopacket, family, bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    names = ("phenopacket.json", "family.json", "fhir-r5-bundle.json")
    for name, payload in zip(names, fixtures(), strict=True):
        path = args.output_dir / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
