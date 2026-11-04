#!/usr/bin/env python3
"""Bootstrap-qualify a historical 1000 Genomes VCFv4.0 cohort file.

This captures immutable bytes and exercises the native parser, BCFtools, and
record routing. The first acquisition is intentionally UNPINNED; its digest
must be reviewed and committed to the source manifest before this evidence can
be promoted to a reproducible qualification result.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from backend.app.domain.vcf_tools import route_vcf_records
from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict

SOURCE_URL = (
    "https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/pilot_data/release/"
    "2010_07/exon/snps/CEU.exon.2010_03.genotypes.vcf.gz"
)
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024


def acquire(destination: Path) -> dict:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "SIRALOOM-VCFv4.0-Qualification/1.0"},
    )
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=180) as response:
        final_url = response.geturl()
        status = getattr(response, "status", None)
        headers = dict(response.headers.items())
        with destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_SOURCE_BYTES:
                    raise ValueError(f"Historical VCF exceeds {MAX_SOURCE_BYTES} byte acquisition limit")
                digest.update(chunk)
                output.write(chunk)
    if size == 0:
        raise ValueError("Historical VCF acquisition returned an empty response")
    return {
        "requested_url": SOURCE_URL,
        "final_url": final_url,
        "http_status": status,
        "response_headers": headers,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "digest_pinned": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--bcftools", default="bcftools")
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Refusing non-empty evidence directory: {output}")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    inputs = output / "inputs"
    routing_dir = output / "routing"
    inputs.mkdir(mode=0o700)
    routing_dir.mkdir(mode=0o700)
    archive = inputs / "CEU.exon.2010_03.genotypes.vcf.gz"
    plain_vcf = inputs / "CEU.exon.2010_03.genotypes.vcf"

    report = {
        "suite_id": "siraloom-vcf40-historical-cohort-bootstrap-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": None,
        "declared_fileformat": None,
        "native_validation": {"status": "NOT_RUN"},
        "bcftools_validation": {"status": "NOT_RUN"},
        "record_routing": {"status": "NOT_RUN"},
        "qualification_status": "BOOTSTRAP_ONLY_UNPINNED",
        "clinical_validation_claim": False,
    }
    try:
        report["source"] = acquire(archive)
        with gzip.open(archive, "rt", encoding="utf-8-sig") as compressed, plain_vcf.open(
            "w", encoding="utf-8", newline="\n"
        ) as plain:
            for line in compressed:
                plain.write(line)
        with gzip.open(archive, "rt", encoding="utf-8-sig") as compressed:
            for line in compressed:
                if line.startswith("##fileformat="):
                    report["declared_fileformat"] = line.rstrip("\r\n").split("=", 1)[1]
                    break
        if report["declared_fileformat"] != "VCFv4.0":
            raise ValueError(
                f"Expected VCFv4.0, observed {report['declared_fileformat']!r}"
            )
        profile = validate_vcf_strict(plain_vcf)
        report["native_validation"] = {
            "status": "PASS",
            "declared_fileformat": profile.get("fileformat"),
            "records": profile.get("records"),
            "sample_count": profile.get("sample_count"),
            "alternate_allele_count": profile.get("alternate_allele_count"),
        }
        completed = subprocess.run(
            [
                args.bcftools, "view", "--no-version", "--output-type", "v",
                "--output", "/dev/null", str(archive),
            ],
            capture_output=True, text=True, timeout=300, check=False,
        )
        report["bcftools_validation"] = {
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "exit_code": completed.returncode,
            "stderr_tail": completed.stderr[-4000:],
        }
        routing = route_vcf_records(plain_vcf, routing_dir)
        reconciliation = routing.get("record_reconciliation", {})
        balanced = (
            reconciliation.get("balanced") is True
            and reconciliation.get("source_records") == reconciliation.get("routed_records")
        )
        report["record_routing"] = {
            "status": "PASS" if balanced else "FAIL",
            "sequence_records": routing.get("sequence_records", 0),
            "structural_variant_records": routing.get("structural_variant_records", 0),
            "cnv_variant_records": routing.get("cnv_variant_records", 0),
            "record_reconciliation": reconciliation,
        }
        passed = (
            report["native_validation"]["status"] == "PASS"
            and report["bcftools_validation"]["status"] == "PASS"
            and report["record_routing"]["status"] == "PASS"
        )
        report["execution_status"] = "PASSED" if passed else "FAILED"
        report["qualification_status"] = (
            "BOOTSTRAP_EXECUTION_PASSED_DIGEST_PIN_PENDING"
            if passed else "BOOTSTRAP_EXECUTION_FAILED_DIGEST_PIN_PENDING"
        )
    except Exception as exc:
        report["execution_status"] = "FAILED"
        report["failure_type"] = type(exc).__name__
        report["failure_message"] = str(exc)
    report_path = output / "vcf40-historical-cohort-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "execution_status": report.get("execution_status"),
        "qualification_status": report["qualification_status"],
        "source_sha256": (report.get("source") or {}).get("sha256"),
        "report": str(report_path),
    }, indent=2))
    return 0 if report.get("execution_status") == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
