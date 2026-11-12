from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


class ToolchainProfileError(ValueError):
    """The configured scientific toolchain is not a registered safe profile."""


CONFIG_ROOT = Path(os.environ.get("SIRALOOM_CONFIG_ROOT", Path.cwd())).resolve()
DEFAULT_REGISTRY = CONFIG_ROOT / "configs" / "bioinformatics" / "toolchain-profiles.v1.json"


def load_toolchain_registry(path: str | Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    registry_path = Path(path)
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolchainProfileError("The scientific toolchain profile registry is unavailable or invalid.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1":
        raise ToolchainProfileError("Unsupported scientific toolchain registry schema.")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ToolchainProfileError("Scientific toolchain registry has no profile list.")
    identifiers = [item.get("id") for item in profiles if isinstance(item, dict)]
    if len(identifiers) != len(profiles) or len(set(identifiers)) != len(identifiers):
        raise ToolchainProfileError("Scientific toolchain profile IDs must be present and unique.")
    return payload


def resolve_toolchain_profile(
    profile_id: str,
    *,
    bcftools_version: str,
    htslib_version: str,
    registry_path: str | Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    if not profile_id or not profile_id.strip():
        raise ToolchainProfileError("An explicit BCFtools/HTSlib profile ID is required.")
    registry = load_toolchain_registry(registry_path)
    matches = [item for item in registry["profiles"] if item["id"] == profile_id]
    if len(matches) != 1:
        raise ToolchainProfileError(f"Unknown BCFtools/HTSlib profile: {profile_id!r}.")
    profile = matches[0]
    from backend.app.domain.scientific_tool_profiles import (
        ScientificToolProfileError,
        resolve_scientific_tool_profile,
    )
    try:
        generic_profile = resolve_scientific_tool_profile(
            profile_id,
            tool_id="bcftools",
            platform=str(profile.get("platform") or ""),
            execution_method="OCI_CONTAINER",
            registry_path=CONFIG_ROOT / "configs" / "bioinformatics" / "scientific-tool-profiles.v1.json",
        )
    except ScientificToolProfileError as exc:
        raise ToolchainProfileError(str(exc)) from exc
    if (
        generic_profile.get("version") != profile.get("bcftools_version")
        or not any(
            dependency.get("name") == "HTSlib"
            and dependency.get("version") == profile.get("htslib_version")
            for dependency in generic_profile.get("dependencies", [])
        )
    ):
        raise ToolchainProfileError(
            f"Generic scientific profile {profile_id!r} disagrees with the BCFtools/HTSlib registry."
        )
    if profile.get("status") != "SOFTWARE_QUALIFIED":
        raise ToolchainProfileError(
            f"BCFtools/HTSlib profile {profile_id!r} is not software-qualified for production."
        )
    if profile.get("security_review", {}).get("status") != "PATCHED_UPSTREAM_RELEASE":
        raise ToolchainProfileError(
            f"BCFtools/HTSlib profile {profile_id!r} has no approved security review."
        )
    if profile.get("bcftools_version") != bcftools_version:
        raise ToolchainProfileError(
            f"Profile {profile_id!r} requires BCFtools {profile.get('bcftools_version')}; "
            f"configured {bcftools_version}."
        )
    if profile.get("htslib_version") != htslib_version:
        raise ToolchainProfileError(
            f"Profile {profile_id!r} requires HTSlib {profile.get('htslib_version')}; "
            f"configured {htslib_version}."
        )
    for artifact_key in ("environment_file", "lock_file"):
        artifact = profile.get(artifact_key)
        if not isinstance(artifact, str) or not artifact.strip():
            raise ToolchainProfileError(f"Profile {profile_id!r} is missing {artifact_key}.")
        artifact_path = CONFIG_ROOT / artifact
        if not artifact_path.is_file():
            raise ToolchainProfileError(
                f"Profile {profile_id!r} references a missing {artifact_key}: {artifact}."
            )
    lock_text = (CONFIG_ROOT / profile["lock_file"]).read_text(encoding="utf-8")
    if "@EXPLICIT" not in lock_text or f"# platform: {profile.get('platform')}" not in lock_text:
        raise ToolchainProfileError(f"Profile {profile_id!r} has an invalid platform-specific explicit lock.")
    return dict(profile)



def resolve_registered_toolchain_profile(profile_id: str) -> dict[str, Any]:
    """Resolve a selectable profile without requiring this API process to run its binaries.

    The worker image performs the second, local executable attestation before it
    consumes the profile's queue. API-side selection is limited to profiles
    that have passed the complete software/image qualification gate.
    """
    registry = load_toolchain_registry()
    matches = [item for item in registry["profiles"] if item.get("id") == profile_id]
    if len(matches) != 1:
        raise ToolchainProfileError(f"Unknown BCFtools/HTSlib profile: {profile_id!r}.")
    candidate = matches[0]
    profile = resolve_toolchain_profile(
        profile_id,
        bcftools_version=str(candidate.get("bcftools_version") or ""),
        htslib_version=str(candidate.get("htslib_version") or ""),
    )
    queue = profile.get("worker_queue")
    if not isinstance(queue, str) or not queue.startswith("bioinformatics.bcftools.") or len(queue) > 128:
        raise ToolchainProfileError(f"Profile {profile_id!r} has no valid isolated worker queue.")
    lock_path = CONFIG_ROOT / profile["lock_file"]
    profile["lock_sha256"] = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    return profile



def assert_analysis_toolchain_matches_worker(
    analysis: Any,
    *,
    worker_profile_id: str,
    worker_bcftools_version: str,
    worker_htslib_version: str,
) -> None:
    """Fail closed if a task reaches a worker with a different native toolchain."""
    expected = (
        str(getattr(analysis, "toolchain_profile_id", None) or worker_profile_id),
        str(getattr(analysis, "toolchain_bcftools_version", None) or worker_bcftools_version),
        str(getattr(analysis, "toolchain_htslib_version", None) or worker_htslib_version),
    )
    actual = (worker_profile_id, worker_bcftools_version, worker_htslib_version)
    if expected != actual:
        raise ToolchainProfileError(
            "ANALYSIS_TOOLCHAIN_WORKER_MISMATCH: analysis requires "
            f"{expected[0]} (BCFtools {expected[1]}, HTSlib {expected[2]}), "
            f"but this worker runs {actual[0]} (BCFtools {actual[1]}, HTSlib {actual[2]})."
        )
    snapshot = getattr(analysis, "toolchain_snapshot", None)
    registered = resolve_registered_toolchain_profile(expected[0])
    queue = str(getattr(analysis, "toolchain_queue", None) or registered["worker_queue"])
    if queue != registered.get("worker_queue"):
        raise ToolchainProfileError(
            "ANALYSIS_TOOLCHAIN_QUEUE_MISMATCH: persisted worker queue does not match "
            "the registered profile routing contract."
        )
    if isinstance(snapshot, dict) and snapshot:
        if (
            snapshot.get("profile_id") != expected[0]
            or snapshot.get("bcftools_version") != expected[1]
            or snapshot.get("htslib_version") != expected[2]
            or snapshot.get("worker_queue") != queue
            or snapshot.get("platform") != registered.get("platform")
            or snapshot.get("lock_file") != registered.get("lock_file")
            or snapshot.get("lock_sha256") != registered.get("lock_sha256")
        ):
            raise ToolchainProfileError(
                "ANALYSIS_TOOLCHAIN_SNAPSHOT_MISMATCH: persisted profile columns "
                "do not match the immutable analysis toolchain snapshot."
            )
