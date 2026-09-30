from __future__ import annotations

"""Pluggable discovery for scientific resources."""

from importlib.metadata import entry_points
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.domain.resources import register_resource_version
from backend.app.domain.resource_source_contract import validate_source_contract

RESOURCE_PROVIDER_GROUP = "siraloom.resource_providers"


def _provider_instances() -> list[Any]:
    discovered = entry_points()
    if hasattr(discovered, "select"):
        entries = discovered.select(group=RESOURCE_PROVIDER_GROUP)
    else:
        entries = discovered.get(RESOURCE_PROVIDER_GROUP, [])
    providers = []
    for entry in entries:
        provider = entry.load()
        providers.append(provider() if isinstance(provider, type) else provider)
    return providers


def discover_resource_candidates(db: Session) -> dict[str, int]:
    """Run installed resource-provider adapters and create CANDIDATE records.

    Discovery never activates a resource. Qualification and activation are
    separate governed operations.
    """
    discovered_count = 0
    failed_providers = 0
    for provider in _provider_instances():
        try:
            candidates: Iterable[dict[str, Any]] = provider.discover()
            for candidate in candidates:
                source_contract = validate_source_contract(dict(candidate.get("source_contract") or {}))
                register_resource_version(
                    db,
                    name=str(candidate.get("name") or ""),
                    provider=str(candidate.get("provider") or ""),
                    resource_type=str(candidate.get("resource_type") or ""),
                    version=str(candidate.get("version") or ""),
                    genome_build=str(candidate["genome_build"]) if candidate.get("genome_build") else None,
                    access_method=str(candidate.get("access_method") or ""),
                    license_text=candidate.get("license_text"),
                    checksum=candidate.get("checksum"),
                    location=candidate.get("location"),
                    population_definition=candidate.get("population_definition"),
                    metadata_json={
                        **dict(candidate.get("metadata") or {}),
                        "source_contract": source_contract.as_dict(),
                        "discovery_provider": provider.__class__.__module__ + "." + provider.__class__.__name__,
                    },
                    organization_id=UUID(str(candidate["organization_id"])) if candidate.get("organization_id") else None,
                    initial_status="CANDIDATE",
                )
                discovered_count += 1
        except Exception:
            db.rollback()
            failed_providers += 1
        else:
            db.commit()
    db.commit()
    return {"candidates_discovered": discovered_count, "providers_failed": failed_providers}