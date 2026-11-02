"""Execute the packaged, version-pinned VCF parser conformance corpus.

This runner executes the production validator against immutable in-package
fixtures. Caller-supplied test counts or PASS claims are never accepted as
execution evidence.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)

_CORPUS = Path(__file__).with_name("vcf_conformance_cases.json")


def execute_vcf_conformance_suite(version: str) -> dict[str, Any]:
    """Run every packaged fixture for exactly one VCF version and hash results."""
    manifest_bytes = _CORPUS.read_bytes()
    manifest = json.loads(manifest_bytes)
    parser_source = Path(__import__("inspect").getsourcefile(validate_vcf_strict) or "").resolve()
    runner_source = Path(__file__).resolve()
    parser_source_sha256 = hashlib.sha256(parser_source.read_bytes()).hexdigest()
    runner_source_sha256 = hashlib.sha256(runner_source.read_bytes()).hexdigest()
    fixtures = manifest.get("versions", {}).get(version, [])
    results: list[dict[str, Any]] = []

    if not isinstance(fixtures, list):
        fixtures = []

    with tempfile.TemporaryDirectory(prefix="siraloom-vcf-conformance-") as directory:
        root = Path(directory)
        for fixture in fixtures:
            fixture_id = str(fixture.get("id") or "")
            expected = str(fixture.get("expected") or "")
            fixture_path = root / f"{fixture_id or 'unnamed'}.vcf"
            lines = fixture.get("lines")
            if not fixture_id or not isinstance(lines, list) or not lines:
                results.append({
                    "fixture_id": fixture_id or None,
                    "expected": expected or None,
                    "observed": "INVALID_FIXTURE_DEFINITION",
                    "passed": False,
                })
                continue

            fixture_path.write_text("\n".join(str(line) for line in lines) + "\n", encoding="utf-8")
            observed = "PASS"
            try:
                profile = validate_vcf_strict(fixture_path)
                if profile.get("fileformat") != version:
                    observed = "VCF_VERSION_IDENTITY_MISMATCH"
            except StrictVCFValidationError as exc:
                observed = exc.code
            except Exception as exc:  # A parser crash is a conformance failure.
                observed = f"UNEXPECTED_{type(exc).__name__}"

            results.append({
                "fixture_id": fixture_id,
                "expected": expected,
                "observed": observed,
                "passed": observed == expected,
            })

    failed = sum(1 for item in results if not item["passed"])
    report = {
        "suite_id": str(manifest.get("suite_id") or ""),
        "suite_version": "1",
        "target_version": version,
        "corpus_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "parser_source_sha256": parser_source_sha256,
        "runner_source_sha256": runner_source_sha256,
        "python_version": sys.version,
        "platform": platform.platform(),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "test_case_count": len(results),
        "passed_test_count": len(results) - failed,
        "failed_test_count": failed,
        "execution_status": "PASSED" if results and failed == 0 else "FAILED",
        "results": results,
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    report["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report
