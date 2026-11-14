#!/usr/bin/env python3
"""Run the SIRALOOM technical qualification engine against a built package manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from backend.app.domain.reference_registry import validate_reference_registration
from backend.app.domain.resource_qualification import qualify_resource


def qualify_manifest(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    package_version = str(manifest["package_version"])
    package_checksum = str(manifest["package_checksum"])
    validate_reference_registration(
        manifest,
        genome_build=str(manifest["assembly_name"]),
        package_version=package_version,
        package_checksum=package_checksum,
    )
    resource_id = uuid4()
    resource = SimpleNamespace(
        id=resource_id,
        name="NCBI GRCh38 full plus hs38d1 analysis set",
        provider="SIRALOOM_REFERENCE",
        resource_type="REFERENCE_PACKAGE",
        version=package_version,
        genome_build="GRCh38",
        status="CANDIDATE",
        access_method="LOCAL",
        organization_id=None,
        checksum=package_checksum,
        location=str(manifest["fasta_path"]),
        metadata_json=manifest,
    )
    fasta = Path(manifest["fasta_path"])
    staging = SimpleNamespace(
        id=uuid4(),
        resource_id=resource_id,
        resource_version=package_version,
        staging_key=f"ncbi:{package_version}",
        source_uri=manifest["source_contract"]["artifact_url"],
        destination_uri=str(fasta),
        storage_backend="LOCAL_FILESYSTEM",
        status="STAGED",
        expected_sha256=manifest["fasta_sha256"],
        observed_sha256=manifest["fasta_sha256"],
        expected_size_bytes=fasta.stat().st_size,
        observed_size_bytes=fasta.stat().st_size,
    )
    result = qualify_resource(
        resource,
        staging=staging,
        qualification_version="siraloom-reference-package-1.2",
    )
    return {
        "engine": "siraloom.reference-package-qualification",
        "qualification_version": result.qualification_version,
        "status": "QUALIFIED" if result.passed else "BLOCKED",
        "passed": result.passed,
        "blockers": result.blockers,
        "checks": result.checks,
        "resource": {
            "name": resource.name,
            "version": resource.version,
            "genome_build": resource.genome_build,
            "package_checksum": resource.checksum,
            "sequence_collection_digest": manifest["sequence_collection_digest"],
        },
        "persistence": "NOT_PERSISTED_THIS_IS_A_DISPOSABLE_QUALIFICATION_RUN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = qualify_manifest(args.manifest)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "passed": report["passed"],
        "blockers": report["blockers"],
        "report": str(args.report),
        "package_version": report["resource"]["version"],
        "sequence_collection_digest": report["resource"]["sequence_collection_digest"],
    }, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
