from __future__ import annotations

from typing import Any


def annotation_provenance_snapshot(annotation: Any) -> dict[str, Any]:
    """Return the safe, reproducible execution identity for a persisted annotation.

    Provider endpoints and runtime-check details are intentionally excluded: they
    may contain deployment-specific URLs or filesystem paths and belong in the
    access-controlled execution record, not clinical presentation payloads.
    """
    metadata = annotation.request_metadata or {}
    options = metadata.get("annotation_options")
    return {
        "provider": annotation.provider_name,
        "provider_version": annotation.provider_version,
        "resource": annotation.resource_name,
        "resource_version": annotation.resource_version,
        "annotation_options": (
            [option for option in options if isinstance(option, str)]
            if isinstance(options, (list, tuple))
            else None
        ),
        "request_fingerprint": annotation.request_fingerprint,
        "response_sha256": annotation.response_sha256,
        "observed_at": annotation.observed_at.isoformat() if annotation.observed_at else None,
    }
