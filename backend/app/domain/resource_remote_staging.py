"""Governed remote acquisition for discovered scientific resources.

This adapter is intentionally narrow: HTTPS only, explicit publisher-host allowlist,
mandatory release SHA-256, bounded streaming, no automatic redirects, and atomic
promotion into the already-qualified staging destination. Authentication and
credentialed providers belong in provider-specific adapters rather than this
generic transport primitive.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import os
import tempfile

from sqlalchemy.orm import Session

from backend.app.domain.resource_staging import (
    ResourceStagingError,
    prepare_staging,
    transition_staging,
)
from backend.app.infrastructure.db.models import ResourceStaging


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _normalized_hosts(allowed_hosts: set[str] | frozenset[str]) -> set[str]:
    return {host.strip().lower().rstrip(".") for host in allowed_hosts if host.strip()}


def _validate_remote_source(source_uri: str, allowed_hosts: set[str] | frozenset[str]) -> str:
    parsed = urlparse(source_uri)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ResourceStagingError("remote staging requires an absolute HTTPS artifact URL")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname not in _normalized_hosts(allowed_hosts):
        raise ResourceStagingError(
            f"remote artifact host {hostname!r} is not in the governed publisher allow-list"
        )
    if parsed.username or parsed.password:
        raise ResourceStagingError("remote artifact URLs must not contain embedded credentials")
    return hostname


def stage_remote_artifact(
    db: Session,
    row: ResourceStaging,
    *,
    allowed_hosts: set[str] | frozenset[str],
    max_bytes: int,
    timeout_seconds: float = 30.0,
) -> ResourceStaging:
    """Acquire one explicitly discovered public HTTPS artifact into governed staging.

    The release checksum is mandatory. Redirects, embedded credentials, oversized
    payloads, and hosts outside the publisher allow-list are rejected before the
    destination can be modified.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if not row.expected_sha256:
        raise ResourceStagingError(
            "remote staging requires a published expected SHA-256 checksum"
        )
    _validate_remote_source(row.source_uri, allowed_hosts)

    destination = Path(row.destination_uri)
    if row.status == "DISCOVERED":
        prepare_staging(db, row)
    if row.status != "READY_TO_STAGE":
        raise ResourceStagingError(f"resource staging is not ready: {row.status}")

    transition_staging(db, row, "STAGING")
    temporary: Path | None = None
    try:
        request = Request(
            row.source_uri,
            headers={
                "User-Agent": "SIRALOOM-resource-stager/1",
                "Accept": "*/*",
            },
            method="GET",
        )
        opener = build_opener(_NoRedirect)
        with opener.open(request, timeout=timeout_seconds) as response:
            if getattr(response, "status", 200) != 200:
                raise ResourceStagingError(
                    f"remote artifact returned HTTP {getattr(response, 'status', 'unknown')}"
                )
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError as exc:
                    raise ResourceStagingError("remote Content-Length is invalid") from exc
                if declared_length > max_bytes:
                    raise ResourceStagingError(
                        f"remote artifact exceeds configured maximum of {max_bytes} bytes"
                    )
                if row.expected_size_bytes is not None and declared_length != row.expected_size_bytes:
                    raise ResourceStagingError(
                        f"remote Content-Length {declared_length} does not match expected "
                        f"{row.expected_size_bytes}"
                    )

            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{destination.name}.remote-",
                dir=str(destination.parent),
            )
            os.close(fd)
            temporary = Path(temp_name)

            digest = sha256()
            observed_size = 0
            with temporary.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    observed_size += len(chunk)
                    if observed_size > max_bytes:
                        raise ResourceStagingError(
                            f"remote artifact exceeds configured maximum of {max_bytes} bytes"
                        )
                    digest.update(chunk)
                    output.write(chunk)

            observed_sha256 = digest.hexdigest()
            row.observed_size_bytes = observed_size
            row.observed_sha256 = observed_sha256

            if (
                row.expected_size_bytes is not None
                and observed_size != row.expected_size_bytes
            ):
                return transition_staging(
                    db,
                    row,
                    "INTEGRITY_FAILED",
                    error_code="SIZE_MISMATCH",
                    error_message=(
                        f"expected {row.expected_size_bytes} bytes, observed {observed_size}"
                    ),
                )
            if observed_sha256 != row.expected_sha256.lower():
                return transition_staging(
                    db,
                    row,
                    "INTEGRITY_FAILED",
                    error_code="CHECKSUM_MISMATCH",
                    error_message="remote artifact SHA-256 does not match the declared release checksum",
                )

            os.replace(temporary, destination)
            temporary = None
            row.metadata_json = {
                **dict(row.metadata_json or {}),
                "acquisition": "HTTPS",
                "publisher_host": urlparse(row.source_uri).hostname,
                "integrity": "SHA256_VERIFIED",
            }
            return transition_staging(db, row, "STAGED")
    except HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            code = "REDIRECT_REJECTED"
        else:
            code = "HTTP_ERROR"
        transition_staging(
            db,
            row,
            "INTEGRITY_FAILED",
            error_code=code,
            error_message=f"remote acquisition failed with HTTP {exc.code}",
        )
        raise ResourceStagingError(f"remote acquisition failed with HTTP {exc.code}") from exc
    except URLError as exc:
        transition_staging(
            db,
            row,
            "INTEGRITY_FAILED",
            error_code="NETWORK_ERROR",
            error_message=str(exc.reason),
        )
        raise ResourceStagingError(f"remote acquisition failed: {exc.reason}") from exc
    except ResourceStagingError as exc:
        transition_staging(
            db,
            row,
            "INTEGRITY_FAILED",
            error_code="REMOTE_ACQUISITION_REJECTED",
            error_message=str(exc),
        )
        raise
    except Exception as exc:
        transition_staging(
            db,
            row,
            "INTEGRITY_FAILED",
            error_code="REMOTE_ACQUISITION_FAILED",
            error_message=str(exc),
        )
        raise ResourceStagingError(f"remote acquisition failed: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
