#!/usr/bin/env python3
"""Read-only preflight for a laboratory's governed SIRALOOM resources/storage.

Run inside the laboratory deployment with its normal DATABASE_URL and storage
environment configured. This script does not register resources, change bindings,
write artifacts, or claim scientific qualification.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from uuid import UUID

from sqlalchemy import select

from backend.app.domain.resource_execution import (
    ResourceExecutionError,
    resolve_resource_execution,
)
from backend.app.domain.storage_profiles import (
    StorageProfileError,
    artifact_store_for_organization,
    resolve_storage_profile,
)
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    Case,
    Organization,
    OrganizationResourceBinding,
    Resource,
)
from backend.app.infrastructure.db.session import SessionLocal


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _check(name: str, status: str, detail: str, **extra) -> dict:
    return {"check": name, "status": status, "detail": detail, **extra}


def qualify_organization(organization_id: UUID) -> dict:
    checks: list[dict] = []
    blockers = 0
    warnings = 0

    with SessionLocal() as db:
        organization = db.get(Organization, organization_id)
        if organization is None:
            return {
                "organization_id": str(organization_id),
                "decision": "BLOCKED",
                "checks": [_check(
                    "organization",
                    "BLOCKED",
                    "Organization ID was not found in the configured database.",
                )],
            }
        checks.append(_check(
            "organization", "PASS", "Organization exists in the configured database.",
            organization_name=organization.name,
        ))

        try:
            storage_profile = resolve_storage_profile(
                db, organization_id=organization_id
            )
            if storage_profile is None:
                checks.append(_check(
                    "storage_profile", "BLOCKED",
                    "No ACTIVE organization storage profile is configured.",
                ))
                blockers += 1
                storage = None
            else:
                storage = artifact_store_for_organization(
                    db, organization_id=organization_id
                )
                checks.append(_check(
                    "storage_profile", "PASS",
                    "ACTIVE storage profile resolves against deployment configuration.",
                    profile_name=storage_profile.name,
                    profile_version=storage_profile.version,
                    backend_type=storage_profile.backend_type,
                    storage_key=storage_profile.storage_key,
                ))
        except StorageProfileError as exc:
            checks.append(_check("storage_profile", "BLOCKED", str(exc)))
            blockers += 1
            storage = None

        bindings = db.scalars(
            select(OrganizationResourceBinding)
            .where(OrganizationResourceBinding.organization_id == organization_id)
            .order_by(OrganizationResourceBinding.identity_key)
        ).all()
        if not bindings:
            checks.append(_check(
                "resource_registry", "BLOCKED",
                "No organization-bound scientific resources were found.",
            ))
            blockers += 1

        for binding in bindings:
            label = f"{binding.identity_key}:{binding.resource_name}"
            resource = db.get(Resource, binding.resource_id)
            if resource is None:
                checks.append(_check(
                    f"resource:{label}", "BLOCKED",
                    "Binding references a missing resource record.",
                    resource_id=str(binding.resource_id),
                ))
                blockers += 1
                continue

            identity_mismatches = []
            for field in ("resource_name", "provider", "resource_type", "genome_build"):
                bound_value = getattr(binding, field)
                resource_value = getattr(resource, "name" if field == "resource_name" else field)
                if bound_value != resource_value:
                    identity_mismatches.append(
                        f"{field}: binding={bound_value!r}, resource={resource_value!r}"
                    )
            if identity_mismatches:
                checks.append(_check(
                    f"resource:{label}", "BLOCKED",
                    "Organization binding identity differs from the registered resource.",
                    mismatches=identity_mismatches,
                ))
                blockers += 1
                continue

            if str(resource.status).upper() != "ACTIVE":
                checks.append(_check(
                    f"resource:{label}", "BLOCKED",
                    f"Bound resource status is {resource.status!r}, not ACTIVE.",
                    resource_id=str(resource.id),
                ))
                blockers += 1
                continue
            if not resource.version or not resource.checksum or not _SHA256.fullmatch(resource.checksum):
                checks.append(_check(
                    f"resource:{label}", "BLOCKED",
                    "Resource must have a version and a 64-character SHA-256 checksum.",
                    resource_id=str(resource.id),
                    version=resource.version,
                    checksum_present=bool(resource.checksum),
                ))
                blockers += 1
                continue

            try:
                execution = resolve_resource_execution(db, resource=resource)
                checks.append(_check(
                    f"resource:{label}", "PASS",
                    "Bound resource has a valid qualified execution contract.",
                    resource_id=str(resource.id),
                    version=resource.version,
                    checksum=resource.checksum,
                    qualification_id=str(execution.qualification_id),
                    qualification_version=execution.qualification_version,
                    execution_contract_sha256=execution.contract_hash,
                ))
            except ResourceExecutionError as exc:
                checks.append(_check(
                    f"resource:{label}", "BLOCKED", str(exc),
                    resource_id=str(resource.id),
                    version=resource.version,
                ))
                blockers += 1

        if storage is not None:
            existing_artifact = db.scalar(
                select(Artifact)
                .join(Case, Case.id == Artifact.case_id)
                .where(Case.organization_id == organization_id)
                .order_by(Artifact.created_at.desc())
                .limit(1)
            )
            if existing_artifact is None:
                checks.append(_check(
                    "storage_read_probe", "NOT_VERIFIED",
                    "No existing organization artifact is available for a non-mutating storage read probe.",
                ))
                warnings += 1
            else:
                try:
                    exists = bool(storage.exists(existing_artifact.storage_uri))
                except Exception as exc:
                    exists = False
                    detail = f"Storage existence probe raised {type(exc).__name__}: {exc}"
                else:
                    detail = (
                        "Configured storage backend can locate an existing artifact."
                        if exists
                        else "Configured storage backend cannot locate the selected existing artifact."
                    )
                checks.append(_check(
                    "storage_read_probe",
                    "PASS" if exists else "BLOCKED",
                    detail,
                    artifact_id=str(existing_artifact.id),
                    artifact_type=existing_artifact.artifact_type,
                ))
                if not exists:
                    blockers += 1

    return {
        "organization_id": str(organization_id),
        "decision": "PASS" if blockers == 0 and warnings == 0 else (
            "PASS_WITH_WARNINGS" if blockers == 0 else "BLOCKED"
        ),
        "blocker_count": blockers,
        "warning_count": warnings,
        "checks": checks,
        "scope_note": (
            "Read-only registry/storage preflight only. This does not execute the workflow, "
            "test storage writes or ingress capacity, compare GIAB truth sets, or qualify "
            "clinical performance."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--organization-id",
        required=True,
        type=UUID,
        help="Exact laboratory organization UUID from the configured SIRALOOM database.",
    )
    args = parser.parse_args()
    result = qualify_organization(args.organization_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 2 if result["decision"] == "PASS_WITH_WARNINGS" else 1


if __name__ == "__main__":
    sys.exit(main())
