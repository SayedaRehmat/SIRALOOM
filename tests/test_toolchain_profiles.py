from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.domain.toolchain_profiles import (
    ToolchainProfileError,
    resolve_toolchain_profile,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs" / "bioinformatics" / "toolchain-profiles.v1.json"
PROFILE_ID = "bcftools-1.25-htslib-1.25-linux-64"


def test_resolves_registered_software_qualified_patched_profile():
    profile = resolve_toolchain_profile(
        PROFILE_ID,
        bcftools_version="1.25",
        htslib_version="1.25",
    )
    assert profile["status"] == "SOFTWARE_QUALIFIED"
    assert profile["platform"] == "linux-64"
    assert "# platform: linux-64" in (ROOT / profile["lock_file"]).read_text(encoding="utf-8")
    assert profile["security_review"]["status"] == "PATCHED_UPSTREAM_RELEASE"
    assert profile["lock_file"] == "configs/bioinformatics/profiles/bcftools-1.25-linux-64.lock"


def test_1_24_1_profile_remains_candidate_until_runtime_image_gate_passes():
    profile_id = "bcftools-1.24.1-htslib-1.24.1-linux-64-source"
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    profile = next(item for item in payload["profiles"] if item["id"] == profile_id)
    assert profile["status"] == "CANDIDATE"
    with pytest.raises(ToolchainProfileError, match="not software-qualified"):
        resolve_toolchain_profile(profile_id, bcftools_version="1.24.1", htslib_version="1.24.1", registry_path=REGISTRY)
    assert profile["installation_method"] == "verified_source_build"
    assert profile["build_script"] == "scripts/build_bcftools_from_profile.sh"
    assert profile["dockerfile"] == "docker/backend-bcftools-source.Dockerfile"
    assert [item["name"] for item in profile["source_archives"]] == [
        "htslib-1.24.1.tar.bz2",
        "bcftools-1.24.1.tar.bz2",
    ]
    assert all(item["url"].startswith("https://") for item in profile["source_archives"])
    assert profile["platform"] == "linux-64"
    assert profile["security_review"]["status"] == "PATCHED_UPSTREAM_RELEASE"
    assert profile["worker_queue"] == "bioinformatics.bcftools.1_24_1"
    assert len(profile["source_archives"]) == 2
    assert all(len(item["sha256"]) == 64 for item in profile["source_archives"])
    assert (ROOT / profile["lock_file"]).is_file()
    build_lock = (ROOT / profile["lock_file"]).read_text(encoding="utf-8")
    assert "conda-forge/linux-64/python-3.12.16-h5f976f7_0_cpython.conda" in build_lock
    assert "conda-forge/noarch/python-3.12.16" not in build_lock


@pytest.mark.parametrize(
    ("bcftools_version", "htslib_version"),
    [("1.24", "1.25"), ("1.25", "1.24")],
)
def test_profile_rejects_independent_bcftools_or_htslib_version_drift(
    bcftools_version, htslib_version
):
    with pytest.raises(ToolchainProfileError, match="requires"):
        resolve_toolchain_profile(
            PROFILE_ID,
            bcftools_version=bcftools_version,
            htslib_version=htslib_version,
        )


def test_generic_runtime_dockerfile_pins_both_base_images_by_digest():
    dockerfile = (ROOT / "docker/backend-bcftools-source.Dockerfile").read_text(encoding="utf-8")
    assert "FROM mambaorg/micromamba:2.3.1@sha256:6113627f42f39d065f116b8649e3f699ed2bbe076a58b64ae50fafb4acb8aaf3 AS bcftools-source-build" in dockerfile
    assert "ARG BCFTOOLS_BASE_IMAGE=python:3.12-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30" in dockerfile


@pytest.mark.parametrize(
    ("service", "compose_profile", "profile_id", "bcftools_version", "htslib_version", "queue", "lock_file"),
    [
        ("worker-bcftools-1-24-1", "bcftools-1.24.1", "bcftools-1.24.1-htslib-1.24.1-linux-64-source", "1.24.1", "1.24.1", "bioinformatics.bcftools.1_24_1", "configs/bioinformatics/profiles/bcftools-1.24.1-build-linux-64.lock"),
        ("worker-bcftools-1-23-3", "bcftools-1.23.3", "bcftools-1.23.3-htslib-1.23.3-linux-64-source", "1.23.3", "1.23.3", "bioinformatics.bcftools.1_23_3", "configs/bioinformatics/profiles/bcftools-1.23.3-htslib-1.23.3-linux-64-build.lock"),
        ("worker-bcftools-1-22-3", "bcftools-1.22.3", "bcftools-1.22.3-htslib-1.22.4-linux-64-source", "1.22.3", "1.22.4", "bioinformatics.bcftools.1_22_4", "configs/bioinformatics/profiles/bcftools-1.22.3-htslib-1.22.4-linux-64-build.lock"),
        ("worker-bcftools-1-21-3", "bcftools-1.21.3", "bcftools-1.21.3-htslib-1.21.3-linux-64-source", "1.21.3", "1.21.3", "bioinformatics.bcftools.1_21_3", "configs/bioinformatics/profiles/bcftools-1.21.3-htslib-1.21.3-linux-64-build.lock"),
    ],
)
def test_production_compose_workers_match_registered_profile_contract(
    service, compose_profile, profile_id, bcftools_version, htslib_version, queue, lock_file
):
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.production.yml").read_text(encoding="utf-8"))
    worker = compose["services"][service]
    assert compose_profile in worker["profiles"]
    assert worker["build"]["dockerfile"] == "docker/backend-bcftools-source.Dockerfile"
    args = worker["build"]["args"]
    assert args["BCFTOOLS_PROFILE_ID"] == profile_id
    assert args["BCFTOOLS_VERSION"] == bcftools_version
    assert args["HTSLIB_VERSION"] == htslib_version
    assert args["BCFTOOLS_BUILD_LOCK_FILE"] == lock_file
    assert args["BCFTOOLS_WORKER_QUEUE"] == queue
    assert worker["environment"]["BCFTOOLS_PROFILE_ID"] == profile_id
    assert worker["environment"]["BCFTOOLS_VERSION"] == bcftools_version
    assert worker["environment"]["HTSLIB_VERSION"] == htslib_version
    assert worker["environment"]["CELERY_QUEUES"] == queue


def test_1_21_3_remains_candidate_while_vcf45_len_regression_is_unresolved():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    profile = next(
        item for item in payload["profiles"]
        if item["id"] == "bcftools-1.21.3-htslib-1.21.3-linux-64-source"
    )
    assert profile["status"] == "BLOCKED_COMPATIBILITY"
    assert any(
        "test_vcf45_len_reference_block_csi_index_includes_last_covered_base" in gap
        for gap in profile.get("qualification_gaps", [])
    )
    with pytest.raises(ToolchainProfileError, match="not software-qualified"):
        resolve_toolchain_profile(
            profile["id"],
            bcftools_version="1.21.3",
            htslib_version="1.21.3",
        )


def test_1_19_is_registered_but_quarantined_from_production():
    profile_id = "bcftools-1.19-htslib-1.19-linux-64-legacy"
    profile = next(
        item for item in json.loads(REGISTRY.read_text(encoding="utf-8"))["profiles"]
        if item["id"] == profile_id
    )
    assert profile["status"] == "QUARANTINED_LEGACY"
    assert profile["security_review"]["status"] == "UNPATCHED_LEGACY_BLOCKED"
    with pytest.raises(ToolchainProfileError, match="not software-qualified"):
        resolve_toolchain_profile(
            profile_id,
            bcftools_version="1.19",
            htslib_version="1.19",
        )


@pytest.mark.parametrize(
    ("profile_id", "bcftools_version", "htslib_version", "queue"),
    [
        ("bcftools-1.23.3-htslib-1.23.3-linux-64-source", "1.23.3", "1.23.3", "bioinformatics.bcftools.1_23_3"),
        ("bcftools-1.22.3-htslib-1.22.4-linux-64-source", "1.22.3", "1.22.4", "bioinformatics.bcftools.1_22_4"),
        ("bcftools-1.21.3-htslib-1.21.3-linux-64-source", "1.21.3", "1.21.3", "bioinformatics.bcftools.1_21_3"),
    ],
)
def test_patched_source_profiles_have_independent_locks_and_exact_version_pairs(
    profile_id, bcftools_version, htslib_version, queue
):
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    profile = next(item for item in payload["profiles"] if item["id"] == profile_id)
    assert profile["status"] == "CANDIDATE"
    assert profile["bcftools_version"] == bcftools_version
    assert profile["htslib_version"] == htslib_version
    assert profile["worker_queue"] == queue
    assert profile["security_review"]["status"] == "PATCHED_UPSTREAM_RELEASE"
    assert profile["installation_method"] == "verified_source_build"
    assert len(profile["source_archives"]) == 2
    assert all(len(item["sha256"]) == 64 for item in profile["source_archives"])
    assert (ROOT / profile["environment_file"]).is_file()
    assert (ROOT / profile["lock_file"]).is_file()
    lock = (ROOT / profile["lock_file"]).read_text(encoding="utf-8")
    assert "@EXPLICIT" in lock
    assert "# platform: linux-64" in lock


def test_profile_registry_does_not_allow_candidate_profiles(tmp_path):
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["profiles"][0]["status"] = "CANDIDATE"
    candidate_registry = tmp_path / "profiles.json"
    candidate_registry.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ToolchainProfileError, match="not software-qualified"):
        resolve_toolchain_profile(
            PROFILE_ID,
            bcftools_version="1.25",
            htslib_version="1.25",
            registry_path=candidate_registry,
        )


def test_analysis_worker_profile_match_requires_exact_profile_and_versions():
    from types import SimpleNamespace

    from backend.app.domain.toolchain_profiles import (
        assert_analysis_toolchain_matches_worker,
    )

    from backend.app.domain.toolchain_profiles import resolve_registered_toolchain_profile
    profile = resolve_registered_toolchain_profile(PROFILE_ID)
    analysis = SimpleNamespace(
        toolchain_profile_id=PROFILE_ID,
        toolchain_bcftools_version="1.25",
        toolchain_htslib_version="1.25",
        toolchain_queue=profile["worker_queue"],
        toolchain_snapshot={
            "profile_id": PROFILE_ID,
            "bcftools_version": "1.25",
            "htslib_version": "1.25",
            "worker_queue": profile["worker_queue"],
            "platform": profile["platform"],
            "lock_file": profile["lock_file"],
            "lock_sha256": profile["lock_sha256"],
        },
    )
    assert_analysis_toolchain_matches_worker(
        analysis,
        worker_profile_id=PROFILE_ID,
        worker_bcftools_version="1.25",
        worker_htslib_version="1.25",
    )


def test_analysis_worker_rejects_a_different_toolchain_profile():
    from types import SimpleNamespace

    from backend.app.domain.toolchain_profiles import (
        ToolchainProfileError,
        assert_analysis_toolchain_matches_worker,
    )

    analysis = SimpleNamespace(
        toolchain_profile_id=PROFILE_ID,
        toolchain_bcftools_version="1.25",
        toolchain_htslib_version="1.25",
        toolchain_queue="bioinformatics.bcftools.1_25",
        toolchain_snapshot={},
    )
    with pytest.raises(ToolchainProfileError, match="ANALYSIS_TOOLCHAIN_WORKER_MISMATCH"):
        assert_analysis_toolchain_matches_worker(
            analysis,
            worker_profile_id="bcftools-1.24.1-htslib-1.24.1-linux-64-source",
            worker_bcftools_version="1.24.1",
            worker_htslib_version="1.24.1",
        )


def test_analysis_worker_rejects_snapshot_or_queue_drift():
    from types import SimpleNamespace

    from backend.app.domain.toolchain_profiles import (
        ToolchainProfileError,
        assert_analysis_toolchain_matches_worker,
    )

    analysis = SimpleNamespace(
        toolchain_profile_id=PROFILE_ID,
        toolchain_bcftools_version="1.25",
        toolchain_htslib_version="1.25",
        toolchain_queue="bioinformatics.bcftools.1_24_1",
        toolchain_snapshot={},
    )
    with pytest.raises(ToolchainProfileError, match="ANALYSIS_TOOLCHAIN_QUEUE_MISMATCH"):
        assert_analysis_toolchain_matches_worker(
            analysis,
            worker_profile_id=PROFILE_ID,
            worker_bcftools_version="1.25",
            worker_htslib_version="1.25",
        )
