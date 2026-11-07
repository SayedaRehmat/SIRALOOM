#!/usr/bin/env python3
"""Formal JSON Schema 2020-12 validation for the VCF research candidate registry."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = ROOT / "docs/scientific/vcf-conformance/atomic-requirement-ledger.schema.json"
REGISTRY = ROOT / "docs/scientific/vcf-conformance/VCF45_ATOMIC_CANDIDATE_REGISTRY_PASS1_2026-11-07.json"


def main() -> int:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(registry),
        key=lambda error: (list(map(str, error.absolute_path)), error.message),
    )
    if errors:
        print(f"FAIL: {len(errors)} JSON Schema 2020-12 validation error(s)")
        for error in errors:
            pointer = "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path)
            print(f"{pointer or '/'}: {error.message}")
        return 1

    print("PASS: schema is valid JSON Schema Draft 2020-12")
    print("PASS: supplemental VCFv4.5 registry validates against the canonical ledger schema")
    print(f"Validated records: {len(registry.get('requirements', []))}")
    print(f"Schema: {SCHEMA.relative_to(ROOT)}")
    print(f"Registry: {REGISTRY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
