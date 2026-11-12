import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "host_runtime_attestor.py"
_SPEC = importlib.util.spec_from_file_location("siraloom_host_runtime_attestor", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_attestor = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_attestor)


def test_docker_identity_uses_container_image_config_and_all_rootfs_layers(monkeypatch):
    container_id = "a" * 64
    image_id = "sha256:" + "b" * 64
    layers = ["sha256:" + "c" * 64, "sha256:" + "d" * 64]
    responses = [
        SimpleNamespace(
            stdout=json.dumps([{"Id": container_id, "Image": image_id, "HostConfig": {"ReadonlyRootfs": True}}])
        ),
        SimpleNamespace(
            stdout=json.dumps([{"Id": image_id, "RootFS": {"Layers": layers}}])
        ),
    ]
    calls = []

    monkeypatch.setattr(
        _attestor,
        "process_cgroups",
        lambda pid: f"0::/system.slice/docker-{container_id}.scope",
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        return responses.pop(0)

    monkeypatch.setattr(_attestor.subprocess, "run", fake_run)

    identity_type, digest = _attestor.docker_identity(1234)

    canonical = json.dumps(
        {"image_config": image_id, "rootfs_layers": layers},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert identity_type == "docker-image-content"
    assert digest == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert calls[0] == ["docker", "inspect", container_id]
    assert calls[1] == ["docker", "image", "inspect", image_id]


def test_docker_identity_rejects_missing_rootfs_layer_evidence(monkeypatch):
    container_id = "a" * 64
    image_id = "sha256:" + "b" * 64
    responses = [
        SimpleNamespace(stdout=json.dumps([{"Id": container_id, "Image": image_id, "HostConfig": {"ReadonlyRootfs": True}}])),
        SimpleNamespace(stdout=json.dumps([{"Id": image_id, "RootFS": {"Layers": []}}])),
    ]
    monkeypatch.setattr(
        _attestor,
        "process_cgroups",
        lambda pid: f"0::/system.slice/docker-{container_id}.scope",
    )
    monkeypatch.setattr(_attestor.subprocess, "run", lambda *_args, **_kwargs: responses.pop(0))

    with pytest.raises(RuntimeError, match="root-filesystem layer identity"):
        _attestor.docker_identity(1234)



def test_docker_identity_rejects_mutable_container_root_filesystem(monkeypatch):
    container_id = "a" * 64
    responses = [
        SimpleNamespace(
            stdout=json.dumps([{
                "Id": container_id,
                "Image": "sha256:" + "b" * 64,
                "HostConfig": {"ReadonlyRootfs": False},
            }])
        ),
    ]
    monkeypatch.setattr(
        _attestor,
        "process_cgroups",
        lambda pid: f"0::/system.slice/docker-{container_id}.scope",
    )
    monkeypatch.setattr(_attestor.subprocess, "run", lambda *_args, **_kwargs: responses.pop(0))

    with pytest.raises(RuntimeError, match="read-only container root filesystem"):
        _attestor.docker_identity(1234)
