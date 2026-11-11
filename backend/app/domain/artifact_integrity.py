"""Byte-level integrity checks for persisted artifacts."""

import hashlib
import os
import re
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile


class ArtifactIntegrityError(ValueError):
    """Raised when stored bytes do not match their persisted identity."""


def stage_verified_cloud_artifact(store, artifact, *, prefix: str) -> Path:
    """Download to a private temporary file and verify before HTTP delivery."""
    validate_integrity_expectations(artifact.sha256, artifact.size_bytes)
    suffix = "".join(Path(artifact.filename).suffixes) or ".bin"
    with NamedTemporaryFile(prefix=prefix, suffix=suffix, delete=False) as handle:
        path = Path(handle.name)
    try:
        store.download_to_file(
            artifact.storage_uri,
            path,
            expected_sha256=artifact.sha256,
            expected_size_bytes=artifact.size_bytes,
        )
        verify_artifact_file(
            path,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
        )
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise ArtifactIntegrityError(
            "Artifact is unavailable or failed integrity verification."
        ) from exc
    return path


def validate_integrity_expectations(sha256: str | None, size_bytes: int | None) -> None:
    if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None:
        raise ArtifactIntegrityError("Artifact SHA-256 metadata is missing or invalid.")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise ArtifactIntegrityError("Artifact size metadata is missing or invalid.")


def verify_artifact_file(path: Path, *, sha256: str | None, size_bytes: int | None) -> None:
    """Verify a file against the artifact row before scientific use or delivery."""
    validate_integrity_expectations(sha256, size_bytes)
    candidate = Path(path)
    # Reject symlinks in every path component, not merely the final filename.
    # This prevents a path that was originally inside an artifact root from
    # being redirected through a symlink before the integrity check.
    absolute = candidate.absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            component_stat = current.lstat()
        except FileNotFoundError as exc:
            raise ArtifactIntegrityError("Artifact path is missing during integrity verification.") from exc
        if stat.S_ISLNK(component_stat.st_mode):
            raise ArtifactIntegrityError("Artifact path contains a symbolic link.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute, flags)
    except OSError as exc:
        raise ArtifactIntegrityError("Artifact cannot be opened safely for integrity verification.") from exc
    digest = hashlib.sha256()
    actual_size = 0
    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ArtifactIntegrityError("Artifact integrity verification requires a regular file.")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
                actual_size += len(chunk)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if actual_size != size_bytes or digest.hexdigest().lower() != sha256.lower():
        raise ArtifactIntegrityError("Artifact bytes do not match persisted SHA-256 and size metadata.")
