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
    print("PASS: canonical version applicability, implementation mappings, test counts, and review states are preserved")
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
    print("NOTE: this validator checks reconciliation integrity, not scientific correctness or laboratory qualification.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
