#!/usr/bin/env python3
"""Create, verify, and restore SIRALOOM laboratory data backups.

Backups include a PostgreSQL custom-format dump and the configured artifact,
reference, and resource-cache bind mounts. Restores always target a new database
and new, empty directories; this tool never overwrites a live database or tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

FORMAT = "siraloom-lab-backup-v1"
DATABASE_FILE = "database.dump"
STORAGE_ARCHIVES = {
    "artifacts": ("/data/siraloom/artifacts", "artifacts.tar.gz"),
    "references": ("/data/references", "references.tar.gz"),
    "resource_cache": ("/data/siraloom/resource-cache", "resource-cache.tar.gz"),
}


class BackupError(RuntimeError):
    """An operation could not safely complete."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    seen: set[str] = set()
    for member in members:
        name = PurePosixPath(member.name)
        if name.is_absolute() or not name.parts or ".." in name.parts:
            raise BackupError(f"Unsafe path in storage archive: {member.name!r}")
        if member.name in seen:
            raise BackupError(f"Duplicate path in storage archive: {member.name!r}")
        if not (member.isdir() or member.isfile()):
            raise BackupError(f"Unsupported file type in storage archive: {member.name!r}")
        seen.add(member.name)
    return members


def verify_bundle(bundle: Path) -> dict[str, Any]:
    """Verify checksums, archive structure, and required backup members."""
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise BackupError("Backup manifest.json is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("Backup manifest.json is unreadable or invalid") from exc
    if manifest.get("format") != FORMAT:
        raise BackupError("Unsupported backup format")
    files = manifest.get("files")
    expected_names = {DATABASE_FILE, *(name for _, name in STORAGE_ARCHIVES.values())}
    if not isinstance(files, dict) or set(files) != expected_names:
        raise BackupError("Manifest does not list the complete database and storage set")
    actual_names = {path.name for path in bundle.iterdir()}
    if actual_names != expected_names | {"manifest.json"}:
        raise BackupError("Backup directory contains missing or unmanifested files")
    for name, expected_digest in files.items():
        path = bundle / name
        if path.is_symlink() or not path.is_file():
            raise BackupError(f"Backup member is missing or not a regular file: {name}")
        if not isinstance(expected_digest, str) or sha256_file(path) != expected_digest:
            raise BackupError(f"SHA-256 verification failed for {name}")
        if name.endswith(".tar.gz"):
            try:
                with tarfile.open(path, "r:gz") as archive:
                    _safe_members(archive)
            except (OSError, tarfile.TarError) as exc:
                raise BackupError(f"Storage archive is invalid: {name}") from exc
    with (bundle / DATABASE_FILE).open("rb") as dump:
        if dump.read(5) != b"PGDMP":
            raise BackupError("database.dump is not a PostgreSQL custom-format archive")
    return manifest


def _run(
    command: list[str], *, cwd: Path, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except OSError as exc:
        raise BackupError(f"Could not execute {command[0]}: {exc}") from exc
    if result.returncode:
        details = (result.stderr or "").strip() if capture else ""
        raise BackupError(f"Command failed ({result.returncode}): {' '.join(command)} {details}")
    return result


def _compose_command(
    compose_file: Path, *, project_name: str | None = None, env_file: Path | None = None
) -> list[str]:
    command = ["docker", "compose"]
    if project_name:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project_name):
            raise BackupError("Compose project name contains unsupported characters")
        command.extend(["-p", project_name])
    if env_file:
        command.extend(["--env-file", str(env_file)])
    command.extend(["-f", str(compose_file)])
    return command


def _compose_config(
    root: Path,
    compose_file: Path,
    *,
    project_name: str | None = None,
    env_file: Path | None = None,
) -> dict[str, Any]:
    result = _run(
        [
            *_compose_command(compose_file, project_name=project_name, env_file=env_file),
            "config",
            "--format",
            "json",
        ],
        cwd=root,
        capture=True,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackupError("Docker Compose returned invalid JSON configuration") from exc


def _volume_sources(config: dict[str, Any]) -> dict[str, Path]:
    services = config.get("services") or {}
    result: dict[str, Path] = {}
    for key, (target, _) in STORAGE_ARCHIVES.items():
        mounts = (services.get("api") or {}).get("volumes") or []
        matches = [mount for mount in mounts if mount.get("target") == target]
        if len(matches) != 1:
            raise BackupError(f"Expected one API bind mount at {target}")
        mount = matches[0]
        source = mount.get("source")
        if mount.get("type") != "bind" or not source or not Path(source).is_absolute():
            raise BackupError(f"{target} must use an absolute host bind mount for backup")
        path = Path(source).resolve(strict=True)
        if not path.is_dir():
            raise BackupError(f"Configured storage source is not a directory: {target}")
        result[key] = path
    postgres_mounts = (services.get("postgres") or {}).get("volumes") or []
    if not any(mount.get("target") == "/var/lib/postgresql/data" for mount in postgres_mounts):
        raise BackupError("PostgreSQL data directory is not configured in Compose")
    return result


def _archive_tree(source: Path, destination: Path) -> None:
    with tarfile.open(destination, "w:gz", compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise BackupError(
                    f"Storage tree contains a symlink; refusing ambiguous backup: {path}"
                )
            if not (path.is_dir() or path.is_file()):
                raise BackupError(f"Storage tree contains an unsupported file type: {path}")
            archive.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)


def _write_manifest(bundle: Path, *, commit: str, database: str) -> None:
    files = [DATABASE_FILE, *(name for _, name in STORAGE_ARCHIVES.values())]
    manifest = {
        "format": FORMAT,
        "created_at": datetime.now(UTC).isoformat(),
        "repository_commit": commit,
        "database": database,
        "storage_targets": {key: target for key, (target, _) in STORAGE_ARCHIVES.items()},
        "files": {name: sha256_file(bundle / name) for name in files},
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def create_backup(
    root: Path,
    compose_file: Path,
    output: Path,
    *,
    project_name: str | None = None,
    env_file: Path | None = None,
) -> None:
    root = root.resolve(strict=True)
    compose_file = (
        (root / compose_file).resolve(strict=True)
        if not compose_file.is_absolute()
        else compose_file.resolve(strict=True)
    )
    if env_file is not None:
        env_file = (
            (root / env_file).resolve(strict=True)
            if not env_file.is_absolute()
            else env_file.resolve(strict=True)
        )
    output = output.absolute()
    if output.exists():
        raise BackupError(f"Backup destination already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    config = _compose_config(root, compose_file, project_name=project_name, env_file=env_file)
    storage_sources = _volume_sources(config)
    postgres = (config.get("services") or {}).get("postgres") or {}
    environment = postgres.get("environment") or {}
    database = str(environment.get("POSTGRES_DB") or "").strip()
    user = str(environment.get("POSTGRES_USER") or "").strip()
    if not database or not user:
        raise BackupError("Compose postgres service must define POSTGRES_DB and POSTGRES_USER")

    staged = output.parent / f".{output.name}.tmp-{os.getpid()}"
    if staged.exists():
        raise BackupError(f"Temporary backup path already exists: {staged}")
    staged.mkdir(mode=0o700)
    compose = _compose_command(compose_file, project_name=project_name, env_file=env_file)
    running: list[str] = []
    stopped = False
    try:
        running_result = _run(
            [*compose, "ps", "--services", "--status", "running"], cwd=root, capture=True
        )
        running = [
            name for name in running_result.stdout.splitlines() if name in {"api", "worker", "beat"}
        ]
        if running:
            # Restart the original running set even if Compose reports a
            # partial stop failure.
            stopped = True
            _run([*compose, "stop", "--timeout", "300", *running], cwd=root)
        dump_path = staged / DATABASE_FILE
        with dump_path.open("wb") as dump:
            process = subprocess.run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    f"--username={user}",
                    f"--dbname={database}",
                ],
                cwd=root,
                stdout=dump,
                check=False,
            )
        if process.returncode:
            raise BackupError(f"pg_dump failed with exit code {process.returncode}")
        for key, (_, archive_name) in STORAGE_ARCHIVES.items():
            _archive_tree(storage_sources[key], staged / archive_name)
        commit_result = _run(["git", "rev-parse", "HEAD"], cwd=root, capture=True)
        _write_manifest(staged, commit=commit_result.stdout.strip(), database=database)
        verify_bundle(staged)
        os.replace(staged, output)
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    finally:
        if stopped and running:
            _run([*compose, "start", *running], cwd=root)


def _extract_tree(archive_path: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in _safe_members(archive):
            relative = PurePosixPath(member.name)
            target = destination.joinpath(*relative.parts)
            target_resolved = target.resolve(strict=False)
            if not target_resolved.is_relative_to(destination.resolve()):
                raise BackupError(f"Archive path escapes restore directory: {member.name!r}")
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.chmod(target, 0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise BackupError(f"Cannot read archive member: {member.name!r}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(target, member.mode & 0o700)


def restore_backup(
    root: Path,
    compose_file: Path,
    bundle: Path,
    target_database: str,
    targets: dict[str, Path],
    *,
    project_name: str | None = None,
    env_file: Path | None = None,
) -> None:
    root = root.resolve(strict=True)
    compose_file = (
        (root / compose_file).resolve(strict=True)
        if not compose_file.is_absolute()
        else compose_file.resolve(strict=True)
    )
    if env_file is not None:
        env_file = (
            (root / env_file).resolve(strict=True)
            if not env_file.is_absolute()
            else env_file.resolve(strict=True)
        )
    bundle = bundle.resolve(strict=True)
    manifest = verify_bundle(bundle)
    if not re.fullmatch(r"siraloom_restore_[a-z0-9_]{1,48}", target_database):
        raise BackupError("Restore database must match siraloom_restore_[a-z0-9_]{1,48}")
    if target_database == manifest["database"]:
        raise BackupError("Restore database must differ from the source database")
    if set(targets) != set(STORAGE_ARCHIVES):
        raise BackupError(
            "Restore requires exactly the artifacts, references, and resource-cache targets"
        )
    for key, target in targets.items():
        if not target.is_absolute() or target.exists():
            raise BackupError(
                f"Restore target must be an absolute, not-yet-existing path: {target}"
            )
        if not target.parent.is_dir():
            raise BackupError(
                f"Restore target parent directory must already exist: {target.parent}"
            )

    config = _compose_config(root, compose_file, project_name=project_name, env_file=env_file)
    postgres = (config.get("services") or {}).get("postgres") or {}
    environment = postgres.get("environment") or {}
    user = str(environment.get("POSTGRES_USER") or "").strip()
    current_database = str(environment.get("POSTGRES_DB") or "").strip()
    if not user:
        raise BackupError("Compose postgres service must define POSTGRES_USER")
    if target_database == current_database:
        raise BackupError("Restore database must differ from the currently configured database")
    compose = _compose_command(compose_file, project_name=project_name, env_file=env_file)
    stages: dict[str, Path] = {}
    installed_targets: list[Path] = []
    created_database = False
    try:
        for key, target in targets.items():
            stage_root = Path(
                tempfile.mkdtemp(prefix=f".{target.name}.restore-", dir=target.parent)
            )
            stage = stage_root / "tree"
            stages[key] = stage
            _extract_tree(bundle / STORAGE_ARCHIVES[key][1], stage)

        _run(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "createdb",
                f"--username={user}",
                f"--owner={user}",
                "--template=template0",
                target_database,
            ],
            cwd=root,
        )
        created_database = True
        with (bundle / DATABASE_FILE).open("rb") as dump:
            process = subprocess.run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                    f"--username={user}",
                    f"--dbname={target_database}",
                ],
                cwd=root,
                stdin=dump,
                check=False,
            )
        if process.returncode:
            raise BackupError(f"pg_restore failed with exit code {process.returncode}")

        for key, target in targets.items():
            target.mkdir(mode=0o700)
            installed_targets.append(target)
            for child in stages[key].iterdir():
                os.rename(child, target / child.name)
            stages[key].rmdir()
            stages[key].parent.rmdir()
        print(
            json.dumps(
                {
                    "status": "RESTORED_TO_NEW_TARGETS",
                    "database": target_database,
                    "directories": {key: str(target) for key, target in targets.items()},
                    "source_commit": manifest["repository_commit"],
                    "next_action": "Review the restored database and files, then update .env explicitly before starting application writers.",
                },
                indent=2,
            )
        )
    except Exception:
        for stage in stages.values():
            shutil.rmtree(stage.parent, ignore_errors=True)
        for target in installed_targets:
            shutil.rmtree(target, ignore_errors=True)
        if created_database:
            _run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "postgres",
                    "dropdb",
                    "--if-exists",
                    f"--username={user}",
                    target_database,
                ],
                cwd=root,
            )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify", help="verify manifest, hashes, and archive safety")
    verify.add_argument("bundle", type=Path)

    create = subparsers.add_parser("create", help="quiesce Compose writers and create a backup")
    create.add_argument("output", type=Path, help="new output directory; it must not exist")
    create.add_argument("--root", type=Path, default=Path.cwd())
    create.add_argument("--compose-file", type=Path, default=Path("docker-compose.production.yml"))
    create.add_argument("--project-name")
    create.add_argument("--env-file", type=Path)

    restore = subparsers.add_parser(
        "restore", help="restore to a new database and empty directories"
    )
    restore.add_argument("bundle", type=Path)
    restore.add_argument(
        "--database", required=True, help="new database name starting siraloom_restore_"
    )
    restore.add_argument("--artifacts-target", required=True, type=Path)
    restore.add_argument("--references-target", required=True, type=Path)
    restore.add_argument("--resource-cache-target", required=True, type=Path)
    restore.add_argument("--root", type=Path, default=Path.cwd())
    restore.add_argument("--compose-file", type=Path, default=Path("docker-compose.production.yml"))
    restore.add_argument("--project-name")
    restore.add_argument("--env-file", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "verify":
            manifest = verify_bundle(args.bundle.resolve(strict=True))
            print(json.dumps({"status": "VERIFIED", "manifest": manifest}, indent=2))
        elif args.command == "create":
            create_backup(
                args.root,
                args.compose_file,
                args.output,
                project_name=args.project_name,
                env_file=args.env_file,
            )
            print(
                json.dumps(
                    {"status": "CREATED_AND_VERIFIED", "bundle": str(args.output.absolute())},
                    indent=2,
                )
            )
        else:
            restore_backup(
                args.root,
                args.compose_file,
                args.bundle,
                args.database,
                {
                    "artifacts": args.artifacts_target,
                    "references": args.references_target,
                    "resource_cache": args.resource_cache_target,
                },
                project_name=args.project_name,
                env_file=args.env_file,
            )
        return 0
    except (BackupError, OSError, tarfile.TarError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
