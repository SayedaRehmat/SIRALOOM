#!/usr/bin/env python3
"""Compare a parent analysis with a reanalysis in the configured SIRALOOM database.

Run inside the lab deployment using its normal DATABASE_URL and storage/resource
configuration. The parent analysis acts as the controlled baseline. A match is
reported only when both analyses have complete version/checksum-pinned resource
snapshots and identical normalized scientific-output fingerprints.
"""
from __future__ import annotations

import json
import sys
from uuid import UUID

from backend.app.domain.reproducibility import compare_reanalysis_outputs
from backend.app.infrastructure.db.session import SessionLocal


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-analysis-id", required=True, type=UUID)
    parser.add_argument("--child-analysis-id", required=True, type=UUID)
    args = parser.parse_args()

    with SessionLocal() as db:
        result = compare_reanalysis_outputs(
            db,
            parent_analysis_id=args.parent_analysis_id,
            child_analysis_id=args.child_analysis_id,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["decision"] == "MATCH":
        return 0
    if result["decision"] == "INELIGIBLE_UNPINNED_RESOURCES":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
