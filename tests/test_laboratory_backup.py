import io
import json
import tarfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.laboratory_backup import (
    DATABASE_FILE,
    FORMAT,
    FORMAT_V1,
    STORAGE_ARCHIVES,
    BackupError,
    _artifact_inventory,
    _artifact_uri_coverage_sql,
    _compose_command,
    _extract_tree,
    _load_local_artifact_targets,
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


def _bundle(tmp_path: Path, *, local_targets: dict[str, str] | None = None) -> Path:
    bundle = tmp_path / "backup"
    bundle.mkdir()
    (bundle / DATABASE_FILE).write_bytes(b"PGDMPfixture")
    files = {DATABASE_FILE: sha256_file(bundle / DATABASE_FILE)}
    for _, archive_name in STORAGE_ARCHIVES.values():
        _write_archive(bundle / archive_name, {"case/file.txt": b"verified artifact"})
        files[archive_name] = sha256_file(bundle / archive_name)
    target_manifest = {}
    for target_id, container_path in (local_targets or {}).items():
        archive_name = f"artifact-target-{target_id}.tar.gz"
        _write_archive(bundle / archive_name, {"case/local.txt": b"local target artifact"})
        files[archive_name] = sha256_file(bundle / archive_name)
        target_manifest[target_id] = {
            "container_path": container_path,
            "archive": archive_name,
        }
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "format": FORMAT,
                "repository_commit": "test-commit",
                "database": "siraloom",
                "local_artifact_targets": target_manifest,
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


def test_verify_accepts_existing_v1_bundle(tmp_path):
    bundle = _bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["format"] = FORMAT_V1
    manifest.pop("local_artifact_targets", None)
    manifest_path.write_text(json.dumps(manifest))

    assert verify_bundle(bundle)["format"] == FORMAT_V1


def test_verify_checks_declared_local_artifact_archives(tmp_path):
    bundle = _bundle(tmp_path, local_targets={"lab-a": "/data/labs/a/artifacts"})

    manifest = verify_bundle(bundle)

    assert manifest["local_artifact_targets"] == {
        "lab-a": {
            "container_path": "/data/labs/a/artifacts",
            "archive": "artifact-target-lab-a.tar.gz",
        }
    }


@pytest.mark.parametrize(
    "container_path",
    ["/", "/data/../outside", "relative/path"],
)
def test_verify_rejects_unsafe_local_artifact_root(tmp_path, container_path):
    bundle = _bundle(tmp_path, local_targets={"lab-a": container_path})

    with pytest.raises(BackupError):
        verify_bundle(bundle)


def test_restore_requires_exact_custom_artifact_destination_set(tmp_path):
    bundle = _bundle(tmp_path, local_targets={"lab-a": "/data/labs/a/artifacts"})
    root = tmp_path / "repo"
    root.mkdir()
    (root / "compose.yml").write_text("services: {}")
    parent = tmp_path / "restore"
    parent.mkdir()
    targets = {
        "artifacts": parent / "artifacts",
        "references": parent / "references",
        "resource_cache": parent / "resource-cache",
    }

    with pytest.raises(BackupError, match="exactly the custom artifact targets"):
        restore_backup(root, Path("compose.yml"), bundle, "siraloom_restore_target", targets)


def test_restore_requires_services_to_load_isolated_runtime_environment(tmp_path):
    from scripts.laboratory_backup import _require_isolated_runtime_environment

    compose_file = tmp_path / "compose.yml"
    compose_file.write_text("services: {}", encoding="utf-8")
    env_file = tmp_path / "restore.env"
    env_file.write_text("POSTGRES_DB=siraloom_restore_bootstrap\n", encoding="utf-8")
    config = {"services": {service: {"env_file": ".env"} for service in ("api", "worker", "beat")}}

    with pytest.raises(BackupError, match="explicit isolated runtime environment"):
        _require_isolated_runtime_environment(config, compose_file=compose_file, env_file=env_file)


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
        (
            '{"cloud_present":true,"local_target_ids":[],"nonlegacy_artifacts":false}',
            "Cloud artifact targets",
        ),
        ("not-json", "invalid data"),
        ('{"cloud_present":false}', "unknown result"),
    ],
)
def test_backup_inventory_rejects_cloud_or_unknown_database_results(
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
        _artifact_inventory(
            ["docker", "compose"],
            root=tmp_path,
            user="siraloom",
            database="siraloom",
        )

    assert "organization_storage_profiles" in seen["command"][-1]
    assert "storage_uri LIKE 'gs://%'" in seen["command"][-1]
    assert seen["capture"] is True


def test_backup_inventory_accepts_confirmed_local_only_storage(tmp_path, monkeypatch):
    from scripts import laboratory_backup

    monkeypatch.setattr(
        laboratory_backup,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"cloud_present":false,"local_target_ids":[],"nonlegacy_artifacts":false}',
            stderr="",
        ),
    )

    result = _artifact_inventory(
        ["docker", "compose"],
        root=tmp_path,
        user="siraloom",
        database="siraloom",
    )
    assert result == {
        "cloud_present": False,
        "local_target_ids": [],
        "nonlegacy_artifacts": False,
    }


def test_local_target_configuration_is_validated_and_only_local_roots_are_returned(
    tmp_path, monkeypatch
):
    from scripts import laboratory_backup

    monkeypatch.setattr(
        laboratory_backup,
        "_run",
        lambda *_args, **_kwargs: CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "lab-a": "/data/lab-a",
                }
            ),
            stderr="",
        ),
    )

    assert _load_local_artifact_targets(["docker", "compose"], root=tmp_path) == {
        "lab-a": "/data/lab-a"
    }


def test_artifact_uri_coverage_query_uses_literal_prefixes():
    query = _artifact_uri_coverage_sql(["/data/siraloom/labs/lab-a/artifacts"])

    assert "file:///data/siraloom/artifacts/" in query
    assert "file:///data/siraloom/labs/lab-a/artifacts/" in query
    assert "left(storage_uri, length(" in query


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
            stdout='{"cloud_present":true,"local_target_ids":[],"nonlegacy_artifacts":false}',
            stderr="",
        )

    monkeypatch.setattr(laboratory_backup, "_run", fake_run)
    output = root / "backup"

    with pytest.raises(BackupError, match="Cloud artifact targets"):
        create_backup(root, compose_file, output)

    assert len(commands) == 1
    assert "psql" in commands[0]
    assert not output.exists()
    assert not list(root.glob(".backup.tmp-*"))


def test_create_backup_archives_each_configured_local_target(tmp_path, monkeypatch):
    from scripts import laboratory_backup

    root = tmp_path / "repo"
    root.mkdir()
    compose_file = root / "compose.yml"
    compose_file.write_text("services: {}", encoding="utf-8")
    mount_sources = {}
    api_volumes = []
    for key, (container_path, _archive_name) in STORAGE_ARCHIVES.items():
        source = root / key
        source.mkdir()
        mount_sources[key] = source
        api_volumes.append({"type": "bind", "source": str(source), "target": container_path})
    custom_source = root / "lab-a-artifacts"
    custom_source.mkdir()
    (custom_source / "case.vcf").write_text("local target data", encoding="utf-8")
    custom_container_root = "/data/siraloom/labs/lab-a/artifacts"
    api_volumes.append(
        {"type": "bind", "source": str(custom_source), "target": custom_container_root}
    )
    compose_config = {
        "services": {
            "api": {"volumes": api_volumes},
            "worker": {
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(custom_source),
                        "target": custom_container_root,
                    }
                ]
            },
            "postgres": {
                "environment": {"POSTGRES_DB": "siraloom", "POSTGRES_USER": "siraloom"},
                "volumes": [{"target": "/var/lib/postgresql/data"}],
            },
        }
    }
    monkeypatch.setattr(laboratory_backup, "_compose_config", lambda *_a, **_k: compose_config)
    commands = []

    def fake_run(command, *, cwd, capture=False):
        commands.append(command)
        if "psql" in command:
            sql = command[-1]
            if "json_build_object" in sql:
                stdout = json.dumps(
                    {
                        "cloud_present": False,
                        "local_target_ids": ["lab-a"],
                        "nonlegacy_artifacts": True,
                    }
                )
            else:
                stdout = "ARTIFACT_URIS_MAPPED"
        elif "run" in command:
            stdout = json.dumps({"lab-a": custom_container_root})
        elif "ps" in command:
            stdout = "api\nworker\n"
        elif "rev-parse" in command:
            stdout = "test-commit\n"
        else:
            stdout = ""
        return CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(laboratory_backup, "_run", fake_run)

    def fake_pg_dump(*_args, cwd, stdout, check):
        stdout.write(b"PGDMPfixture")
        return CompletedProcess(args=[], returncode=0)

    monkeypatch.setattr(laboratory_backup.subprocess, "run", fake_pg_dump)
    output = root / "backup"

    create_backup(root, compose_file, output)

    manifest = verify_bundle(output)
    assert manifest["local_artifact_targets"]["lab-a"]["container_path"] == custom_container_root
    assert (output / "artifact-target-lab-a.tar.gz").is_file()
    assert any("stop" in command for command in commands)
    assert any("start" in command for command in commands)


def test_create_backup_rejects_overlapping_local_mount_roots_before_stopping_writers(
    tmp_path, monkeypatch
):
    from scripts import laboratory_backup

    root = tmp_path / "repo"
    root.mkdir()
    compose_file = root / "compose.yml"
    compose_file.write_text("services: {}", encoding="utf-8")
    mount_sources = {}
    api_volumes = []
    for key, (container_path, _archive_name) in STORAGE_ARCHIVES.items():
        source = root / key
        source.mkdir()
        mount_sources[key] = source
        api_volumes.append({"type": "bind", "source": str(source), "target": container_path})
    custom_source = root / "custom"
    custom_source.mkdir()
    custom_container_root = "/data/siraloom/artifacts/lab-a"
    api_volumes.append(
        {"type": "bind", "source": str(custom_source), "target": custom_container_root}
    )
    config = {
        "services": {
            "api": {"volumes": api_volumes},
            "worker": {
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(custom_source),
                        "target": custom_container_root,
                    }
                ]
            },
            "postgres": {
                "environment": {"POSTGRES_DB": "siraloom", "POSTGRES_USER": "siraloom"},
                "volumes": [{"target": "/var/lib/postgresql/data"}],
            },
        }
    }
    monkeypatch.setattr(laboratory_backup, "_compose_config", lambda *_a, **_k: config)
    commands = []

    def fake_run(command, *, cwd, capture=False):
        commands.append(command)
        if "psql" in command:
            stdout = json.dumps(
                {
                    "cloud_present": False,
                    "local_target_ids": ["lab-a"],
                    "nonlegacy_artifacts": False,
                }
            )
        elif "run" in command:
            stdout = json.dumps({"lab-a": custom_container_root})
        else:
            stdout = ""
        return CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(laboratory_backup, "_run", fake_run)

    with pytest.raises(BackupError, match="must not overlap"):
        create_backup(root, compose_file, root / "backup")

    assert not any("stop" in command for command in commands)


def test_restore_custom_local_target_into_new_compose_mounts(tmp_path, monkeypatch):
    from scripts import laboratory_backup

    bundle = _bundle(tmp_path, local_targets={"lab-a": "/data/siraloom/labs/lab-a/artifacts"})
    root = tmp_path / "repo"
    root.mkdir()
    compose_file = root / "compose.yml"
    compose_file.write_text("services: {}", encoding="utf-8")
    env_file = root / "restore.env"
    env_file.write_text("POSTGRES_DB=siraloom_restore_bootstrap\n", encoding="utf-8")
    parent = tmp_path / "restore-targets"
    parent.mkdir()
    custom_target = parent / "lab-a-artifacts"
    targets = {
        "artifacts": parent / "artifacts",
        "references": parent / "references",
        "resource_cache": parent / "resource-cache",
        "artifact_target:lab-a": custom_target,
    }
    container_root = "/data/siraloom/labs/lab-a/artifacts"
    compose_config = {
        "services": {
            "postgres": {
                "environment": {
                    "POSTGRES_DB": "siraloom_restore_bootstrap",
                    "POSTGRES_USER": "siraloom",
                }
            },
            **{
                service: {
                    "env_file": str(env_file),
                    "volumes": [
                        {
                            "type": "bind",
                            "source": str(custom_target),
                            "target": container_root,
                        }
                    ],
                }
                for service in ("api", "worker", "beat")
            },
        }
    }
    monkeypatch.setattr(laboratory_backup, "_compose_config", lambda *_a, **_k: compose_config)
    monkeypatch.setattr(
        laboratory_backup,
        "_load_local_artifact_targets",
        lambda *_a, **_k: {"lab-a": container_root},
    )
    commands = []

    def fake_run(command, *, cwd, capture=False):
        commands.append(command)
        if "ps" in command:
            stdout = "postgres\nredis\n"
        elif "psql" in command and "json_build_object" in command[-1]:
            stdout = json.dumps(
                {
                    "cloud_present": False,
                    "local_target_ids": ["lab-a"],
                    "nonlegacy_artifacts": True,
                }
            )
        elif "psql" in command:
            stdout = "ARTIFACT_URIS_MAPPED"
        else:
            stdout = ""
        return CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(laboratory_backup, "_run", fake_run)
    monkeypatch.setattr(
        laboratory_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: CompletedProcess(args=[], returncode=0),
    )

    restore_backup(
        root,
        compose_file,
        bundle,
        "siraloom_restore_local_target",
        targets,
        project_name="siraloom_restore_test",
        env_file=env_file,
    )

    assert (custom_target / "case" / "local.txt").read_bytes() == b"local target artifact"
    assert custom_target.is_dir()
    assert any("createdb" in command for command in commands)


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
                **{service: {"env_file": str(env_file)} for service in ("api", "worker", "beat")},
                "postgres": {
                    "environment": {
                        "POSTGRES_DB": "siraloom_restore_bootstrap",
                        "POSTGRES_USER": "siraloom",
                    }
                },
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
