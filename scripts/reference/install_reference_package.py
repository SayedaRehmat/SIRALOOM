#!/usr/bin/env python3
"""Install a reference package into a deployment-provided persistent filesystem.

Copies all reference and publisher-evidence assets, verifies copied bytes, rewrites
manifest paths, then atomically publishes one immutable version directory. This
does not register, qualify, approve, or activate the package. Persistence depends
on the deployment supplying a genuinely persistent mount as --storage-root.
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


def _safe_asset(value: Any, field: str, base: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise InstallError(f"manifest is missing required asset path {field!r}")
    candidate = Path(value).expanduser()
    if candidate.is_symlink():
        raise InstallError(f"manifest asset {field!r} must not be a symlink")
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise InstallError(f"manifest asset {field!r} is not a file: {resolved}")
    return resolved


def _copy_verified(source: Path, destination: Path, relative: Path) -> dict[str, Any]:
    if not source.is_file():
        raise InstallError(f"reference package asset is missing: {source}")
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
    if observed != _sha256(source) or size != source.stat().st_size:
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
        raise InstallError("existing installation has no verified durable asset inventory")
    for item in inventory:
        relative = Path(str(item.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise InstallError("existing install inventory contains an unsafe path")
        asset = destination / relative
        if asset.is_symlink() or not asset.is_file():
            raise InstallError(f"installed asset is missing or unsafe: {relative}")
        if asset.stat().st_size != item.get("size_bytes") or _sha256(asset) != item.get("sha256"):
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

    publisher = manifest.get("source_contract", {}).get("publisher_checksum_evidence", {})
    sources: list[tuple[str, Path, Path]] = []
    for field, subdirectory in _ASSET_FIELDS:
        value = manifest.get(field)
        if value is None and field == "gzi_path":
            continue
        source = _safe_asset(value, field, manifest_path.parent)
        sources.append((field, source, Path(subdirectory) / source.name))
    for field in ("evidence_file_path", "verified_artifact_path"):
        source = _safe_asset(
            publisher.get(field),
            f"source_contract.publisher_checksum_evidence.{field}",
            manifest_path.parent,
        )
        sources.append((field, source, Path("source") / source.name))

    relative_names = [relative.as_posix() for _field, _source, relative in sources]
    if len(relative_names) != len(set(relative_names)):
        raise InstallError("reference package contains colliding asset filenames")
    required_bytes = sum(source.stat().st_size for _field, source, _relative in sources)
    available_bytes = shutil.disk_usage(root).free
    if available_bytes < required_bytes:
        raise InstallError(f"insufficient storage: need {required_bytes} bytes, have {available_bytes}")

    temporary = Path(tempfile.mkdtemp(prefix=f".{version}.staging-", dir=root))
    try:
        inventory: list[dict[str, Any]] = []
        installed_paths: dict[str, str] = {}
        for field, source, relative in sources:
            inventory.append(_copy_verified(source, temporary / relative, relative))
            installed_paths[field] = str(destination / relative)

        for field in ("fasta_path", "fai_path", "dictionary_path", "gzi_path"):
            if field in installed_paths:
                manifest[field] = installed_paths[field]
        publisher["evidence_file_path"] = installed_paths["evidence_file_path"]
        publisher["verified_artifact_path"] = installed_paths["verified_artifact_path"]
        manifest.setdefault("source_contract", {})["publisher_checksum_evidence"] = publisher
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
