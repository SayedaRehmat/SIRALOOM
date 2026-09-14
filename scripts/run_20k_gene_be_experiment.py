from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))



def load_runtime():
    from backend.app.adapters.annotation.genebe import GeneBeError, GeneBeProvider
    from backend.app.config import settings
    return GeneBeError, GeneBeProvider, settings


def build_variants(count: int, chromosome: str = "1", start: int = 10_000):
    from backend.app.domain.schemas import CanonicalVariant
    return [
        CanonicalVariant(
            genome_build="GRCh38",
            chromosome=chromosome,
            position=start + i,
            reference="A",
            alternate="G",
            normalization_status="NORMALIZED",
        )
        for i in range(count)
    ]


def batch_plan(total: int, batch_size: int) -> list[tuple[int, int]]:
    return [(start, min(start + batch_size, total)) for start in range(0, total, batch_size)]


def run_live(variants, genome: str) -> dict[str, Any]:
    GeneBeError, GeneBeProvider, settings = load_runtime()
    if not settings.genebe_enabled:
        raise RuntimeError("GENEBE_ENABLED=true is required for --live")
    if not settings.genebe_email or not settings.genebe_api_key:
        raise RuntimeError("GENEBE_EMAIL and GENEBE_API_KEY must be configured for --live")

    provider = GeneBeProvider()
    max_batch = settings.genebe_max_batch
    plan = batch_plan(len(variants), max_batch)
    results: list[dict[str, Any]] = []
    batch_results: list[dict[str, Any]] = []

    for batch_number, (start, end) in enumerate(plan, start=1):
        batch = variants[start:end]
        started = time.perf_counter()
        try:
            response = provider.annotate(batch, {"genome": genome})
        except GeneBeError as exc:
            batch_results.append({
                "batch": batch_number,
                "start_index": start,
                "end_index_exclusive": end,
                "requested": len(batch),
                "status": "FAILED",
                "error": str(exc),
                "duration_seconds": round(time.perf_counter() - started, 3),
            })
            break
        duration = time.perf_counter() - started
        results.extend(response)
        batch_results.append({
            "batch": batch_number,
            "start_index": start,
            "end_index_exclusive": end,
            "requested": len(batch),
            "returned": len(response),
            "status": "SUCCEEDED",
            "duration_seconds": round(duration, 3),
        })

    return {
        "mode": "live",
        "requested_variants": len(variants),
        "batch_size": max_batch,
        "planned_batches": len(plan),
        "completed_batches": sum(x["status"] == "SUCCEEDED" for x in batch_results),
        "failed_batches": sum(x["status"] == "FAILED" for x in batch_results),
        "returned_variants": len(results),
        "batch_results": batch_results,
    }


def run_dry(variants) -> dict[str, Any]:
    batch_size = 1000
    plan = batch_plan(len(variants), batch_size)
    sizes = [end - start for start, end in plan]
    return {
        "mode": "dry-run",
        "requested_variants": len(variants),
        "batch_size": batch_size,
        "planned_batches": len(plan),
        "batch_sizes": sizes,
        "max_batch_ok": all(size <= batch_size for size in sizes),
        "expected_last_batch": sizes[-1] if sizes else 0,
    }


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows = report.get("batch_results", [])
    if rows:
        with (output_dir / "batch_results.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=sorted(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="SIRALOOM 20K GeneBe batching experiment")
    parser.add_argument("--variants", type=int, default=20_000)
    parser.add_argument("--live", action="store_true", help="Use configured GeneBe API credentials")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "20k-genebe-experiment")
    args = parser.parse_args()

    if args.variants <= 0:
        raise SystemExit("--variants must be > 0")

    variants = build_variants(args.variants)
    report = run_live(variants, "hg38") if args.live else run_dry(variants)
    report["genome"] = "hg38"
    report["provider_base_url"] = "https://api.genebe.net/cloud/api-public/v1"
    write_report(report, args.output)
    print(json.dumps({k: v for k, v in report.items() if k != "batch_results"}, indent=2))
    return 2 if report.get("failed_batches", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
