#!/usr/bin/env python3
"""Formal JSON Schema 2020-12 validation for VCF research candidate registries."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = ROOT / "docs/scientific/vcf-conformance/atomic-requirement-ledger.schema.json"
REGISTRIES = (
    (
        "VCFv4.5 supplemental candidate registry",
        ROOT / "docs/scientific/vcf-conformance/VCF45_ATOMIC_CANDIDATE_REGISTRY_PASS1_2026-11-07.json",
    ),
    (
        "VCFv4.5 cardinality/local-allele addendum",
        ROOT / "docs/scientific/vcf-conformance/vcf4.5-cardinality-local-allele-atomic-addendum.v1.json",
    ),
)


def main() -> int:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    total_records = 0
    failures = 0
    print("PASS: schema is valid JSON Schema Draft 2020-12")

    for label, path in REGISTRIES:
        registry = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(
            validator.iter_errors(registry),
            key=lambda error: (list(map(str, error.absolute_path)), error.message),
        )
        if errors:
            failures += len(errors)
            print(f"FAIL: {label}: {len(errors)} JSON Schema 2020-12 validation error(s)")
            for error in errors:
                pointer = "/" + "/".join(
                    str(part).replace("~", "~0").replace("/", "~1")
                    for part in error.absolute_path
                )
                print(f"{pointer or '/'}: {error.message}")
            continue

        record_count = len(registry.get("requirements", []))
        total_records += record_count
        print(f"PASS: {label} validates against the canonical ledger schema")
        print(f"Validated records: {record_count}")
        print(f"Registry: {path.relative_to(ROOT)}")

    if failures:
        print(f"FAIL: {failures} total JSON Schema validation error(s)")
        return 1

    print(f"PASS: all research registries validated ({total_records} records total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
