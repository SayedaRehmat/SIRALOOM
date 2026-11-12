#!/usr/bin/env python3
"""Privileged host-side runtime identity broker for SIRALOOM clinical workers.

Run on the Docker host or bare-metal node. The private Ed25519 key remains on
the host; workers receive only the public key. The Unix socket must be mounted
read/write only into the designated worker containers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import socketserver
import struct
import re
import subprocess
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def process_start_time(pid: int) -> str:
    # Field 22 in /proc/PID/stat; comm may contain spaces and parentheses.
    raw = Path(f"/proc/{pid}/stat").read_text()
    return raw[raw.rfind(")") + 2 :].split()[19]


def process_cgroups(pid: int) -> str:
    return Path(f"/proc/{pid}/cgroup").read_text()


def docker_identity(pid: int) -> tuple[str, str]:
    cgroups = process_cgroups(pid).lower()
    candidates = set(re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", cgroups))
    if len(candidates) != 1:
        raise RuntimeError("Host cgroup metadata does not identify exactly one Docker container")
    container_id = next(iter(candidates))
    result = subprocess.run(
        ["docker", "inspect", container_id],
        check=True, capture_output=True, text=True, timeout=5,
    )
    records = json.loads(result.stdout)
    if len(records) != 1 or records[0].get("Id") != container_id:
        raise RuntimeError("Docker Engine did not return the exact host container")
    if records[0].get("HostConfig", {}).get("ReadonlyRootfs") is not True:
        raise RuntimeError("Clinical Docker workers must run with a read-only container root filesystem")
    image_id = str(records[0].get("Image") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError("Docker Engine did not report an immutable sha256 image config ID")
    image_result = subprocess.run(
        ["docker", "image", "inspect", image_id],
        check=True, capture_output=True, text=True, timeout=5,
    )
    images = json.loads(image_result.stdout)
    if len(images) != 1 or images[0].get("Id") != image_id:
        raise RuntimeError("Docker Engine did not resolve the exact immutable image object")
    layers = images[0].get("RootFS", {}).get("Layers")
    if not isinstance(layers, list) or not layers or any(
        not isinstance(layer, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", layer) for layer in layers
    ):
        raise RuntimeError("Docker image has no complete immutable root-filesystem layer identity")
    identity_bytes = json.dumps(
        {"image_config": image_id, "rootfs_layers": layers},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    content_digest = hashlib.sha256(identity_bytes).hexdigest()
    return "docker-image-content", "sha256:" + content_digest


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            peer_pid, peer_uid, _ = struct.unpack(
                "3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            if peer_pid <= 1:
                raise RuntimeError("Cannot authenticate the connecting worker process")
            request = json.loads(self.rfile.readline(65537))
            nonce = request.get("nonce")
            if not isinstance(nonce, str) or len(nonce) != 64 or any(
                ch not in "0123456789abcdef" for ch in nonce
            ):
                raise RuntimeError("Malformed attestation challenge")
            start = process_start_time(peer_pid)
            executable = os.readlink(f"/proc/{peer_pid}/exe")
            command_line = Path(f"/proc/{peer_pid}/cmdline").read_bytes()
            command_arguments = [
                item.decode(errors="replace")
                for item in command_line.split(bytes([0]))
                if item
            ]
            if not any(
                "celery" in item.lower()
                or item.endswith("print_runtime_component_manifest.py")
                for item in command_arguments
            ):
                raise RuntimeError("Host attestor only signs a SIRALOOM Celery worker or runtime-manifest command")
            executable_sha256 = sha256_file(Path(f"/proc/{peer_pid}/exe"))
            command_sha256 = hashlib.sha256(command_line).hexdigest()
            cgroups = process_cgroups(peer_pid)
            if self.server.mode == "docker":
                identity_type, identity = docker_identity(peer_pid)
                image_digest = identity.removeprefix("sha256:")
                identity_version = identity
            else:
                root = self.server.install_root.resolve(strict=True)
                if root.stat().st_uid != 0 or root.stat().st_mode & 0o022:
                    raise RuntimeError("Bare-metal installation root must be root-owned and not group/world writable")
                cwd = Path(f"/proc/{peer_pid}/cwd").resolve(strict=True)
                executable_path = Path(executable.replace(" (deleted)", "")).resolve(strict=True)
                if root != cwd and root not in cwd.parents:
                    raise RuntimeError("Connecting process working directory is outside the trusted installation root")
                if root != executable_path and root not in executable_path.parents:
                    raise RuntimeError("Bare-metal worker interpreter must be inside the trusted installation root")
                if executable_path.stat().st_uid != 0 or executable_path.stat().st_mode & 0o022:
                    raise RuntimeError("Bare-metal worker interpreter must be root-owned and not group/world writable")
                if self.server.release_manifest.is_symlink():
                    raise RuntimeError("Release manifest cannot be a symbolic link")
                manifest = self.server.release_manifest.resolve(strict=True)
                if root != manifest.parent and root not in manifest.parents:
                    raise RuntimeError("Release manifest is outside the trusted installation root")
                if manifest.stat().st_uid != 0 or manifest.stat().st_mode & 0o022:
                    raise RuntimeError("Release manifest must be root-owned and not group/world writable")
                release = json.loads(manifest.read_text(encoding="utf-8"))
                files = release.get("files") if isinstance(release, dict) else None
                if not isinstance(release, dict) or release.get("schema_version") != "1" or not isinstance(files, list) or not files:
                    raise RuntimeError("Release manifest must contain a non-empty version-1 file inventory")
                seen = set()
                for item in files:
                    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                        raise RuntimeError("Release manifest contains a malformed file entry")
                    relative = Path(item["path"])
                    if relative.is_absolute() or ".." in relative.parts or str(relative) in seen:
                        raise RuntimeError("Release manifest contains an unsafe or duplicate path")
                    seen.add(str(relative))
                    declared_path = root / relative
                    current = root
                    for part in relative.parts[:-1]:
                        current = current / part
                        if current.is_symlink():
                            raise RuntimeError("Release manifest cannot include symbolic links")
                        if current.stat().st_uid != 0 or current.stat().st_mode & 0o022:
                            raise RuntimeError("Release directories must be root-owned and not group/world writable")
                    current = current / relative.parts[-1]
                    if current.is_symlink():
                        raise RuntimeError("Release manifest cannot include symbolic links")
                    target = declared_path.resolve(strict=True)
                    if root not in target.parents or not target.is_file():
                        raise RuntimeError("Release manifest file is missing or escapes the installation root")
                    if target.stat().st_uid != 0 or target.stat().st_mode & 0o022:
                        raise RuntimeError("Installed release files must be root-owned and not group/world writable")
                    expected = item.get("sha256")
                    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256_file(target) != expected:
                        raise RuntimeError(f"Installed release file does not match its manifest: {relative}")
                image_digest = sha256_file(manifest)
                identity_type = "bare-metal-release-manifest"
                identity_version = f"bare-metal:{image_digest}"
            payload = {
                "schema_version": "1",
                "nonce": nonce,
                "issued_at_unix": int(time.time()),
                "peer_pid": peer_pid,
                "peer_uid": peer_uid,
                "process_start_time": start,
                "process_executable": executable,
                "process_executable_sha256": executable_sha256,
                "process_command_sha256": command_sha256,
                "process_cgroup_sha256": hashlib.sha256(cgroups.encode()).hexdigest(),
                "identity_type": identity_type,
                "identity_version": identity_version,
                "image_sha256": image_digest,
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            signature = subprocess.run(
                ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(self.server.private_key)],
                input=canonical, check=True, capture_output=True, timeout=5,
            ).stdout
            response = {"payload": payload, "signature": signature.hex()}
            self.wfile.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")
        except Exception as exc:
            self.wfile.write(json.dumps({"error": str(exc)}).encode() + b"\n")


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--socket-gid", type=int)
    parser.add_argument("--mode", choices=("docker", "bare-metal"), required=True)
    parser.add_argument("--install-root")
    parser.add_argument("--release-manifest")
    args = parser.parse_args()
    key = Path(args.private_key).resolve(strict=True)
    if key.stat().st_uid != 0 or key.stat().st_mode & 0o077:
        raise SystemExit("Private signing key must be root-owned and not group/world accessible")
    key_info = subprocess.run(
        ["openssl", "pkey", "-in", str(key), "-text", "-noout"],
        check=True, capture_output=True, text=True, timeout=5,
    ).stdout
    if "ED25519" not in key_info.upper():
        raise SystemExit("Host signing key must be Ed25519")
    if args.mode == "bare-metal" and not (args.install_root and args.release_manifest):
        parser.error("bare-metal mode requires --install-root and --release-manifest")
    socket_path = Path(args.socket)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        raise SystemExit("Refusing to replace an existing host-attestor socket")
    server = Server(str(socket_path), Handler)
    os.chmod(socket_path, 0o660)
    if args.socket_gid is not None:
        os.chown(socket_path, 0, args.socket_gid)
    server.private_key = key
    server.mode = args.mode
    server.install_root = Path(args.install_root) if args.install_root else None
    server.release_manifest = Path(args.release_manifest) if args.release_manifest else None
    try:
        server.serve_forever()
    finally:
        server.server_close()
        socket_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
