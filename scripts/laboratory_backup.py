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

FORMAT_V1 = "siraloom-lab-backup-v1"
FORMAT = "siraloom-lab-backup-v2"
DATABASE_FILE = "database.dump"
STORAGE_ARCHIVES = {
    "artifacts": ("/data/siraloom/artifacts", "artifacts.tar.gz"),
    "references": ("/data/references", "references.tar.gz"),
    "resource_cache": ("/data/siraloom/resource-cache", "resource-cache.tar.gz"),
}
ARTIFACT_STORAGE_PREFLIGHT_SQL = """
    SELECT json_build_object(
      'cloud_present', EXISTS (
        SELECT 1 FROM organization_storage_profiles
        WHERE backend_type = 'FIREBASE_GCS'
      ) OR EXISTS (
        SELECT 1 FROM artifacts WHERE storage_uri LIKE 'gs://%'
      ),
      'local_target_ids', COALESCE((
        SELECT json_agg(DISTINCT configuration->>'target_id')
        FROM organization_storage_profiles
        WHERE backend_type = 'LOCAL_FILESYSTEM'
          AND COALESCE(configuration->>'target_id', '') <> ''
      ), '[]'::json),
      'nonlegacy_artifacts', EXISTS (
        SELECT 1 FROM artifacts
        WHERE storage_uri NOT LIKE 'file:///data/siraloom/artifacts/%'
          AND storage_uri NOT LIKE 'gs://%'
      )
    )::text
"""


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
    if manifest.get("format") not in {FORMAT_V1, FORMAT}:
        raise BackupError("Unsupported backup format")
    files = manifest.get("files")
    expected_names = {DATABASE_FILE, *(name for _, name in STORAGE_ARCHIVES.values())}
    local_targets = manifest.get("local_artifact_targets", {})
    if manifest["format"] == FORMAT_V1 and local_targets:
        raise BackupError("Legacy backup manifest cannot declare custom artifact targets")
    if not isinstance(local_targets, dict):
        raise BackupError("Manifest local_artifact_targets must be an object")
    for target_id, target in local_targets.items():
        if (
            not isinstance(target_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", target_id)
            or not isinstance(target, dict)
            or set(target) != {"container_path", "archive"}
            or not isinstance(target["container_path"], str)
            or ".." in target["container_path"].split("/")
            or not PurePosixPath(target["container_path"]).is_absolute()
            or target["container_path"] == "/"
            or target["archive"] != f"artifact-target-{target_id}.tar.gz"
        ):
            raise BackupError(f"Invalid local artifact target metadata: {target_id!r}")
        expected_names.add(target["archive"])
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


def _bind_mount_source(
    config: dict[str, Any], service: str, target: str, *, must_exist: bool = True
) -> Path:
    mounts = ((config.get("services") or {}).get(service) or {}).get("volumes") or []
    matches = [mount for mount in mounts if mount.get("target") == target]
    if len(matches) != 1:
        raise BackupError(f"Expected one {service} bind mount at {target}")
    mount = matches[0]
    source = mount.get("source")
    if mount.get("type") != "bind" or not source or not Path(source).is_absolute():
        raise BackupError(f"{service} target {target} must use an absolute host bind mount")
    path = Path(source).resolve(strict=must_exist)
    if must_exist and not path.is_dir():
        raise BackupError(f"Configured storage source is not a directory: {target}")
    return path


def _load_local_artifact_targets(compose: list[str], *, root: Path) -> dict[str, str]:
    """Read deployment-owned local target IDs and container roots from the API image."""
    probe = (
        "import json; "
        "from backend.app.domain.storage_profiles import configured_local_storage_targets; "
        "print(json.dumps(dict(configured_local_storage_targets())))"
    )
    result = _run(
        [
            *compose,
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "--entrypoint",
            "python",
            "api",
            "-c",
            probe,
        ],
        cwd=root,
        capture=True,
    )
    try:
        configured = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackupError("Could not read deployment artifact-target configuration") from exc
    if not isinstance(configured, dict):
        raise BackupError("Deployment artifact-target configuration must be a JSON object")
    local: dict[str, str] = {}
    for target_id, container_path in configured.items():
        if (
            not isinstance(target_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", target_id)
            or not isinstance(container_path, str)
        ):
            raise BackupError("Deployment artifact-target configuration is invalid")
        path = PurePosixPath(container_path)
        if (
            path is None
            or not path.is_absolute()
            or path == PurePosixPath("/")
            or ".." in path.parts
        ):
            raise BackupError(f"Local artifact target {target_id} has an invalid container root")
        local[target_id] = str(path)
    return local


def _require_isolated_runtime_environment(
    config: dict[str, Any], *, compose_file: Path, env_file: Path
) -> None:
    """Ensure application services load the explicit restore environment file."""
    expected = env_file.resolve(strict=True)
    services = config.get("services") or {}
    for service in ("api", "worker", "beat"):
        raw = (services.get(service) or {}).get("env_file")
        entries = raw if isinstance(raw, list) else [raw]
        paths = []
        for entry in entries:
            value = entry.get("path") if isinstance(entry, dict) else entry
            if not isinstance(value, str) or not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                path = compose_file.parent / path
            paths.append(path.resolve(strict=False))
        if paths != [expected]:
            raise BackupError(
                f"Restore Compose service {service} must use only the explicit isolated "
                "runtime environment file. Set SIRALOOM_RUNTIME_ENV_FILE in the "
                "--env-file to that file's absolute path."
            )


def _artifact_inventory(
    compose: list[str], *, root: Path, user: str, database: str
) -> dict[str, Any]:
    result = _run(
        [
            *compose,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-X",
            "-qAt",
            f"--username={user}",
            f"--dbname={database}",
            f"--command={ARTIFACT_STORAGE_PREFLIGHT_SQL}",
        ],
        cwd=root,
        capture=True,
    )
    try:
        inventory = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackupError(
            "Artifact storage preflight returned invalid data; refusing backup"
        ) from exc
    if (
        not isinstance(inventory, dict)
        or set(inventory) != {"cloud_present", "local_target_ids", "nonlegacy_artifacts"}
        or not isinstance(inventory["cloud_present"], bool)
        or not isinstance(inventory["local_target_ids"], list)
        or not isinstance(inventory["nonlegacy_artifacts"], bool)
        or any(not isinstance(item, str) for item in inventory["local_target_ids"])
    ):
        raise BackupError("Artifact storage preflight returned an unknown result; refusing backup")
    if inventory["cloud_present"]:
        raise BackupError(
            "Cloud artifact targets are present. Configure and verify a cloud-aware backup "
            "before creating a recovery bundle."
        )
    return inventory


def _require_artifact_uris_covered(
    compose: list[str], *, root: Path, user: str, database: str, container_roots: list[str]
) -> None:
    prefixes = [Path(STORAGE_ARCHIVES["artifacts"][0]).as_uri() + "/"]
    prefixes.extend(PurePosixPath(path).as_uri() + "/" for path in container_roots)
    sql = _artifact_uri_coverage_sql(container_roots)
    result = _run(
        [
            *compose,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-X",
            "-qAt",
            f"--username={user}",
            f"--dbname={database}",
            f"--command={sql}",
        ],
        cwd=root,
        capture=True,
    )
    if result.stdout.strip() != "ARTIFACT_URIS_MAPPED":
        raise BackupError(
            "At least one persisted artifact URI is outside the configured local artifact roots; "
            "refusing an incomplete backup."
        )


def _artifact_uri_coverage_sql(container_roots: list[str]) -> str:
    prefixes = [Path(STORAGE_ARCHIVES["artifacts"][0]).as_uri() + "/"]
    prefixes.extend(PurePosixPath(path).as_uri() + "/" for path in container_roots)
    predicates = []
    for prefix in prefixes:
        literal = "'" + prefix.replace("'", "''") + "'"
        predicates.append(f"left(storage_uri, length({literal})) = {literal}")
    covered = " OR ".join(predicates)
    return (
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM artifacts "
        f"WHERE NOT ({covered}) AND storage_uri NOT LIKE 'gs://%') "
        "THEN 'UNMAPPED_ARTIFACT_URI' ELSE 'ARTIFACT_URIS_MAPPED' END"
    )


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


def _write_manifest(
    bundle: Path,
    *,
    commit: str,
    database: str,
    local_artifact_targets: dict[str, str] | None = None,
) -> None:
    local_artifact_targets = local_artifact_targets or {}
    files = [
        DATABASE_FILE,
        *(name for _, name in STORAGE_ARCHIVES.values()),
        *(f"artifact-target-{target_id}.tar.gz" for target_id in local_artifact_targets),
    ]
    manifest = {
        "format": FORMAT,
        "created_at": datetime.now(UTC).isoformat(),
        "repository_commit": commit,
        "database": database,
        "storage_targets": {key: target for key, (target, _) in STORAGE_ARCHIVES.items()},
        "local_artifact_targets": {
            target_id: {
                "container_path": container_path,
                "archive": f"artifact-target-{target_id}.tar.gz",
            }
            for target_id, container_path in sorted(local_artifact_targets.items())
        },
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
        inventory = _artifact_inventory(compose, root=root, user=user, database=database)
        local_targets = _load_local_artifact_targets(compose, root=root)
        local_target_sources: dict[str, Path] = {}
        missing_targets = set(inventory["local_target_ids"]) - set(local_targets)
        if missing_targets:
            raise BackupError(
                "Storage profiles reference local targets absent from the deployment "
                "configuration: " + ", ".join(sorted(missing_targets))
            )
        for target_id, container_path in local_targets.items():
            api_source = _bind_mount_source(config, "api", container_path)
            worker_source = _bind_mount_source(config, "worker", container_path)
            if api_source != worker_source:
                raise BackupError(
                    f"Local artifact target {target_id} has different API and worker mounts"
                )
            local_target_sources[target_id] = api_source
        container_roots = [Path(target) for target in local_targets.values()]
        container_roots.extend(Path(target) for target, _ in STORAGE_ARCHIVES.values())
        host_roots = list(local_target_sources.values())
        host_roots.extend(storage_sources.values())
        for roots in (container_roots, host_roots):
            for index, path in enumerate(roots):
                for other in roots[index + 1 :]:
                    if path == other or path in other.parents or other in path.parents:
                        raise BackupError(
                            "Configured artifact roots must not overlap each other or the base "
                            "storage roots in container or host mount paths."
                        )
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
        # Repeat the database inventory only after all application writers have
        # stopped. The preliminary check avoids disrupting an unsupported
        # deployment; this quiesced check closes the race with a final upload,
        # profile change, or artifact URI written between preflight and stop.
        quiesced_inventory = _artifact_inventory(compose, root=root, user=user, database=database)
        if set(quiesced_inventory["local_target_ids"]) - set(local_targets):
            missing_targets = sorted(
                set(quiesced_inventory["local_target_ids"]) - set(local_targets)
            )
            raise BackupError(
                "Storage profiles reference local targets absent from the deployment "
                "configuration after writers stopped: " + ", ".join(missing_targets)
            )
        _require_artifact_uris_covered(
            compose,
            root=root,
            user=user,
            database=database,
            container_roots=list(local_targets.values()),
        )
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
        for target_id, source in local_target_sources.items():
            _archive_tree(source, staged / f"artifact-target-{target_id}.tar.gz")
        commit_result = _run(["git", "rev-parse", "HEAD"], cwd=root, capture=True)
        _write_manifest(
            staged,
            commit=commit_result.stdout.strip(),
            database=database,
            local_artifact_targets=local_targets,
        )
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
        env_file = (root / env_file).resolve() if not env_file.is_absolute() else env_file.resolve()
    bundle = bundle.resolve(strict=True)
    manifest = verify_bundle(bundle)
    if not re.fullmatch(r"siraloom_restore_[a-z0-9_]{1,48}", target_database):
        raise BackupError("Restore database must match siraloom_restore_[a-z0-9_]{1,48}")
    if target_database == manifest["database"]:
        raise BackupError("Restore database must differ from the source database")
    local_targets = manifest.get("local_artifact_targets", {})
    expected_target_keys = set(STORAGE_ARCHIVES) | {
        f"artifact_target:{target_id}" for target_id in local_targets
    }
    if set(targets) != expected_target_keys:
        raise BackupError(
            "Restore requires the base storage paths and exactly the custom artifact targets "
            "listed in the backup manifest"
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

    if not project_name or not re.fullmatch(
        r"siraloom_restore(?:[_-][a-z0-9][a-z0-9_-]{0,48})?", project_name
    ):
        raise BackupError(
            "Restore requires a dedicated Compose project name beginning with siraloom_restore"
        )
    if env_file is None:
        raise BackupError(
            "Restore requires an explicit isolated environment file; do not use the live .env"
        )
    if not env_file.is_file():
        raise BackupError("Isolated restore environment file is unavailable")

    config = _compose_config(root, compose_file, project_name=project_name, env_file=env_file)
    _require_isolated_runtime_environment(config, compose_file=compose_file, env_file=env_file)
    if local_targets:
        configured_targets = _load_local_artifact_targets(
            _compose_command(compose_file, project_name=project_name, env_file=env_file),
            root=root,
        )
        for target_id, metadata in local_targets.items():
            if configured_targets.get(target_id) != metadata["container_path"]:
                raise BackupError(
                    f"Restore environment does not configure artifact target {target_id} "
                    "at its recorded container path"
                )
            destination = targets[f"artifact_target:{target_id}"].resolve(strict=False)
            for service in ("api", "worker"):
                mounted_source = _bind_mount_source(
                    config, service, metadata["container_path"], must_exist=False
                )
                if mounted_source != destination:
                    raise BackupError(
                        f"Restore {service} mount for artifact target {target_id} "
                        "does not match its new storage destination"
                    )
    running_result = _run(
        [
            *_compose_command(compose_file, project_name=project_name, env_file=env_file),
            "ps",
            "--services",
            "--status",
            "running",
        ],
        cwd=root,
        capture=True,
    )
    running_application_services = {
        name
        for name in running_result.stdout.splitlines()
        if name in {"api", "worker", "beat", "frontend"}
    }
    if running_application_services:
        raise BackupError(
            "Restore project must not run application services before the restored data is reviewed: "
            + ", ".join(sorted(running_application_services))
        )
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
            if key in STORAGE_ARCHIVES:
                archive_name = STORAGE_ARCHIVES[key][1]
            else:
                target_id = key.removeprefix("artifact_target:")
                archive_name = local_targets[target_id]["archive"]
            _extract_tree(bundle / archive_name, stage)

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

        restored_inventory = _artifact_inventory(
            compose, root=root, user=user, database=target_database
        )
        if restored_inventory["cloud_present"]:
            raise BackupError(
                "Backup contains cloud artifacts that this local restore cannot provide"
            )
        missing_targets = set(restored_inventory["local_target_ids"]) - set(local_targets)
        if missing_targets:
            raise BackupError(
                "Restored database references local artifact targets absent from the bundle: "
                + ", ".join(sorted(missing_targets))
            )
        _require_artifact_uris_covered(
            compose,
            root=root,
            user=user,
            database=target_database,
            container_roots=[metadata["container_path"] for metadata in local_targets.values()],
        )

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
    restore.add_argument(
        "--local-artifact-target",
        action="append",
        default=[],
        metavar="TARGET_ID=HOST_PATH",
        help="new host directory for a custom local target in the backup (repeat per target)",
    )
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
            artifact_targets: dict[str, Path] = {}
            for value in args.local_artifact_target:
                target_id, separator, path_value = value.partition("=")
                if (
                    not separator
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", target_id)
                    or not path_value
                ):
                    raise BackupError(
                        "Local artifact target must use TARGET_ID=/absolute/host/path"
                    )
                key = f"artifact_target:{target_id}"
                if key in artifact_targets:
                    raise BackupError(f"Duplicate local artifact target: {target_id}")
                artifact_targets[key] = Path(path_value)
            restore_backup(
                args.root,
                args.compose_file,
                args.bundle,
                args.database,
                {
                    "artifacts": args.artifacts_target,
                    "references": args.references_target,
                    "resource_cache": args.resource_cache_target,
                    **artifact_targets,
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
