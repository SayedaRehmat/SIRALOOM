from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ToolchainProfileError(ValueError):
    """The configured scientific toolchain is not a registered safe profile."""


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = REPOSITORY_ROOT / "configs" / "bioinformatics" / "toolchain-profiles.v1.json"


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
    return dict(profile)
