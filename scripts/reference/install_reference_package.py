#!/usr/bin/env python3
"""Install a qualified reference package into a deployment-owned durable filesystem.

The installer copies every byte-bearing package asset into one versioned directory,
verifies each copy, rewrites the manifest to the installed paths, and atomically
publishes the directory. It never registers, qualifies, or activates a resource.
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
    """A durable reference-package installation failure."""


_ASSET_FIELDS = (
    ("fasta_path", "sequences"),
    ("fai_path", "sequences"),
    ("dictionary_path", "sequences"),
    ("gzi_path", "sequences"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file() or source.is_symlink():
        raise InstallError(f"reference package asset is missing or is a symlink: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(1024 * 1024):
            writer.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    observed = digest.hexdigest()
    source_digest = _sha256(source)
    if observed != source_digest or size != source.stat().st_size:
        raise InstallError(f"copied asset failed byte verification: {source}")
    return {"path": destination.relative_to(destination.parents[1]).as_posix(),
            "size_bytes": size, "sha256": observed}


def _safe_asset(source_value: Any, field: str, base: Path) -> Path:
    if not isinstance(source_value, str) or not source_value.strip():
        raise InstallError(f"manifest is missing required asset path {field!r}")
    source = Path(source_value).expanduser()
    if not source.is_absolute():
        source = base / source
    source = source.resolve(strict=True)
    if not source.is_file():
        raise InstallError(f"manifest asset {field!r} is not a file: {source}")
    return source


def _verify_existing(destination: Path, package_checksum: str) -> dict[str, Any]:
    manifest_path = destination / "reference-package.json"
    if not manifest_path.is_file():
        raise InstallError(
            f"destination already exists without an install manifest: {destination}"
        )
    installed = json.loads(manifest_path.read_text(encoding="utf-8"))
    if installed.get("package_checksum") != package_checksum:
        raise InstallError(
            "destination contains a different reference package; refusing to overwrite"
        )
    inventory = installed.get("durable_install", {}).get("assets")
    if not isinstance(inventory, list) or not inventory:
        raise InstallError("existing installation has no durable asset inventory")
    for item in inventory:
        relative = Path(str(item.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise InstallError("existing install inventory contains an unsafe path")
        asset = destination / relative
        if not asset.is_file() or asset.is_symlink():
            raise InstallError(f"installed asset is missing or unsafe: {relative}")
        if asset.stat().st_size != item.get("size_bytes") or _sha256(asset) != item.get("sha256"):
            raise InstallError(f"installed asset integrity check failed: {relative}")
    return installed


def install_reference_package(manifest_path: Path, storage_root: Path) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    if not manifest_path.is_file():
        raise InstallError(f"package manifest is not a file: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    package_version = str(manifest.get("package_version") or "").strip()
    package_checksum = str(manifest.get("package_checksum") or "").strip().lower()
    if not package_version or not package_checksum:
        raise InstallError("manifest must declare package_version and package_checksum")
    if len(package_checksum) != 64 or any(c not in "0123456789abcdef" for c in package_checksum):
        raise InstallError("manifest package_checksum must be a SHA-256 hex digest")
    if any(part in {"", ".", ".."} for part in Path(package_version).parts) or "/" in package_version or "\\\\" in package_version:
        raise InstallError("package_version is not a safe directory name")

    root = storage_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise InstallError("storage root must be a real directory, not a symlink")
    destination = root / package_version
    if destination.exists():
        return _verify_existing(destination, package_checksum)

    temporary = Path(tempfile.mkdtemp(prefix=f".{package_version}.staging-", dir=root))
    try:
        assets: list[dict[str, Any]] = []
        copied_paths: dict[str, str] = {}

        for field, subdirectory in _ASSET_FIELDS:
            source_value = manifest.get(field)
            if source_value is None and field == "gzi_path":
                continue
            source = _safe_asset(source_value, field, manifest_path.parent)
            relative = Path(subdirectory) / source.name
            if relative.as_posix() in {item["path"] for item in assets}:
                raise InstallError(f"asset filename collision while installing {field}")
            evidence = _copy_verified(source, temporary / relative)
            evidence["path"] = relative.as_posix()
            assets.append(evidence)
            copied_paths[field] = str((destination / relative).resolve(strict=False))

        publisher = manifest.get("source_contract", {}).get("publisher_checksum_evidence", {})
        for field, source_key in (
            ("evidence_file_path", "source"),
            ("verified_artifact_path", "source"),
        ):
            source_value = publisher.get(field)
            if not source_value:
                raise InstallError(f"publisher checksum evidence is missing {field}")
            source = _safe_asset(source_value, f"source_contract.publisher_checksum_evidence.{field}", manifest_path.parent)
            relative = Path(source_key) / source.name
            if relative.as_posix() in {item["path"] for item in assets}:
                raise InstallError(f"publisher evidence filename collision: {relative.name}")
            evidence = _copy_verified(source, temporary / relative)
            evidence["path"] = relative.as_posix()
            assets.append(evidence)
            publisher[field] = str((destination / relative).resolve(strict=False))

        for field, installed_path in copied_paths.items():
            manifest[field] = installed_path
        execution = manifest.setdefault("execution", {})
        execution["location"] = copied_paths["fasta_path"]
        manifest.setdefault("source_contract", {})["publisher_checksum_evidence"] = publisher
        manifest["durable_install"] = {
            "schema_version": "1",
            "status": "PUBLISHED",
            "storage_backend": "LOCAL_FILESYSTEM",
            "storage_root": str(root),
            "package_directory": str(destination),
            "package_checksum": package_checksum,
            "assets": assets,
        }

        installed_manifest = temporary / "reference-package.json"
        with installed_manifest.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\\n")
            handle.flush()
            os.fsync(handle.fileno())

        # The package directory becomes visible in one same-filesystem rename.
        os.rename(temporary, destination)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return _verify_existing(destination, package_checksum)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True,
                        help="deployment-owned persistent mount; must not be an ephemeral job directory")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = install_reference_package(args.manifest, args.storage_root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    print(json.dumps({
        "status": result["durable_install"]["status"],
        "package_version": result["package_version"],
        "package_checksum": result["package_checksum"],
        "package_directory": result["durable_install"]["package_directory"],
        "asset_count": len(result["durable_install"]["assets"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
