#!/usr/bin/env python3
"""Print the measured runtime manifest for a laboratory-controlled validation record."""
from __future__ import annotations

import argparse
import json

from backend.app.domain.runtime_attestation import (
    collect_runtime_component_manifest,
    runtime_manifest_sha256,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the current worker runtime for a laboratory validation record."
    )
    parser.add_argument(
        "--workflow-version",
        required=True,
        help="Exact workflow version being validated by the laboratory.",
    )
    args = parser.parse_args()
    components = collect_runtime_component_manifest(
        workflow_version=args.workflow_version
    )
    print(json.dumps({
        "schema_version": "1",
        "components": components,
        "manifest_sha256": runtime_manifest_sha256(components),
    }, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
