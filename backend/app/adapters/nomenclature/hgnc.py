"""Runtime adapter for an organization-approved HGNC archive resource.

The adapter accepts only the exact manifest selected by the immutable analysis
resource plan. It verifies the manifest and both artifact digests again at
runtime before constructing the deterministic resolver.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from backend.app.domain.hgnc_crosswalk import (
    HGNC_ARCHIVE_RELEASE,
    HGNC_COMPLETE_URL,
    HGNC_LICENSE,
    HGNC_PUBLISHER,
    HGNC_WITHDRAWN_URL,
    HGNCResolution,
    HGNCResolver,
)


class HGNCArchiveProviderError(RuntimeError):
    """The approved HGNC archive is missing, changed or not executable."""


class HGNCArchiveProvider:
    provider_id = "HGNC"
    provider_version = "HGNC_ARCHIVE"
    supported_builds = frozenset()

    def __init__(self, *, resolver: HGNCResolver, manifest_sha256: str) -> None:
        self.resolver = resolver
        self.release = resolver.release
        self.sha256 = manifest_sha256
        self.complete_sha256 = resolver.complete_sha256
        self.withdrawn_sha256 = resolver.withdrawn_sha256
        self._resolution_cache: dict[str, HGNCResolution] = {}

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def from_execution_contract(
        cls,
        resolved: Any,
        *,
        expected_sha256: str | None = None,
    ) -> "HGNCArchiveProvider":
        contract = resolved.contract
        if contract.provider_id != cls.provider_id:
            raise HGNCArchiveProviderError("HGNC execution provider identity does not match")
        if contract.provider_version != str(resolved.resource_version):
            raise HGNCArchiveProviderError("HGNC execution release does not match the registered resource version")
        if contract.provider_version != HGNC_ARCHIVE_RELEASE:
            raise HGNCArchiveProviderError(
                f"unsupported HGNC release {contract.provider_version!r}; expected {HGNC_ARCHIVE_RELEASE}"
            )
        if contract.access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise HGNCArchiveProviderError("HGNC requires the governed local archive manifest")
        if not contract.location:
            raise HGNCArchiveProviderError("HGNC manifest location is required")

        toolchain = dict(contract.toolchain or {})
        expected = str(
            expected_sha256
            or toolchain.get("manifest_sha256")
            or toolchain.get("sha256")
            or ""
        ).strip().lower().removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise HGNCArchiveProviderError("HGNC requires the approved manifest SHA-256 pin")

        manifest_path = Path(contract.location).expanduser()
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise HGNCArchiveProviderError("HGNC manifest must be a regular, non-symlink file")
        manifest_path = manifest_path.resolve(strict=True)
        manifest_sha256 = cls._sha256(manifest_path)
        if manifest_sha256 != expected:
            raise HGNCArchiveProviderError("HGNC manifest SHA-256 does not match the approved resource")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HGNCArchiveProviderError(f"HGNC manifest is unreadable: {exc}") from exc

        expected_manifest_fields = {
            "schema": "siraloom.hgnc-acquisition.v1",
            "publisher": HGNC_PUBLISHER,
            "release": HGNC_ARCHIVE_RELEASE,
            "release_kind": "HGNC_QUARTERLY_ARCHIVE",
            "license": HGNC_LICENSE,
            "checksum_semantics": "LOCAL_SHA256; HGNC_DOES_NOT_PUBLISH_FILE_CHECKSUMS",
        }
        for field, value in expected_manifest_fields.items():
            if manifest.get(field) != value:
                raise HGNCArchiveProviderError(
                    f"HGNC manifest {field!r} does not match the approved source contract"
                )

        files = manifest.get("files")
        if not isinstance(files, list) or len(files) != 2:
            raise HGNCArchiveProviderError("HGNC manifest must declare exactly two archive artifacts")
        by_name = {str(item.get("filename") or ""): item for item in files if isinstance(item, dict)}
        if set(by_name) != {"hgnc_complete_set.txt", "withdrawn.txt"}:
            raise HGNCArchiveProviderError("HGNC manifest artifact set is incomplete or contains unexpected files")

        manifest_directory = manifest_path.parent.resolve(strict=True)
        artifact_paths: dict[str, Path] = {}
        for filename, expected_url in (
            ("hgnc_complete_set.txt", HGNC_COMPLETE_URL),
            ("withdrawn.txt", HGNC_WITHDRAWN_URL),
        ):
            item = by_name[filename]
            if item.get("source_url") != expected_url:
                raise HGNCArchiveProviderError(f"HGNC artifact source URL is not the pinned official URL: {filename}")
            expected_artifact_sha256 = str(item.get("sha256") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_artifact_sha256):
                raise HGNCArchiveProviderError(f"HGNC artifact SHA-256 is invalid: {filename}")
            candidate = manifest_directory / filename
            if candidate.is_symlink() or not candidate.is_file():
                raise HGNCArchiveProviderError(f"HGNC artifact is missing or is not a regular file: {filename}")
            artifact_path = candidate.resolve(strict=True)
            if artifact_path.parent != manifest_directory:
                raise HGNCArchiveProviderError(f"HGNC artifact resolves outside its managed release directory: {filename}")
            if artifact_path.stat().st_size != int(item.get("size_bytes") or -1):
                raise HGNCArchiveProviderError(f"HGNC artifact size does not match the manifest: {filename}")
            if cls._sha256(artifact_path) != expected_artifact_sha256:
                raise HGNCArchiveProviderError(f"HGNC artifact SHA-256 does not match the manifest: {filename}")
            artifact_paths[filename] = artifact_path

        try:
            resolver = HGNCResolver(
                artifact_paths["hgnc_complete_set.txt"],
                artifact_paths["withdrawn.txt"],
                release=HGNC_ARCHIVE_RELEASE,
                expected_complete_sha256=by_name["hgnc_complete_set.txt"]["sha256"],
                expected_withdrawn_sha256=by_name["withdrawn.txt"]["sha256"],
            )
        except Exception as exc:
            raise HGNCArchiveProviderError(f"HGNC resolver initialization failed: {exc}") from exc
        return cls(resolver=resolver, manifest_sha256=manifest_sha256)

    def resolve(self, identifier: str) -> HGNCResolution:
        key = str(identifier)
        if key not in self._resolution_cache:
            self._resolution_cache[key] = self.resolver.resolve(identifier)
        return self._resolution_cache[key]

    def resolve_many(self, identifiers: list[str] | tuple[str, ...]) -> tuple[HGNCResolution, ...]:
        return tuple(self.resolve(identifier) for identifier in identifiers)
