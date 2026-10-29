import io
import json
import tarfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.laboratory_backup import (
    DATABASE_FILE,
    FORMAT,
    STORAGE_ARCHIVES,
    BackupError,
    _compose_command,
    _extract_tree,
    _require_local_artifact_storage,
    _safe_members,
    _volume_sources,
    create_backup,
    restore_backup,
    sha256_file,
    verify_bundle,
)


def _write_archive(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, body in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(body)
            member.mode = 0o600
            archive.addfile(member, io.BytesIO(body))


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "backup"
    bundle.mkdir()
    (bundle / DATABASE_FILE).write_bytes(b"PGDMPfixture")
    files = {DATABASE_FILE: sha256_file(bundle / DATABASE_FILE)}
    for _, archive_name in STORAGE_ARCHIVES.values():
        _write_archive(bundle / archive_name, {"case/file.txt": b"verified artifact"})
        files[archive_name] = sha256_file(bundle / archive_name)
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "format": FORMAT,
                "repository_commit": "test-commit",
                "database": "siraloom",
                "files": files,
            }
        )
    )
    return bundle


def test_verify_checks_complete_bundle_and_storage_archive_structure(tmp_path):
    bundle = _bundle(tmp_path)

    manifest = verify_bundle(bundle)

    assert manifest["format"] == FORMAT
    assert set(manifest["files"]) == {
        DATABASE_FILE,
        *(archive_name for _, archive_name in STORAGE_ARCHIVES.values()),
    }


def test_verify_rejects_changed_backup_member(tmp_path):
    bundle = _bundle(tmp_path)
    (bundle / DATABASE_FILE).write_bytes(b"changed")

    with pytest.raises(BackupError, match="SHA-256 verification failed"):
        verify_bundle(bundle)


@pytest.mark.parametrize("name", ["../outside", "/absolute", "folder/../../outside"])
def test_verify_rejects_path_traversal_in_storage_archive(tmp_path, name):
    bundle = _bundle(tmp_path)
    archive_name = STORAGE_ARCHIVES["artifacts"][1]
    _write_archive(bundle / archive_name, {name: b"unsafe"})
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["files"][archive_name] = sha256_file(bundle / archive_name)
    (bundle / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(BackupError, match="Unsafe path"):
        verify_bundle(bundle)


def test_verify_rejects_links_and_nonregular_storage_entries(tmp_path):
    bundle = _bundle(tmp_path)
    archive_name = STORAGE_ARCHIVES["artifacts"][1]
    with tarfile.open(bundle / archive_name, "w:gz") as archive:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["files"][archive_name] = sha256_file(bundle / archive_name)
    (bundle / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(BackupError, match="Unsupported file type"):
        verify_bundle(bundle)


def test_extract_tree_restores_regular_files_without_overwriting(tmp_path):
    archive_path = tmp_path / "files.tar.gz"
    _write_archive(archive_path, {"case/report.txt": b"restored"})
    destination = tmp_path / "new-storage"

    _extract_tree(archive_path, destination)

    assert (destination / "case/report.txt").read_bytes() == b"restored"
    with pytest.raises(FileExistsError):
        _extract_tree(archive_path, destination)


def test_safe_members_rejects_duplicate_archive_names(tmp_path):
    archive_path = tmp_path / "duplicate.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for payload in (b"one", b"two"):
            member = tarfile.TarInfo("same")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))

    with (
        tarfile.open(archive_path, "r:gz") as archive,
        pytest.raises(BackupError, match="Duplicate path"),
    ):
        _safe_members(archive)


def test_volume_discovery_rejects_named_volumes_for_backup_sources(tmp_path):
    services = {
        "api": {
            "volumes": [
                {"type": "volume", "source": "artifact_data", "target": target}
                for target, _ in STORAGE_ARCHIVES.values()
            ]
        },
        "postgres": {"volumes": [{"target": "/var/lib/postgresql/data"}]},
    }

    with pytest.raises(BackupError, match="absolute host bind mount"):
        _volume_sources({"services": services})


@pytest.mark.parametrize(
    ("database_result", "message"),
    [
        ("CLOUD_ARTIFACTS_PRESENT", "Firebase/GCS storage profiles"),
        (
            "CUSTOM_LOCAL_ARTIFACT_TARGETS_PRESENT",
            "organization-targeted local artifact profiles",
        ),
        ("", "unknown result"),
    ],
)
def test_backup_refuses_unsupported_artifact_targets_or_unknown_database_result(
    tmp_path, monkeypatch, database_result, message
):
    from scripts import laboratory_backup

    seen = {}

    def fake_run(command, *, cwd, capture=False):
        seen["command"] = command
        seen["cwd"] = cwd
        seen["capture"] = capture
        return CompletedProcess(command, 0, stdout=database_result, stderr="")

    monkeypatch.setattr(laboratory_backup, "_run", fake_run)

    with pytest.raises(BackupError, match=message):
        _require_local_artifact_storage(
            ["docker", "compose"],
            root=tmp_path,
            user="siraloom",
            database="siraloom",
        )

    assert "organization_storage_profiles" in seen["command"][-1]
    assert "storage_uri LIKE 'gs://%'" in seen["command"][-1]
    assert "CUSTOM_LOCAL_ARTIFACT_TARGETS_PRESENT" in seen["command"][-1]
    assert seen["capture"] is True


def test_backup_accepts_confirmed_local_only_artifact_storage(tmp_path, monkeypatch):
    from scripts import laboratory_backup

    monkeypatch.setattr(
        laboratory_backup,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess(
            args=[], returncode=0, stdout="LOCAL_ARTIFACTS_ONLY\n", stderr=""
        ),
    )

    _require_local_artifact_storage(
        ["docker", "compose"],
        root=tmp_path,
        user="siraloom",
        database="siraloom",
    )


def test_create_backup_checks_cloud_storage_before_stopping_writers(tmp_path, monkeypatch):
    from scripts import laboratory_backup

    root = tmp_path / "repo"
    root.mkdir()
    compose_file = root / "compose.yml"
    compose_file.write_text("services: {}", encoding="utf-8")
    api_volumes = []
    for key, (container_path, _archive_name) in STORAGE_ARCHIVES.items():
        source = root / key
        source.mkdir()
        api_volumes.append({"type": "bind", "source": str(source), "target": container_path})
    monkeypatch.setattr(
        laboratory_backup,
        "_compose_config",
        lambda *_args, **_kwargs: {
            "services": {
                "api": {"volumes": api_volumes},
                "postgres": {
                    "environment": {
                        "POSTGRES_DB": "siraloom",
                        "POSTGRES_USER": "siraloom",
                    },
                    "volumes": [{"target": "/var/lib/postgresql/data"}],
                },
            }
        },
    )
    commands = []

    def fake_run(command, *, cwd, capture=False):
        commands.append(command)
        return CompletedProcess(
            args=command,
            returncode=0,
            stdout="CLOUD_ARTIFACTS_PRESENT\n",
            stderr="",
        )

    monkeypatch.setattr(laboratory_backup, "_run", fake_run)
    output = root / "backup"

    with pytest.raises(BackupError, match="Firebase/GCS storage profiles"):
        create_backup(root, compose_file, output)

    assert len(commands) == 1
    assert "psql" in commands[0]
    assert not output.exists()
    assert not list(root.glob(".backup.tmp-*"))


def test_compose_command_supports_isolated_restore_environment(tmp_path):
    env_file = tmp_path / ".env.restore"

    command = _compose_command(
        Path("compose.yml"), project_name="siraloom_restore", env_file=env_file
    )

    assert command == [
        "docker",
        "compose",
        "-p",
        "siraloom_restore",
        "--env-file",
        str(env_file),
        "-f",
        "compose.yml",
    ]
    with pytest.raises(BackupError, match="unsupported characters"):
        _compose_command(Path("compose.yml"), project_name="unsafe;project")


def test_restore_refuses_source_database_before_docker_access(tmp_path):
    bundle = _bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["database"] = "siraloom_restore_20261026"
    manifest_path.write_text(json.dumps(manifest))
    root = tmp_path / "repo"
    root.mkdir()
    compose = root / "compose.yml"
    compose.write_text("services: {}")
    parent = tmp_path / "restore"
    parent.mkdir()
    targets = {
        "artifacts": parent / "artifacts",
        "references": parent / "references",
        "resource_cache": parent / "resource-cache",
    }

    with pytest.raises(BackupError, match="differ from the source database"):
        restore_backup(root, compose, bundle, "siraloom_restore_20261026", targets)


def test_create_refuses_existing_backup_destination_before_docker_access(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    compose = root / "compose.yml"
    compose.write_text("services: {}")
    destination = tmp_path / "existing-backup"
    destination.mkdir()

    with pytest.raises(BackupError, match="destination already exists"):
        create_backup(root, compose, destination)


def test_restore_refuses_existing_storage_target_before_docker_access(tmp_path):
    bundle = _bundle(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    compose = root / "compose.yml"
    compose.write_text("services: {}")
    parent = tmp_path / "restore"
    parent.mkdir()
    existing = parent / "artifacts"
    existing.mkdir()
    targets = {
        "artifacts": existing,
        "references": parent / "references",
        "resource_cache": parent / "resource-cache",
    }

    with pytest.raises(BackupError, match="not-yet-existing path"):
        restore_backup(root, compose, bundle, "siraloom_restore_20261026", targets)


@pytest.mark.parametrize(
    ("project_name", "env_file", "message"),
    [
        (None, Path("restore.env"), "dedicated Compose project"),
        ("siraloom", Path("restore.env"), "dedicated Compose project"),
        ("siraloom_restoreevil", Path("restore.env"), "dedicated Compose project"),
        ("siraloom_restore_test", None, "explicit isolated environment file"),
    ],
)
def test_restore_requires_explicit_isolated_compose_project_and_environment(
    tmp_path, project_name, env_file, message
):
    bundle = _bundle(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "compose.yml").write_text("services: {}")
    (root / "restore.env").write_text("POSTGRES_DB=siraloom_restore_bootstrap\n")
    parent = tmp_path / "restore"
    parent.mkdir()
    targets = {
        "artifacts": parent / "artifacts",
        "references": parent / "references",
        "resource_cache": parent / "resource-cache",
    }

    with pytest.raises(BackupError, match=message):
        restore_backup(
            root,
            Path("compose.yml"),
            bundle,
            "siraloom_restore_20261026",
            targets,
            project_name=project_name,
            env_file=env_file,
        )


def test_restore_refuses_running_application_services_in_isolated_project(tmp_path, monkeypatch):
    from scripts import laboratory_backup

    bundle = _bundle(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    compose = root / "compose.yml"
    compose.write_text("services: {}")
    env_file = root / "restore.env"
    env_file.write_text("POSTGRES_DB=siraloom_restore_bootstrap\n")
    parent = tmp_path / "restore"
    parent.mkdir()
    targets = {
        "artifacts": parent / "artifacts",
        "references": parent / "references",
        "resource_cache": parent / "resource-cache",
    }
    monkeypatch.setattr(
        laboratory_backup,
        "_compose_config",
        lambda *_args, **_kwargs: {
            "services": {
                "postgres": {
                    "environment": {
                        "POSTGRES_DB": "siraloom_restore_bootstrap",
                        "POSTGRES_USER": "siraloom",
                    }
                }
            }
        },
    )
    monkeypatch.setattr(
        laboratory_backup,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess(
            args=[], returncode=0, stdout="api\npostgres\nredis\n", stderr=""
        ),
    )

    with pytest.raises(BackupError, match="must not run application services"):
        restore_backup(
            root,
            compose,
            bundle,
            "siraloom_restore_20261026",
            targets,
            project_name="siraloom_restore_test",
            env_file=env_file,
        )

    assert not any(target.exists() for target in targets.values())
