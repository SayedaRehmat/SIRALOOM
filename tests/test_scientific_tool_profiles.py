from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.domain.scientific_tool_profiles import (
    ScientificToolProfileError,
    load_scientific_tool_registry,
    resolve_scientific_tool_profile,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs" / "bioinformatics" / "scientific-tool-profiles.v1.json"


def test_registry_contains_independent_tool_and_architecture_profiles():
    registry = load_scientific_tool_registry(REGISTRY)
    profiles = registry["profiles"]
    assert len({item["id"] for item in profiles}) == len(profiles)
    assert {item["tool_id"] for item in profiles} == {"bcftools", "ensembl-vep"}
    assert any(item["platform"] == "linux-aarch64" for item in profiles)
    assert any(item["platform"] == "linux-64" for item in profiles)


@pytest.mark.parametrize(
    ("profile_id", "tool_version", "platform", "legacy_id"),
    [
        ("bcftools-1.25-htslib-1.25-linux-64", "1.25", "linux-64", "bcftools-1.25-htslib-1.25-linux-64"),
        ("bcftools-1.24.1-htslib-1.24.1-linux-64-source", "1.24.1", "linux-64", "bcftools-1.24.1-htslib-1.24.1-linux-64-source"),
        ("bcftools-1.23.3-htslib-1.23.3-linux-64-source", "1.23.3", "linux-64", "bcftools-1.23.3-htslib-1.23.3-linux-64-source"),
        ("bcftools-1.22.3-htslib-1.22.4-linux-64-source", "1.22.3", "linux-64", "bcftools-1.22.3-htslib-1.22.4-linux-64-source"),
    ],
)
def test_qualified_bcftools_profiles_resolve_with_tool_neutral_contract(
    profile_id, tool_version, platform, legacy_id
):
    profile = resolve_scientific_tool_profile(
        profile_id,
        tool_id="bcftools",
        platform=platform,
        execution_method="OCI_CONTAINER",
        registry_path=REGISTRY,
    )
    assert profile["version"] == tool_version
    assert profile["routing"]["legacy_profile_id"] == legacy_id
    assert profile["executable_identity"]["name"] == "bcftools"
    assert profile["installation"]["lock_file"]
    assert profile["dependencies"][0]["name"] == "HTSlib"


def test_arm64_bcftools_candidates_are_registered_but_not_production_selectable():
    registry = load_scientific_tool_registry(REGISTRY)
    candidates = [
        item for item in registry["profiles"]
        if item["tool_id"] == "bcftools" and item["platform"] == "linux-aarch64"
    ]
    assert len(candidates) == 3
    assert all(item["status"] == "CANDIDATE" for item in candidates)
    for profile in candidates:
        with pytest.raises(ScientificToolProfileError, match="only SOFTWARE_QUALIFIED"):
            resolve_scientific_tool_profile(profile["id"], registry_path=REGISTRY)


def test_vep_has_an_independent_candidate_profile_and_is_not_bcftools():
    profile = resolve_scientific_tool_profile(
        "vep-115-linux-amd64",
        tool_id="ensembl-vep",
        platform="linux-64",
        execution_method="OCI_CONTAINER",
        registry_path=REGISTRY,
        require_qualified=False,
    )
    assert profile["version"] == "115.2"
    cache = next(item for item in profile["dependencies"] if item["name"] == "vep-cache")
    assert cache["version"] == "115"
    assert profile["status"] == "CANDIDATE"
    assert profile["installation"]["dependency_lock"] is None
    assert {item["name"] for item in profile["dependencies"]} >= {
        "perl-runtime", "ensembl-vep-perl-modules", "vep-cache"
    }
    assert profile["resource_requirements"]["cache_mount"] == "read-only"
    with pytest.raises(ScientificToolProfileError, match="only SOFTWARE_QUALIFIED"):
        resolve_scientific_tool_profile("vep-115-linux-amd64", registry_path=REGISTRY)


def test_resolver_rejects_tool_platform_and_executor_mismatch():
    profile_id = "bcftools-1.25-htslib-1.25-linux-64"
    with pytest.raises(ScientificToolProfileError, match="belongs to"):
        resolve_scientific_tool_profile(profile_id, tool_id="ensembl-vep", registry_path=REGISTRY)
    with pytest.raises(ScientificToolProfileError, match="targets"):
        resolve_scientific_tool_profile(profile_id, platform="linux-aarch64", registry_path=REGISTRY)
    with pytest.raises(ScientificToolProfileError, match="does not permit"):
        resolve_scientific_tool_profile(profile_id, execution_method="REMOTE_AGENT", registry_path=REGISTRY)


def test_registry_rejects_duplicate_profile_ids_and_inconsistent_architecture(tmp_path):
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["profiles"].append(dict(payload["profiles"][0]))
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScientificToolProfileError, match="unique"):
        load_scientific_tool_registry(duplicate_path)

    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["profiles"][0]["architecture"] = "aarch64"
    mismatch_path = tmp_path / "mismatch.json"
    mismatch_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScientificToolProfileError, match="inconsistent platform"):
        load_scientific_tool_registry(mismatch_path)


def test_registry_rejects_unqualified_profile_missing_execution_contract(tmp_path):
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["profiles"][0]["resource_requirements"] = None
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScientificToolProfileError, match="resource requirements"):
        load_scientific_tool_registry(malformed_path)
