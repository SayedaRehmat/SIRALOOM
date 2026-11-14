#!/usr/bin/env python3
"""Register and persist qualification of a built reference package in a target DB."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.reference_registry import (
    qualify_reference_package_resource,
    register_reference_package,
)
from backend.app.domain.resource_staging import (
    create_staging_candidate,
    verify_existing_local_artifact,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Resource, ResourceQualification, ResourceStaging


def register_and_qualify(manifest_path: Path, database_url: str) -> dict:
    if not database_url.startswith(("sqlite+pysqlite:///", "sqlite:///")):
        raise ValueError(
            "this qualification harness is restricted to disposable SQLite databases; "
            "use the governed application service and approved database migration path for production"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = (
        "package_version", "package_checksum", "assembly_name",
        "fasta_path", "fasta_sha256", "fasta_size_bytes",
    )
    missing = [key for key in required if manifest.get(key) is None or manifest.get(key) == ""]
    if missing:
        raise ValueError("package manifest missing required fields: " + ", ".join(missing))
    if not isinstance(manifest["fasta_size_bytes"], int) or manifest["fasta_size_bytes"] <= 0:
        raise ValueError("package manifest fasta_size_bytes must be a positive integer")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        Base.metadata.create_all(
            engine,
            tables=[
                Resource.__table__,
                ResourceStaging.__table__,
                ResourceQualification.__table__,
            ],
        )
        with Session(engine) as db:
            resource, created = register_reference_package(
                db,
                name="NCBI GRCh38 full plus hs38d1 analysis set",
                provider="SIRALOOM_REFERENCE",
                version=str(manifest["package_version"]),
                genome_build=str(manifest["assembly_name"]),
                manifest=manifest,
                package_checksum=str(manifest["package_checksum"]),
                source_contract=manifest["source_contract"],
                execution_contract=manifest["execution"],
            )
            staging = create_staging_candidate(
                db,
                resource=resource,
                source_uri=manifest["source_contract"]["artifact_url"],
                destination_uri=str(manifest["fasta_path"]),
                storage_backend="LOCAL_FILESYSTEM",
                expected_sha256=str(manifest["fasta_sha256"]),
                expected_size_bytes=int(manifest["fasta_size_bytes"]),
                staging_key=f"ncbi:{resource.version}",
                metadata={
                    "publisher_artifact_url": manifest["source_contract"]["artifact_url"],
                    "publisher_evidence_file_sha256": manifest["source_contract"][
                        "publisher_checksum_evidence"
                    ]["evidence_file_sha256"],
                },
            )
            staging = verify_existing_local_artifact(db, staging)
            result, qualification = qualify_reference_package_resource(
                db,
                resource_id=resource.id,
                staging=staging,
                qualification_version="siraloom-reference-package-1.2",
            )
            if not result.passed or qualification.status != "QUALIFIED":
                db.commit()
                return {
                    "status": "BLOCKED",
                    "passed": False,
                    "resource_id": str(resource.id),
                    "resource_status": resource.status,
                    "qualification_id": str(qualification.id),
                    "qualification_status": qualification.status,
                    "blockers": result.blockers,
                    "checks": result.checks,
                    "database_url": database_url,
                }
            db.commit()
            db.refresh(resource)
            db.refresh(qualification)
            return {
                "status": "QUALIFIED",
                "passed": True,
                "resource_id": str(resource.id),
                "resource_version": resource.version,
                "resource_status": resource.status,
                "created": created,
                "staging_id": str(staging.id),
                "qualification_id": str(qualification.id),
                "qualification_status": qualification.status,
                "checks": qualification.checks_json,
                "sequence_collection_digest": manifest["sequence_collection_digest"],
                "activation": "NOT_REQUESTED_REQUIRES_SEPARATE_GOVERNANCE_APPROVAL",
                "database_url": database_url,
            }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = register_and_qualify(args.manifest, args.database_url)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "passed": report["passed"],
        "resource_id": report.get("resource_id"),
        "resource_status": report.get("resource_status"),
        "qualification_status": report.get("qualification_status"),
        "report": str(args.report),
    }, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
