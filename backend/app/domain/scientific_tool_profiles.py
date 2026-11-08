from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class ScientificToolProfileError(ValueError):
    """A scientific tool profile is malformed, incompatible or not qualified."""


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = ROOT / "configs" / "bioinformatics" / "scientific-tool-profiles.v1.json"
_SUPPORTED_STATUSES = {
    "SOFTWARE_QUALIFIED",
    "CANDIDATE",
    "BLOCKED_COMPATIBILITY",
    "QUARANTINED_LEGACY",
    "RETIRED",
}
_PLATFORM_ARCHITECTURES = {
    "linux-64": "x86_64",
    "linux-aarch64": "aarch64",
    "osx-64": "x86_64",
    "osx-arm64": "arm64",
    "win-64": "x86_64",
}


def load_scientific_tool_registry(
    registry_path: str | Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    path = Path(registry_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScientificToolProfileError(
            "The scientific tool profile registry is unavailable or invalid."
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "1"
        or payload.get("schema") != "siraloom.scientific-tool-profile-registry"
        or not isinstance(payload.get("profiles"), list)
    ):
        raise ScientificToolProfileError("Unsupported scientific tool profile registry schema.")
    seen: set[str] = set()
    for profile in payload["profiles"]:
        if not isinstance(profile, dict):
            raise ScientificToolProfileError("Scientific tool profiles must be JSON objects.")
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not profile_id.strip() or profile_id in seen:
            raise ScientificToolProfileError("Scientific tool profile IDs must be present and unique.")
        seen.add(profile_id)
        _validate_profile_shape(profile)
    return payload


def _validate_profile_shape(profile: dict[str, Any]) -> None:
    required_strings = (
        "tool_id", "version", "platform", "architecture", "status",
    )
    missing = [key for key in required_strings if not isinstance(profile.get(key), str) or not profile[key].strip()]
    if missing:
        raise ScientificToolProfileError(
            "Scientific tool profile is missing: " + ", ".join(missing)
        )
    if profile["status"] not in _SUPPORTED_STATUSES:
        raise ScientificToolProfileError(f"Unknown scientific tool qualification status: {profile['status']!r}.")
    expected_architecture = _PLATFORM_ARCHITECTURES.get(profile["platform"])
    if expected_architecture is None or profile["architecture"] != expected_architecture:
        raise ScientificToolProfileError(
            f"Profile {profile['id']!r} has inconsistent platform/architecture identity."
        )
    methods = profile.get("execution_methods")
    if not isinstance(methods, list) or not methods or any(
        item not in {"LOCAL_PROCESS", "OCI_CONTAINER", "REMOTE_AGENT"} for item in methods
    ):
        raise ScientificToolProfileError(f"Profile {profile['id']!r} has invalid execution_methods.")
    dependencies = profile.get("dependencies")
    if not isinstance(dependencies, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip()
        for item in dependencies
    ):
        raise ScientificToolProfileError(f"Profile {profile['id']!r} has invalid dependencies.")
    executable = profile.get("executable_identity")
    if not isinstance(executable, dict) or not isinstance(executable.get("name"), str):
        raise ScientificToolProfileError(f"Profile {profile['id']!r} has no executable identity contract.")
    if not isinstance(executable.get("version_args"), list) or not executable["version_args"]:
        raise ScientificToolProfileError(f"Profile {profile['id']!r} has no version attestation arguments.")
    if not isinstance(executable.get("sha256_policy"), str) or not executable["sha256_policy"]:
        raise ScientificToolProfileError(f"Profile {profile['id']!r} has no executable digest policy.")
    if not isinstance(profile.get("resource_requirements"), dict):
        raise ScientificToolProfileError(f"Profile {profile['id']!r} has no resource requirements.")
    if not isinstance(profile.get("installation"), dict):
        raise ScientificToolProfileError(f"Profile {profile['id']!r} has no installation contract.")
    if not isinstance(profile.get("routing"), dict):
        raise ScientificToolProfileError(f"Profile {profile['id']!r} has no routing contract.")
    qualification = profile.get("qualification")
    if not isinstance(qualification, dict) or qualification.get("status") != profile["status"]:
        raise ScientificToolProfileError(
            f"Profile {profile['id']!r} qualification status does not match its registry status."
        )


def resolve_scientific_tool_profile(
    profile_id: str,
    *,
    tool_id: str | None = None,
    platform: str | None = None,
    execution_method: str | None = None,
    registry_path: str | Path = DEFAULT_REGISTRY,
    require_qualified: bool = True,
) -> dict[str, Any]:
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ScientificToolProfileError("An explicit scientific tool profile ID is required.")
    registry = load_scientific_tool_registry(registry_path)
    matches = [item for item in registry["profiles"] if item["id"] == profile_id]
    if len(matches) != 1:
        raise ScientificToolProfileError(f"Unknown scientific tool profile: {profile_id!r}.")
    profile = dict(matches[0])
    if tool_id is not None and profile["tool_id"] != tool_id:
        raise ScientificToolProfileError(
            f"Profile {profile_id!r} belongs to {profile['tool_id']!r}, not {tool_id!r}."
        )
    if platform is not None and profile["platform"] != platform:
        raise ScientificToolProfileError(
            f"Profile {profile_id!r} targets {profile['platform']!r}, not {platform!r}."
        )
    if execution_method is not None and execution_method not in profile["execution_methods"]:
        raise ScientificToolProfileError(
            f"Profile {profile_id!r} does not permit execution method {execution_method!r}."
        )
    if require_qualified and profile["status"] != "SOFTWARE_QUALIFIED":
        raise ScientificToolProfileError(
            f"Scientific tool profile {profile_id!r} is {profile['status']} and is not software-qualified; "
            "only SOFTWARE_QUALIFIED profiles are selectable for production."
        )
    installation = profile["installation"]
    lock_file = installation.get("lock_file")
    if require_qualified and lock_file:
        lock_path = ROOT / lock_file
        if not lock_path.is_file():
            raise ScientificToolProfileError(
                f"Qualified profile {profile_id!r} references a missing dependency lock."
            )
    return profile
