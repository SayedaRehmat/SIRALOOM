#!/usr/bin/env python3
"""Qualify immutable public VCF examples for declared VCFv4.0-v4.5 versions.

This is parser/interoperability and routing qualification, not clinical
analytical validation. Sources are pinned to immutable Git commits and checked
against their canonical Git blob SHA-1 before execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.domain.vcf_normative_inventory import git_blob_sha1
from backend.app.domain.vcf_tools import route_vcf_records
from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict

MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "backend" / "app" / "domain" / "vcf_public_version_corpus.json"
)


def acquire(source: dict[str, Any], destination: Path) -> bytes:
    request = urllib.request.Request(
        source["url"], headers={"User-Agent": "SIRALOOM-VCF-Qualification/1.0"}
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = response.read(int(source["size_bytes"]) + 1)
    if len(payload) != int(source["size_bytes"]):
        raise ValueError(
            f"{source['id']}: expected {source['size_bytes']} bytes, received {len(payload)}"
        )
    observed_blob = git_blob_sha1(payload)
    if observed_blob != source["git_blob_sha1"]:
        raise ValueError(
            f"{source['id']}: Git blob mismatch; expected {source['git_blob_sha1']}, "
            f"observed {observed_blob}"
        )
    destination.write_bytes(payload)
    return payload


def run_bcftools(executable: str, source_path: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                executable, "view", "--no-version", "--output-type", "v",
                "--output", os.devnull, str(source_path),
            ],
            capture_output=True, text=True, timeout=180, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {"status": "TIMEOUT", "timeout_seconds": 180, "stderr_tail": stderr[-4000:]}
    except OSError as exc:
        return {"status": "EXECUTION_ERROR", "error_type": type(exc).__name__, "error_message": str(exc)}
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "exit_code": completed.returncode,
        "stderr_tail": completed.stderr[-4000:],
    }


def qualify_source(
    source: dict[str, Any], *, download_dir: Path, routing_dir: Path, bcftools: str
) -> dict[str, Any]:
    path = download_dir / f"{source['id']}.vcf"
    result: dict[str, Any] = {
        "source_id": source["id"],
        "declared_version_expected": source["version"],
        "source_class": source["source_class"],
        "source_url": source["url"],
        "source_commit": source["commit"],
        "source_path": source["path"],
        "expected_git_blob_sha1": source["git_blob_sha1"],
        "expected_size_bytes": source["size_bytes"],
        "status": "FAIL",
    }
    try:
        payload = acquire(source, path)
        result["source_integrity"] = {
            "status": "VERIFIED",
            "bytes": len(payload),
            "git_blob_sha1": git_blob_sha1(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    except Exception as exc:
        result["failure_stage"] = "ACQUISITION_OR_SOURCE_INTEGRITY"
        result["failure_type"] = type(exc).__name__
        result["failure_message"] = str(exc)
        return result

    try:
        profile = validate_vcf_strict(path)
        version_matches = profile.get("fileformat") == source["version"]
        result["strict_validation"] = {
            "status": "PASS" if version_matches else "FAIL",
            "declared_version": profile.get("fileformat"),
            "records": profile.get("records"),
            "sample_count": profile.get("sample_count"),
            "alternate_allele_count": profile.get("alternate_allele_count"),
            "compression": profile.get("compression"),
        }
        if not version_matches:
            result["strict_validation"]["error_message"] = (
                f"expected {source['version']}, observed {profile.get('fileformat')}"
            )
    except StrictVCFValidationError as exc:
        result["strict_validation"] = {
            "status": "FAIL", "error_code": exc.code, "error_message": str(exc)
        }
    except Exception as exc:
        result["strict_validation"] = {
            "status": "FAIL", "error_type": type(exc).__name__, "error_message": str(exc)
        }

    result["bcftools_parser"] = run_bcftools(bcftools, path)

    if result.get("strict_validation", {}).get("status") == "PASS":
        try:
            routing = route_vcf_records(path, routing_dir / source["id"])
            reconciliation = routing.get("record_reconciliation", {})
            balanced = (
                reconciliation.get("balanced") is True
                and reconciliation.get("source_records") == reconciliation.get("routed_records")
            )
            route_category_counts = {
                "sequence": routing.get("sequence_records", 0),
                "structural_variants": routing.get("structural_variant_records", 0),
                "copy_number_variants": routing.get("cnv_variant_records", 0),
                "repeat_expansions": routing.get("repeat_expansion_records", 0),
                "mitochondrial_variants": routing.get("mitochondrial_variant_records", 0),
            }
            expected_category = source.get("expected_route_category")
            expected_category_count = route_category_counts.get(expected_category, 0)
            route_passed = balanced and expected_category_count > 0
            result["record_routing"] = {
                "status": "PASS" if route_passed else "FAIL",
                "expected_route_category": expected_category,
                "expected_route_category_record_count": expected_category_count,
                "route_category_counts": route_category_counts,
                "record_reconciliation": reconciliation,
            }
        except Exception as exc:
            result["record_routing"] = {
                "status": "FAIL", "error_type": type(exc).__name__, "error_message": str(exc)
            }

    passed = (
        result.get("strict_validation", {}).get("status") == "PASS"
        and result.get("bcftools_parser", {}).get("status") == "PASS"
        and result.get("record_routing", {}).get("status") == "PASS"
    )
    result["status"] = "PASS" if passed else "FAIL"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--bcftools", default="bcftools")
    args = parser.parse_args()

    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"Refusing non-empty evidence directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    download_dir = output_dir / "inputs"
    routing_dir = output_dir / "routing"
    download_dir.mkdir(mode=0o700)
    routing_dir.mkdir(mode=0o700)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    version_output = subprocess.run(
        [args.bcftools, "--version"], capture_output=True, text=True, timeout=30, check=True
    ).stdout.splitlines()
    reports = [
        qualify_source(
            source, download_dir=download_dir, routing_dir=routing_dir, bcftools=args.bcftools
        )
        for source in manifest["sources"]
    ]
    expected = {"VCFv4.0", "VCFv4.1", "VCFv4.2", "VCFv4.3", "VCFv4.4", "VCFv4.5"}
    observed = {item["declared_version_expected"] for item in reports}
    source_ids = [item["source_id"] for item in reports]
    failed = [item for item in reports if item["status"] != "PASS"]
    report = {
        "suite_id": manifest["suite_id"],
        "schema_version": manifest["schema_version"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "repository_commit": os.environ.get("GITHUB_SHA"),
        "bcftools_version_output": version_output,
        "expected_versions": sorted(expected),
        "sources_cover_all_versions": observed == expected,
        "source_count": len(reports),
        "unique_source_count": len(set(source_ids)),
        "one_source_per_version": len(reports) == len(expected) and len(set(source_ids)) == len(expected) and observed == expected,
        "passed_source_count": len(reports) - len(failed),
        "failed_source_count": len(failed),
        "execution_status": "PASSED" if not failed and observed == expected and len(reports) == len(expected) and len(set(source_ids)) == len(expected) else "FAILED",
        "clinical_validation_claim": False,
        "source_results": reports,
    }
    report_path = output_dir / "public-vcf-version-corpus-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_status": report["execution_status"],
        "passed_source_count": report["passed_source_count"],
        "failed_source_count": report["failed_source_count"],
        "report": str(report_path),
    }, indent=2))
    return 0 if report["execution_status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
