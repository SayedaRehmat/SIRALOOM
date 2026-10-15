"""Byte-level integrity checks for persisted artifacts."""

import hashlib
import re
from pathlib import Path


class ArtifactIntegrityError(ValueError):
    """Raised when stored bytes do not match their persisted identity."""


def validate_integrity_expectations(sha256: str | None, size_bytes: int | None) -> None:
    if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None:
        raise ArtifactIntegrityError("Artifact SHA-256 metadata is missing or invalid.")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise ArtifactIntegrityError("Artifact size metadata is missing or invalid.")


def verify_artifact_file(path: Path, *, sha256: str | None, size_bytes: int | None) -> None:
    """Verify a file against the artifact row before scientific use or delivery."""
    validate_integrity_expectations(sha256, size_bytes)
    digest = hashlib.sha256()
    actual_size = 0
    with Path(path).open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
            actual_size += len(chunk)
    if actual_size != size_bytes or digest.hexdigest().lower() != sha256.lower():
        raise ArtifactIntegrityError("Artifact bytes do not match persisted SHA-256 and size metadata.")
