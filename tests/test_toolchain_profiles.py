from __future__ import annotations

import json
import subprocess
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


def test_1_24_1_profile_is_software_qualified_after_runtime_image_gate_passes():
    profile_id = "bcftools-1.24.1-htslib-1.24.1-linux-64-source"
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    profile = next(item for item in payload["profiles"] if item["id"] == profile_id)
    assert profile["status"] == "SOFTWARE_QUALIFIED"
    resolved = resolve_toolchain_profile(
        profile_id,
        bcftools_version="1.24.1",
        htslib_version="1.24.1",
        registry_path=REGISTRY,
    )
    assert resolved["id"] == profile_id
    assert "isolated non-root runtime image checks" in resolved["qualification_scope"]
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


@pytest.mark.parametrize(
    ("profile_id", "release_folder", "expected_advisory_count"),
    [
        ("bcftools-1.25-htslib-1.25-linux-64", "1.25", 11),
        ("bcftools-1.24.1-htslib-1.24.1-linux-64-source", "1.24.1", 11),
        ("bcftools-1.23.3-htslib-1.23.3-linux-64-source", "1.23.3", 11),
        ("bcftools-1.22.3-htslib-1.22.4-linux-64-source", "1.22.4", 10),
        ("bcftools-1.21.3-htslib-1.21.3-linux-64-source", "1.21.3", 10),
    ],
)
def test_security_review_advisories_match_the_exact_upstream_release(
    profile_id, release_folder, expected_advisory_count
):
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    profile = next(item for item in payload["profiles"] if item["id"] == profile_id)
    review = profile["security_review"]
    assert review["status"] == "PATCHED_UPSTREAM_RELEASE"
    assert len(review["advisories_reviewed"]) == expected_advisory_count
    assert review["release_notes_url"] == (
        f"https://sourceforge.net/projects/samtools/files/samtools/{release_folder}/"
    )
    assert review["reviewed_on"] == "2026-11-05"


def test_generic_runtime_dockerfile_pins_both_base_images_by_digest():
    dockerfile = (ROOT / "docker/backend-bcftools-source.Dockerfile").read_text(encoding="utf-8")
    assert "ARG BCFTOOLS_BUILDER_IMAGE=mambaorg/micromamba:2.3.1@sha256:6113627f42f39d065f116b8649e3f699ed2bbe076a58b64ae50fafb4acb8aaf3" in dockerfile
    assert "FROM ${BCFTOOLS_BUILDER_IMAGE} AS bcftools-source-build" in dockerfile
    assert "ARG BCFTOOLS_BASE_IMAGE=python:3.12-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30" in dockerfile
    assert "ARG DEBIAN_SNAPSHOT_TIMESTAMP=20261105T000000Z" in dockerfile
    assert "printf '%s\\n'" in dockerfile
    assert "trixie main" in dockerfile

    assert "printf '%s\\n' \"deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian/${DEBIAN_SNAPSHOT_TIMESTAMP}/ trixie-updates main\"" in dockerfile
    assert "printf '%s\\n' \"deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT_TIMESTAMP}/ trixie-security main\"" in dockerfile
    assert "main\\\\\\\\n" not in dockerfile
    assert "APT::Update::Error-Mode=any update" in dockerfile
    assert "for attempt in 1 2 3 4 5; do" in dockerfile
    assert 'sleep "$((attempt * 10))"' in dockerfile
    assert 'test "$apt_update_succeeded" = 1' in dockerfile
    assert "ca-certificates libcairo2" in dockerfile
    assert "test -s /etc/ssl/certs/ca-certificates.crt" in dockerfile
    assert "ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt SSL_CERT_DIR=/etc/ssl/certs" in dockerfile
    assert "ssl.get_default_verify_paths()" in dockerfile
    assert "ARG UV_ARCHIVE_SHA256_X86_64=230e328948c92dd1ebad83949c4d56e83813dfe9c6362a4c519e6a227973f1ae" in dockerfile
    assert "ARG UV_ARCHIVE_SHA256_AARCH64=c300afd5f2d31df039fe6a26a2d68a76b62832098c272a43e1e74ab9efd4fbd7" in dockerfile
    assert "aarch64:linux-aarch64" in dockerfile
    assert "uv-aarch64-unknown-linux-gnu.tar.gz" in dockerfile
    assert "uv archive SHA-256 mismatch" in dockerfile


def test_default_runtime_dockerfile_pins_all_inputs_and_fails_closed_outside_amd64():
    dockerfile = (ROOT / "docker/backend.Dockerfile").read_text(encoding="utf-8")
    assert "FROM mambaorg/micromamba:2.3.1@sha256:6113627f42f39d065f116b8649e3f699ed2bbe076a58b64ae50fafb4acb8aaf3 AS bcftools" in dockerfile
    assert "ARG BCFTOOLS_BASE_IMAGE=python:3.12-slim-trixie@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30" in dockerfile
    assert "FROM ${BCFTOOLS_BASE_IMAGE}" in dockerfile
    assert "x86_64:linux-64) ;;" in dockerfile
    assert "aarch64:linux-aarch64" not in dockerfile
    assert "ARG DEBIAN_SNAPSHOT_TIMESTAMP=20261105T000000Z" in dockerfile
    assert "printf" in dockerfile
    assert "trixie main" in dockerfile
    assert "trixie-updates main" in dockerfile
    assert "trixie-security main" in dockerfile
    assert "APT::Update::Error-Mode=any update" in dockerfile
    assert "for attempt in 1 2 3 4 5; do" in dockerfile
    assert 'sleep "$((attempt * 10))"' in dockerfile
    assert 'test "$apt_update_succeeded" = 1' in dockerfile
    assert "ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt SSL_CERT_DIR=/etc/ssl/certs" in dockerfile
    assert "ARG UV_ARCHIVE_SHA256=230e328948c92dd1ebad83949c4d56e83813dfe9c6362a4c519e6a227973f1ae" in dockerfile
    assert "uv archive SHA-256 mismatch" in dockerfile



def test_pinned_snapshot_retry_loop_retries_transient_apt_failures():
    dockerfile = (ROOT / "docker/backend-bcftools-source.Dockerfile").read_text(encoding="utf-8")
    loop = dockerfile.split("    && apt_update_succeeded=0 \\\n", 1)[1].split(
        "    && apt-get install", 1
    )[0]
    script = """set -eu
apt_calls=0
sleep_calls=0
apt_get() {
    apt_calls=$((apt_calls + 1))
    [ "$apt_calls" -ge 3 ]
}
sleep() {
    sleep_calls=$((sleep_calls + 1))
}
apt_update_succeeded=0 \\
""" + loop.replace("apt-get", "apt_get")
    script = script.replace(
        '&& test "$apt_update_succeeded" = 1',
        '&& test "$apt_update_succeeded" = 1 && test "$apt_calls" = 3 && test "$sleep_calls" = 2',
    )
    subprocess.run(["/bin/sh", "-c", script], check=True, capture_output=True, text=True)



def test_source_profile_matrix_runs_on_main_and_serializes_snapshot_image_builds():
    workflow = (ROOT / ".github/workflows/bcftools-source-profile-matrix.yml").read_text(encoding="utf-8")
    assert "      - main" in workflow
    assert "feat/bcftools-toolchain-qualification-rebased" not in workflow
    assert "      max-parallel: 1" in workflow
    assert "APT::Update::Error-Mode=any update" in (ROOT / "docker/backend-bcftools-source.Dockerfile").read_text(encoding="utf-8")



def test_legacy_1_24_1_builder_is_removed_in_favor_of_generic_profile_contract():
    assert not (ROOT / "docker/backend-bcftools-1.24.1.Dockerfile").exists()
    assert not (ROOT / "scripts/build_bcftools_1_24_1.sh").exists()
    assert not (ROOT / ".github/workflows/bcftools-1.24.1-profile.yml").exists()
    assert not (ROOT / ".github/workflows/bcftools-1.24.1-build-lock.yml").exists()
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    matrix = (ROOT / ".github/workflows/bcftools-source-profile-matrix.yml").read_text(encoding="utf-8")
    assert "Build isolated BCFtools 1.24.1 laboratory backend image" not in ci
    assert "docker/backend-bcftools-source.Dockerfile" in matrix
    assert "Discover immutable source-build profiles" in matrix
    assert "      - main" in ci



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


def test_1_21_3_is_blocked_while_vcf45_len_regression_is_unresolved():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    profile = next(
        item for item in payload["profiles"]
        if item["id"] == "bcftools-1.21.3-htslib-1.21.3-linux-64-source"
    )
    assert profile["status"] == "BLOCKED_COMPATIBILITY"
    assert (ROOT / profile["environment_file"]).is_file()
    assert (ROOT / profile["lock_file"]).is_file()
    assert len(profile["source_archives"]) == 2
    archive_hashes = {item["name"]: item["sha256"] for item in profile["source_archives"]}
    assert archive_hashes["htslib-1.21.3.tar.bz2"] == "e97593ecf45b941e09b292941a7e1a7a17139ebed56c642874b88075491aa8e4"
    assert archive_hashes["bcftools-1.21.3.tar.bz2"] == "6fb32e80ac05b35684ef95f8a5c3b33eaf265ebc78a2218a8c177f9fa94ed889"
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
    ("profile_id", "bcftools_version", "htslib_version", "queue", "htslib_sha256", "bcftools_sha256"),
    [
        ("bcftools-1.23.3-htslib-1.23.3-linux-64-source", "1.23.3", "1.23.3", "bioinformatics.bcftools.1_23_3", "c460ffc5b79ea64d4feacd84f7e98968a66c30fbe34e5602f1384f0892f83c23", "b2b6488b71a4086f138f13f26ae4a47cb277690d28d34bc5e4e61c34c4220694"),
        ("bcftools-1.22.3-htslib-1.22.4-linux-64-source", "1.22.3", "1.22.4", "bioinformatics.bcftools.1_22_4", "f5e860a7dfb8cb4c4a06034956a39b6fa95b6d09757b872001ccc6f0c598537c", "361d39ea5afcaed2f633e64d572045f4e1a1cd895c7faf4d615102846d028a95"),
    ],
)
def test_patched_source_profiles_have_independent_locks_and_exact_version_pairs(
    profile_id, bcftools_version, htslib_version, queue, htslib_sha256, bcftools_sha256
):
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    profile = next(item for item in payload["profiles"] if item["id"] == profile_id)
    assert profile["status"] == "SOFTWARE_QUALIFIED"
    assert profile["bcftools_version"] == bcftools_version
    assert profile["htslib_version"] == htslib_version
    assert profile["worker_queue"] == queue
    assert profile["security_review"]["status"] == "PATCHED_UPSTREAM_RELEASE"
    assert profile["installation_method"] == "verified_source_build"
    assert len(profile["source_archives"]) == 2
    archive_hashes = {item["name"]: item["sha256"] for item in profile["source_archives"]}
    assert archive_hashes[f"htslib-{htslib_version}.tar.bz2"] == htslib_sha256
    assert archive_hashes[f"bcftools-{bcftools_version}.tar.bz2"] == bcftools_sha256
    assert (ROOT / profile["environment_file"]).is_file()
    assert (ROOT / profile["lock_file"]).is_file()
    lock = (ROOT / profile["lock_file"]).read_text(encoding="utf-8")
    assert "@EXPLICIT" in lock
    assert "# platform: linux-64" in lock



@pytest.mark.parametrize(
    ("profile_id", "bcftools_version", "htslib_version", "source_id"),
    [
        ("bcftools-1.24.1-htslib-1.24.1-linux-aarch64-source", "1.24.1", "1.24.1", "bcftools-1.24.1-htslib-1.24.1-linux-64-source"),
        ("bcftools-1.23.3-htslib-1.23.3-linux-aarch64-source", "1.23.3", "1.23.3", "bcftools-1.23.3-htslib-1.23.3-linux-64-source"),
        ("bcftools-1.22.3-htslib-1.22.4-linux-aarch64-source", "1.22.3", "1.22.4", "bcftools-1.22.3-htslib-1.22.4-linux-64-source"),
    ],
)
def test_arm64_profiles_are_distinct_candidates_and_not_production_selectable(
    profile_id, bcftools_version, htslib_version, source_id
):
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    profile = next(item for item in payload["profiles"] if item["id"] == profile_id)
    assert profile["status"] == "CANDIDATE"
    assert profile["platform"] == "linux-aarch64"
    assert profile["architecture_candidate_for"] == source_id
    assert profile["bcftools_version"] == bcftools_version
    assert profile["htslib_version"] == htslib_version
    assert profile["worker_queue"].endswith(".arm64")
    assert profile["environment_file"] == "configs/bioinformatics/profiles/bcftools-build-linux-aarch64.yml"
    arm_environment = (ROOT / profile["environment_file"]).read_text(encoding="utf-8")
    assert "sysroot_linux-aarch64=2.28" in arm_environment
    with pytest.raises(ToolchainProfileError, match="not software-qualified"):
        resolve_toolchain_profile(
            profile_id,
            bcftools_version=bcftools_version,
            htslib_version=htslib_version,
        )


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
