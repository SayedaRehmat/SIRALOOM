"""Provider-neutral staged scientific resource lifecycle primitives.

This module intentionally does not download arbitrary URLs. Providers must supply
an explicit staging adapter and integrity metadata; automatic discovery alone
never activates a resource.
"""

from dataclasses import dataclass
from pathlib import Path
from hashlib import sha256
from typing import Protocol


class ResourceStagingError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedResource:
    source: str
    local_path: str
    sha256: str
    size_bytes: int
    metadata: dict[str, object]


class ResourceStager(Protocol):
    def stage(self, descriptor: dict[str, object], destination: Path) -> StagedResource:
        ...


def verify_staged_resource(path: Path, expected_sha256: str) -> StagedResource:
    if not path.is_file():
        raise ResourceStagingError("staged resource file does not exist")
    digest = sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected_sha256.lower():
        raise ResourceStagingError(
            f"staged resource checksum mismatch: expected {expected_sha256}, got {actual}"
        )
    return StagedResource(
        source="verified-local-staging",
        local_path=str(path),
        sha256=actual,
        size_bytes=size,
        metadata={"integrity": "SHA-256"},
    )


def stage_and_verify(
    stager: ResourceStager,
    descriptor: dict[str, object],
    destination: Path,
    expected_sha256: str,
) -> StagedResource:
    staged = stager.stage(descriptor, destination)
    verified = verify_staged_resource(Path(staged.local_path), expected_sha256)
    return StagedResource(
        source=staged.source,
        local_path=verified.local_path,
        sha256=verified.sha256,
        size_bytes=verified.size_bytes,
        metadata={**staged.metadata, **verified.metadata},
    )
