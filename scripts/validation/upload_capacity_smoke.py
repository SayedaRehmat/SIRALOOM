#!/usr/bin/env python3
"""Concurrent artifact-upload smoke test for a disposable SIRALOOM lab case.

This script creates one persisted artifact per successful request. Use only a
disposable case and VCF fixture; it does not delete artifacts after the run.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import time
from pathlib import Path
from threading import Lock
from typing import Any

import httpx


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="API base URL, e.g. https://lab.example/api/v1")
    parser.add_argument("--case-id", required=True, help="Existing disposable case UUID")
    parser.add_argument("--specimen-id", required=True, help="Specimen UUID belonging to that case")
    parser.add_argument("--genome-build", choices=("GRCh37", "GRCh38"), required=True)
    parser.add_argument("--vcf", required=True, type=Path, help="Small valid VCF fixture to upload repeatedly")
    parser.add_argument("--requests", type=int, default=10, help="Total uploads (default: 10)")
    parser.add_argument("--concurrency", type=int, default=2, help="Parallel uploads (default: 2)")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--confirm-disposable-case", action="store_true", help="Required: confirms artifacts may be retained")
    args = parser.parse_args()

    token = os.environ.get("SIRALOOM_API_TOKEN")
    if not token:
        parser.error("Set SIRALOOM_API_TOKEN in the environment; do not pass tokens as CLI arguments.")
    if not args.confirm_disposable_case:
        parser.error("Use --confirm-disposable-case only after confirming this case is disposable.")
    if not args.vcf.is_file():
        parser.error(f"VCF fixture does not exist: {args.vcf}")
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive integers.")
    if args.concurrency > args.requests:
        parser.error("--concurrency cannot exceed --requests.")

    fixture_size = args.vcf.stat().st_size
    if fixture_size == 0:
        parser.error("VCF fixture is empty.")
    endpoint = f"{args.base_url.rstrip('/')}/cases/{args.case_id}/artifacts"
    headers = {"Authorization": f"Bearer {token}"}
    lock = Lock()
    results: list[dict[str, Any]] = []

    def upload(index: int) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with args.vcf.open("rb") as handle:
                response = httpx.post(
                    endpoint,
                    headers=headers,
                    data={"specimen_id": args.specimen_id, "genome_build": args.genome_build},
                    files={"file": (args.vcf.name, handle, "application/octet-stream")},
                    timeout=args.timeout_seconds,
                    follow_redirects=False,
                )
            elapsed = time.perf_counter() - started
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text[:1000]
            result = {
                "request": index,
                "status_code": response.status_code,
                "elapsed_seconds": round(elapsed, 4),
                "response": body,
            }
        except Exception as exc:  # report transport and timeout failures alongside HTTP responses
            result = {
                "request": index,
                "status_code": None,
                "elapsed_seconds": round(time.perf_counter() - started, 4),
                "error": f"{type(exc).__name__}: {exc}",
            }
        with lock:
            results.append(result)
        return result

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(upload, range(1, args.requests + 1)))
    total_seconds = time.perf_counter() - started

    latencies = [r["elapsed_seconds"] for r in results]
    accepted = sum(r["status_code"] == 201 for r in results)
    summary = {
        "endpoint": endpoint,
        "fixture_path": str(args.vcf.resolve()),
        "fixture_size_bytes": fixture_size,
        "requested_uploads": args.requests,
        "concurrency": args.concurrency,
        "successful_uploads": accepted,
        "failed_uploads": args.requests - accepted,
        "elapsed_seconds": round(total_seconds, 4),
        "aggregate_upload_mib_per_second": round(
            (accepted * fixture_size / (1024 * 1024)) / total_seconds, 4
        ) if total_seconds else None,
        "latency_seconds": {
            "min": round(min(latencies), 4) if latencies else None,
            "median": round(statistics.median(latencies), 4) if latencies else None,
            "p95": round(percentile(latencies, 0.95), 4) if latencies else None,
            "max": round(max(latencies), 4) if latencies else None,
        },
        "results": sorted(results, key=lambda item: item["request"]),
        "interpretation": (
            "HTTP 201 means the endpoint accepted the upload; inspect validation_status "
            "in each response. This script does not measure server temp-disk peaks or prove "
            "ingress-level body-size enforcement. Collect host/proxy/storage metrics separately."
        ),
    }
    print(json.dumps(summary, indent=2))
    return 0 if accepted == args.requests else 1


if __name__ == "__main__":
    sys.exit(main())
