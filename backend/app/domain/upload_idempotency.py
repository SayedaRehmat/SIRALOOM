"""Pure functions for tenant-scoped artifact upload idempotency."""
import hashlib
import json
from uuid import UUID


def idempotency_key_sha256(value: str | None) -> str | None:
    """Validate and hash an opaque client key without persisting the raw value."""
    if value is None:
        return None
    if not isinstance(value, str) or not 16 <= len(value) <= 255:
        raise ValueError("Idempotency-Key must contain between 16 and 255 characters.")
    if value != value.strip() or any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise ValueError("Idempotency-Key must contain printable non-whitespace ASCII characters.")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def upload_request_fingerprint(
    *,
    content_sha256: str,
    size_bytes: int,
    filename: str,
    artifact_type: str,
    media_type: str | None,
    genome_build: str | None,
    specimen_id: UUID | None,
    paired_artifact_id: UUID | None,
    caller_attestation_sha256: str | None = None,
) -> str:
    """Bind a key to bytes and every upload field that changes artifact meaning."""
    identity = {
        "content_sha256": content_sha256,
        "size_bytes": int(size_bytes),
        "filename": filename,
        "artifact_type": artifact_type,
        "media_type": media_type,
        "genome_build": genome_build,
        "specimen_id": str(specimen_id) if specimen_id else None,
        "paired_artifact_id": str(paired_artifact_id) if paired_artifact_id else None,
        "caller_attestation_sha256": caller_attestation_sha256,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
