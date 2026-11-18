#!/usr/bin/env python3
"""Install a reference package into a deployment-provided persistent filesystem.

Copies every reference and publisher-evidence asset, verifies copied bytes against
manifest digests, rewrites paths, and atomically publishes one immutable version
directory. It never registers, qualifies, approves, or activates the package.
Persistence depends on the deployment supplying a genuinely persistent mount.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


class InstallError(RuntimeError):
    """A reference-package installation failure."""


_ASSET_FIELDS = (
    ("fasta_path", "sequences", "fasta_sha256"),
    ("fai_path", "sequences", "fai_sha256"),
    ("dictionary_path", "sequences", "dictionary_sha256"),
    ("gzi_path", "sequences", "gzi_sha256"),
)


def _digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.md5(usedforsecurity=False) if algorithm == "md5" else hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_asset(value: Any, field: str, base: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise InstallError(f"manifest is missing required asset path {field!r}")
    candidate = Path(value).expanduser()
    if any(parent.is_symlink() for parent in (candidate, *candidate.parents)):
        raise InstallError(f"manifest asset {field!r} must not traverse a symlink")
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise InstallError(f"manifest asset {field!r} is not a file: {resolved}")
    return resolved


def _copy_verified(
    source: Path,
    destination: Path,
    relative: Path,
    *,
    expected_sha256: str,
    expected_size_bytes: int | None = None,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(1024 * 1024):
            writer.write(chunk)
            hasher.update(chunk)
            size += len(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    observed = hasher.hexdigest()
    if observed != expected_sha256.lower():
        raise InstallError(f"asset SHA-256 does not match manifest: {source}")
    if expected_size_bytes is not None and size != expected_size_bytes:
        raise InstallError(f"asset size does not match manifest: {source}")
    if size != source.stat().st_size or observed != _digest(source, "sha256"):
        raise InstallError(f"copied asset failed byte verification: {source}")
    return {"path": relative.as_posix(), "size_bytes": size, "sha256": observed}


def _verify_existing(destination: Path, package_checksum: str) -> dict[str, Any]:
    manifest_path = destination / "reference-package.json"
    if not manifest_path.is_file():
        raise InstallError(f"destination exists without an install manifest: {destination}")
    installed = json.loads(manifest_path.read_text(encoding="utf-8"))
    if installed.get("package_checksum") != package_checksum:
        raise InstallError("destination contains a different reference package; refusing to overwrite")
    install = installed.get("durable_install") or {}
    inventory = install.get("assets")
    if install.get("status") != "INSTALLED_VERIFIED" or not isinstance(inventory, list) or not inventory:
        raise InstallError("existing installation has no verified asset inventory")
    package_root = destination.resolve()
    for item in inventory:
        relative = Path(str(item.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise InstallError("existing install inventory contains an unsafe path")
        asset = destination / relative
        try:
            asset.resolve(strict=True).relative_to(package_root)
        except (OSError, ValueError) as exc:
            raise InstallError(f"installed asset escapes package directory: {relative}") from exc
        if any(parent.is_symlink() for parent in (asset, *asset.parents) if parent != destination.parent):
            raise InstallError(f"installed asset traverses a symlink: {relative}")
        if not asset.is_file():
            raise InstallError(f"installed asset is missing: {relative}")
        if asset.stat().st_size != item.get("size_bytes") or _digest(asset, "sha256") != item.get("sha256"):
            raise InstallError(f"installed asset integrity check failed: {relative}")
    return installed


def install_reference_package(manifest_path: Path, storage_root: Path) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    if not manifest_path.is_file():
        raise InstallError(f"package manifest is not a file: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("package_version") or "").strip()
    checksum = str(manifest.get("package_checksum") or "").strip().lower()
    if not version or not checksum:
        raise InstallError("manifest must declare package_version and package_checksum")
    if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
        raise InstallError("manifest package_checksum must be a SHA-256 hex digest")
    if version in {".", ".."} or "/" in version or "\\" in version:
        raise InstallError("package_version is not a safe directory name")

    raw_root = storage_root.expanduser()
    if raw_root.is_symlink():
        raise InstallError("storage root must not be a symlink")
    root = raw_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise InstallError("storage root must be a directory")
    destination = root / version
    if destination.exists():
        return _verify_existing(destination, checksum)

    source_contract = manifest.get("source_contract")
    if not isinstance(source_contract, dict):
        raise InstallError("manifest source_contract must be an object")
    publisher = source_contract.get("publisher_checksum_evidence")
    if not isinstance(publisher, dict):
        raise InstallError("manifest publisher checksum evidence must be an object")

    sources: list[tuple[str, Path, Path, str, int | None]] = []
    for field, subdirectory, digest_field in _ASSET_FIELDS:
        value = manifest.get(field)
        if value is None and field == "gzi_path":
            continue
        source = _safe_asset(value, field, manifest_path.parent)
        expected = str(manifest.get(digest_field) or "").strip().lower()
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise InstallError(f"manifest is missing a valid SHA-256 for {field}")
        size = manifest.get("fasta_size_bytes") if field == "fasta_path" else None
        sources.append((field, source, Path(subdirectory) / source.name, expected, size))

    checksum_path = _safe_asset(
        publisher.get("evidence_file_path"),
        "source_contract.publisher_checksum_evidence.evidence_file_path",
        manifest_path.parent,
    )
    checksum_sha = str(publisher.get("evidence_file_sha256") or "").strip().lower()
    if len(checksum_sha) != 64 or _digest(checksum_path, "sha256") != checksum_sha:
        raise InstallError("publisher checksum manifest SHA-256 does not match its declared evidence")

    compressed_path = _safe_asset(
        publisher.get("verified_artifact_path"),
        "source_contract.publisher_checksum_evidence.verified_artifact_path",
        manifest_path.parent,
    )
    expected_md5 = str(publisher.get("expected_digest") or "").strip().lower()
    if publisher.get("algorithm") != "md5" or len(expected_md5) != 32:
        raise InstallError("publisher checksum evidence must declare a valid MD5")
    if _digest(compressed_path, "md5") != expected_md5:
        raise InstallError("compressed publisher artifact does not match publisher MD5")
    sources.extend((
        ("evidence_file_path", checksum_path, Path("source") / checksum_path.name, checksum_sha, None),
        ("verified_artifact_path", compressed_path, Path("source") / compressed_path.name,
         _digest(compressed_path, "sha256"), None),
    ))

    relative_names = [relative.as_posix() for _field, _source, relative, _digest_value, _size in sources]
    if len(relative_names) != len(set(relative_names)):
        raise InstallError("reference package contains colliding asset filenames")
    required_bytes = sum(source.stat().st_size for _field, source, _relative, _digest_value, _size in sources)
    available_bytes = shutil.disk_usage(root).free
    if available_bytes < required_bytes:
        raise InstallError(f"insufficient storage: need {required_bytes} bytes, have {available_bytes}")

    temporary = Path(tempfile.mkdtemp(prefix=f".{version}.staging-", dir=root))
    try:
        inventory: list[dict[str, Any]] = []
        installed_paths: dict[str, str] = {}
        for field, source, relative, expected, expected_size in sources:
            inventory.append(_copy_verified(
                source, temporary / relative, relative,
                expected_sha256=expected, expected_size_bytes=expected_size,
            ))
            installed_paths[field] = str(destination / relative)

        for field in ("fasta_path", "fai_path", "dictionary_path", "gzi_path"):
            if field in installed_paths:
                manifest[field] = installed_paths[field]
        publisher["evidence_file_path"] = installed_paths["evidence_file_path"]
        publisher["verified_artifact_path"] = installed_paths["verified_artifact_path"]
        source_contract["publisher_checksum_evidence"] = publisher
        manifest["source_contract"] = source_contract
        manifest.setdefault("execution", {})["location"] = installed_paths["fasta_path"]
        manifest["durable_install"] = {
            "schema_version": "1",
            "status": "INSTALLED_VERIFIED",
            "storage_backend": "LOCAL_FILESYSTEM",
            "persistence_guarantee": "DEPLOYMENT_MOUNT_DEPENDENT",
            "storage_root": str(root),
            "package_directory": str(destination),
            "package_checksum": checksum,
            "preflight": {
                "required_bytes": required_bytes,
                "available_bytes": available_bytes,
                "passed": True,
            },
            "assets": inventory,
        }

        with (temporary / "reference-package.json").open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Persist directory entries before atomically exposing the package.
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        os.rename(temporary, destination)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return _verify_existing(destination, checksum)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True,
                        help="deployment-provided persistent mount, not an ephemeral job directory")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = install_reference_package(args.manifest, args.storage_root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["durable_install"]["status"],
        "package_version": result["package_version"],
        "package_checksum": result["package_checksum"],
        "package_directory": result["durable_install"]["package_directory"],
        "asset_count": len(result["durable_install"]["assets"]),
        "persistence_guarantee": result["durable_install"]["persistence_guarantee"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
