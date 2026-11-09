#!/usr/bin/env python3
"""Validate the Phase 1 germline VCF profile overlay against the canonical ledger."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "docs/scientific/vcf-conformance"
SCHEMA_PATH = BASE / "germline-small-variant-vcf-profile-reconciliation.schema.json"
PROFILE_PATH = BASE / "GERMLINE_SMALL_VARIANT_VCF_PROFILE_RECONCILIATION_2026-11-09.json"
LEDGER_PATH = BASE / "atomic-requirements.v1.json"
SOURCE_GAP_REGISTER_PATH = BASE / "VCF45_SOURCE_TO_LEDGER_GAP_REGISTER_2026-11-07.json"
ADJUDICATION_SCHEMA_PATH = BASE / "vcf45-source-candidate-adjudication.schema.json"
ADJUDICATION_PATH = BASE / "VCF45_SOURCE_CANDIDATE_ADJUDICATION_PHASE1_2026-11-09.json"
VCF45_SOURCE_PATH = BASE / "sources/hts-specs-510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex"
PROFILES = ("GERMLINE_VARIANT_VCF", "GERMLINE_GVCF")
DISPOSITIONS = {
    "CORE_REQUIRED",
    "CONDITIONAL_INPUT",
    "OUT_OF_SCOPE_EXPLICIT_REJECTION",
    "DESCRIPTIVE_RESERVED",
    "NOT_APPLICABLE",
}


def git_blob_sha1(raw: bytes) -> str:
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def fail(message: str) -> None:
    raise ValueError(message)


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(profile),
        key=lambda error: (list(map(str, error.absolute_path)), error.message),
    )
    if errors:
        for error in errors:
            pointer = "/" + "/".join(
                str(part).replace("~", "~0").replace("/", "~1")
                for part in error.absolute_path
            )
            print(f"FAIL: {pointer or '/'}: {error.message}")
        return 1
    print("PASS: profile artifact validates against JSON Schema Draft 2020-12")

    ledger_raw = LEDGER_PATH.read_bytes()
    actual_blob = git_blob_sha1(ledger_raw)
    expected_blob = profile["canonical_ledger"]["blob_sha"]
    if actual_blob != expected_blob:
        fail(f"canonical ledger blob mismatch: expected {expected_blob}, got {actual_blob}")
    ledger = json.loads(ledger_raw)
    canonical = {item["requirement_id"]: item for item in ledger["requirements"]}
    overlay_items = profile["requirement_dispositions"]
    overlay = {item["requirement_id"]: item for item in overlay_items}

    if len(canonical) != 226 or len(overlay_items) != 226 or len(overlay) != 226:
        fail(
            "requirement count/uniqueness failure: "
            f"canonical={len(canonical)}, overlay_records={len(overlay_items)}, "
            f"overlay_unique={len(overlay)}"
        )
    if set(canonical) != set(overlay):
        missing = sorted(set(canonical) - set(overlay))
        extra = sorted(set(overlay) - set(canonical))
        fail(f"requirement ID mismatch; missing={missing}; extra={extra}")
    print("PASS: all 226 canonical requirement IDs occur exactly once in the overlay")

    observed_counts = {name: Counter() for name in PROFILES}
    for requirement_id, source in canonical.items():
        item = overlay[requirement_id]
        if item["title"] != source["title"]:
            fail(f"{requirement_id}: title differs from canonical ledger")
        if item["source_applicability"] != {
            version: applicability["status"]
            for version, applicability in source["version_applicability"].items()
        }:
            fail(f"{requirement_id}: version applicability differs from canonical ledger")
        evidence = item["evidence_snapshot"]
        if evidence["implementation_status"] != source["implementation"]["status"]:
            fail(f"{requirement_id}: implementation status was altered")
        if evidence["code_symbols"] != source["implementation"]["code_symbols"]:
            fail(f"{requirement_id}: code-symbol mapping was altered")
        if evidence["review_status"] != source["review"]["status"]:
            fail(f"{requirement_id}: review status was altered")
        expected_tests = [
            {
                "test_id": test["test_id"],
                "test_kind": test["test_kind"],
                "execution_status": test["execution_status"],
                "execution_commit": test.get("execution_commit"),
                "evidence_uri": test.get("evidence_uri"),
            }
            for test in source["tests"]
        ]
        if evidence["tests"] != expected_tests:
            fail(f"{requirement_id}: test evidence was altered")
        if evidence["implementation_commit"] != source["implementation"]["implementation_commit"]:
            fail(f"{requirement_id}: implementation commit was altered")
        if evidence["second_review_status"] != source["review"]["second_review_status"]:
            fail(f"{requirement_id}: second-review status was altered")
        if evidence["independent_review_required"] != source["review"]["independent_second_review_required"]:
            fail(f"{requirement_id}: independent-review requirement was altered")
        expected_evidence_status = (
            "FAIL" if any(test["execution_status"] == "FAIL" for test in source["tests"])
            else "PASS" if source["implementation"]["code_symbols"]
            and any(test["execution_status"] == "PASS" for test in source["tests"])
            else "UNRESOLVED"
        )
        if evidence["evidence_status"] != expected_evidence_status:
            fail(f"{requirement_id}: evidence status was upgraded or downgraded")
        for profile_id in PROFILES:
            disposition = item["profile_dispositions"][profile_id]["scope_disposition"]
            if disposition not in DISPOSITIONS:
                fail(f"{requirement_id}: invalid {profile_id} disposition {disposition}")
            observed_counts[profile_id][disposition] += 1
        if item["future_retention"]["retain"] is not True:
            fail(f"{requirement_id}: future requirement retention is false")

    expected_counts = profile["requirement_disposition_counts"]
    for profile_id in PROFILES:
        observed = dict(observed_counts[profile_id])
        expected = expected_counts[profile_id]
        if observed != expected:
            fail(f"{profile_id}: disposition counts differ; observed={observed}, expected={expected}")
    print("PASS: two-profile dispositions and aggregate counts are internally consistent")
    print("PASS: canonical version applicability, implementation mappings, exact test evidence, and review states are preserved")
    print("PASS: every canonical requirement is retained for Phase 1 or a future workstream")

    gap_ids = [item["gap_id"] for item in profile["source_gap_candidates"]]
    if len(gap_ids) != len(set(gap_ids)):
        fail("source gap candidate IDs are not unique")
    for workstream in profile["preserved_future_workstreams"]:
        unknown = sorted(set(workstream["requirement_ids"]) - set(canonical))
        if unknown:
            fail(f"{workstream['workstream']}: unknown requirement IDs {unknown}")
    print(
        "PASS: source-gap IDs are unique and future workstream references resolve "
        f"({len(profile['source_gap_candidates'])} gaps; "
        f"{len(profile['preserved_future_workstreams'])} workstreams)"
    )

    gap_register_raw = SOURCE_GAP_REGISTER_PATH.read_bytes()
    gap_register_sha = git_blob_sha1(gap_register_raw)
    gap_register = json.loads(gap_register_raw)
    reconciliation = profile["source_gap_register_reconciliation"]
    if gap_register_sha != reconciliation["source_gap_register_blob_sha"]:
        fail(
            "source-gap register blob mismatch: "
            f"expected {reconciliation['source_gap_register_blob_sha']}, got {gap_register_sha}"
        )
    if gap_register["input_artifacts"]["canonical_ledger_blob_sha"] != reconciliation["historical_canonical_ledger_blob_sha"]:
        fail("historical source-gap register ledger hash does not match its recorded input")
    if reconciliation["current_canonical_ledger_blob_sha"] != actual_blob:
        fail("source-gap recheck is not bound to the current canonical ledger blob")

    source_candidates = {item["candidate_id"]: item for item in gap_register["gaps"]}
    triage_items = profile["source_candidate_profile_triage"]
    triage = {item["candidate_id"]: item for item in triage_items}
    if len(source_candidates) != 94 or len(triage_items) != 94 or len(triage) != 94:
        fail(
            "source candidate count/uniqueness failure: "
            f"source={len(source_candidates)}, triage_records={len(triage_items)}, "
            f"triage_unique={len(triage)}"
        )
    if set(source_candidates) != set(triage):
        fail("source candidate IDs do not match the source-gap register")
    exact_overlaps = 0
    candidate_counts = {name: Counter() for name in PROFILES}
    for candidate_id, source_candidate in source_candidates.items():
        item = triage[candidate_id]
        for key, source_key in (
            ("source_line", "source_line"),
            ("source_text", "source_text"),
            ("source_context", "source_context"),
            ("original_primary_disposition", "primary_disposition"),
            ("original_traceability_disposition", "traceability_disposition"),
            ("source_current_requirement_ids", "current_requirement_ids"),
        ):
            if item[key] != source_candidate[source_key]:
                fail(f"{candidate_id}: source candidate content differs from its register")
        line = source_candidate["source_line"]
        has_overlap = any(
            reference.get("source_file") == "VCFv4.5.tex"
            and reference.get("locator", {}).get("start_line") is not None
            and reference.get("locator", {}).get("end_line") is not None
            and reference["locator"]["start_line"] <= line <= reference["locator"]["end_line"]
            for requirement in ledger["requirements"]
            for reference in requirement.get("source_references", [])
        )
        if has_overlap:
            exact_overlaps += 1
        if item["future_retention"]["retain"] is not True:
            fail(f"{candidate_id}: source candidate retention is false")
        for profile_id in PROFILES:
            disposition = item["profile_dispositions"][profile_id]["scope_disposition"]
            if disposition not in DISPOSITIONS:
                fail(f"{candidate_id}: invalid {profile_id} source-candidate disposition")
            candidate_counts[profile_id][disposition] += 1

    expected_recheck = reconciliation["exact_locator_recheck_against_current_ledger"]
    if expected_recheck["candidate_lines"] != 94:
        fail("source-gap register candidate-line count is not 94")
    if expected_recheck["exact_locator_overlap"] != exact_overlaps:
        fail(
            "source-gap exact-locator overlap count mismatch: "
            f"expected {expected_recheck['exact_locator_overlap']}, got {exact_overlaps}"
        )
    if expected_recheck["no_exact_locator_overlap"] != 94 - exact_overlaps:
        fail("source-gap no-overlap count is inconsistent")
    for profile_id in PROFILES:
        if dict(candidate_counts[profile_id]) != reconciliation["candidate_disposition_counts"][profile_id]:
            fail(f"{profile_id}: source-candidate disposition counts differ")
    if reconciliation["original_register_counts"] != gap_register["counts"]:
        fail("source-gap register summary counts differ from the source artifact")
    print(
        "PASS: all 94 source-gap candidates are mapped to both profiles and checked against "
        f"the current ledger ({exact_overlaps} exact locator overlaps)"
    )
    adjudication_raw = ADJUDICATION_PATH.read_bytes()
    adjudication_blob = git_blob_sha1(adjudication_raw)
    expected_adjudication_blob = profile["source_candidate_semantic_adjudication"]["artifact_blob_sha"]
    if adjudication_blob != expected_adjudication_blob:
        fail(
            "profile-to-adjudication artifact blob mismatch: "
            f"expected {expected_adjudication_blob}, got {adjudication_blob}"
        )
    adjudication_schema = json.loads(ADJUDICATION_SCHEMA_PATH.read_text(encoding="utf-8"))
    adjudication = json.loads(ADJUDICATION_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(adjudication_schema)
    schema_errors = sorted(
        Draft202012Validator(adjudication_schema).iter_errors(adjudication),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        first = schema_errors[0]
        fail(
            "source-candidate adjudication schema validation failed at "
            f"{list(first.absolute_path)}: {first.message}"
        )

    vcf45_raw = VCF45_SOURCE_PATH.read_bytes()
    vcf45_sha = hashlib.sha256(vcf45_raw).hexdigest()
    if vcf45_sha != adjudication["source"]["sha256"]:
        fail(
            "pinned VCFv4.5 source SHA-256 mismatch: "
            f"expected {adjudication['source']['sha256']}, got {vcf45_sha}"
        )
    if git_blob_sha1(vcf45_raw) != adjudication["source"]["git_blob_sha1"]:
        fail("pinned VCFv4.5 source Git blob identity mismatch")

    adjudication_register = {
        item["candidate_id"]: item
        for item in gap_register["gaps"]
        if item["traceability_disposition"]
        in {"POTENTIAL_NORMATIVE_OR_MIXED_OBLIGATION", "AMBIGUOUS_SCOPE"}
    }
    adjudicated = {item["candidate_id"]: item for item in adjudication["records"]}
    if len(adjudication_register) != 51 or len(adjudicated) != 51:
        fail(
            "source-candidate adjudication must cover exactly 51 candidates "
            f"(register={len(adjudication_register)}, adjudicated={len(adjudicated)})"
        )
    if set(adjudication_register) != set(adjudicated):
        fail("source-candidate adjudication IDs differ from the 50+1 source register set")

    source_lines = vcf45_raw.decode("utf-8").splitlines()
    canonical_ids = set(canonical)
    proposal_ids = []
    decision_counts = Counter()
    proposal_count = 0
    direct_mapping_edges = 0
    related_mapping_edges = 0
    for candidate_id, source_candidate in adjudication_register.items():
        item = adjudicated[candidate_id]
        line_number = source_candidate["source_line"]
        if item["source_line"] != line_number:
            fail(f"{candidate_id}: source line number mismatch")
        if item["source_excerpt"] != source_lines[line_number - 1]:
            fail(f"{candidate_id}: source excerpt differs from pinned VCFv4.5 source")
        context = item["source_context"]
        if context["start_line"] != max(1, line_number - 3):
            fail(f"{candidate_id}: context start is not the expected three-line window")
        if context["end_line"] != min(len(source_lines), line_number + 3):
            fail(f"{candidate_id}: context end is not the expected three-line window")
        expected_context = source_lines[context["start_line"] - 1:context["end_line"]]
        observed_context = [entry["text"] for entry in context["lines"]]
        if observed_context != expected_context:
            fail(f"{candidate_id}: surrounding source context differs from pinned source")
        if item["original_register_classification"]["traceability_disposition"] != source_candidate["traceability_disposition"]:
            fail(f"{candidate_id}: original source classification was changed")
        if item["status"] != "AUTHOR_ADJUDICATED_PENDING_INDEPENDENT_REVIEW":
            fail(f"{candidate_id}: author adjudication status changed")
        decision_counts[item["adjudication_decision"]] += 1
        mappings = item["existing_requirement_mapping"]
        related = item["related_existing_requirement_ids"]
        if set(mappings + related) - canonical_ids:
            fail(f"{candidate_id}: mapping references unknown canonical requirement IDs")
        direct_mapping_edges += len(mappings)
        related_mapping_edges += len(related)
        for proposal in item["proposed_atomic_requirements"]:
            proposal_ids.append(proposal["proposal_id"])
            proposal_count += 1
            if proposal["review_status"] not in {
                "PROPOSED_NOT_CANONICAL",
                "PROPOSED_CANONICAL_REQUIREMENT_REFINEMENT",
            }:
                fail(f"{candidate_id}: invalid proposal review status")
            if not proposal["atomic_statement"].strip() or not proposal["observable_acceptance_condition"].strip():
                fail(f"{candidate_id}: incomplete proposed atomic requirement")
    if len(proposal_ids) != len(set(proposal_ids)):
        fail("proposed atomic requirement IDs are not unique")
    if proposal_count != adjudication["counts"]["proposed_atomic_requirement_count"]:
        fail("proposed atomic requirement count differs from adjudication summary")
    if direct_mapping_edges != adjudication["counts"]["existing_requirement_mapping_edges"]:
        fail("direct canonical mapping edge count differs from adjudication summary")
    if related_mapping_edges != adjudication["counts"]["related_existing_requirement_edges"]:
        fail("related canonical mapping edge count differs from adjudication summary")
    if dict(decision_counts) != adjudication["counts"]["decision_counts"]:
        fail("adjudication decision counts differ from adjudication summary")
    if adjudication["controls"]["canonical_ledger_modified"] is not False:
        fail("source-candidate adjudication must not mutate the canonical ledger")
    if adjudication["controls"]["production_code_modified"] is not False:
        fail("source-candidate adjudication must not claim production code changes")
    if adjudication["controls"]["existing_pso_bnd_assets_modified"] is not False:
        fail("source-candidate adjudication must preserve PSO/BND assets")
    print(
        "PASS: VCFv4.5 source-candidate adjudication schema and pinned source provenance "
        f"({len(adjudicated)} candidates; {proposal_count} proposed atomic requirements; "
        f"{direct_mapping_edges} direct and {related_mapping_edges} related canonical mapping edges)"
    )
    print(
        "NOTE: author adjudication only; semantic cross-version review, independent standards review, "
        "runtime implementation and laboratory qualification remain open."
    )
    print("NOTE: this validator checks reconciliation integrity, not scientific correctness or laboratory qualification.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
