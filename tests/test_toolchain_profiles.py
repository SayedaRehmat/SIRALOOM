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
        resolve_toolchain_profile(profile_id, bcftools_version="1.24.1", htslib_version="1.24.1")
    assert profile["installation_method"] == "verified_source_build"
    assert profile["platform"] == "linux-64"
    assert profile["security_review"]["status"] == "PATCHED_UPSTREAM_RELEASE"
    assert profile["worker_queue"] == "bioinformatics.bcftools.1_24_1"
    assert len(profile["source_archives"]) == 2
    assert all(len(item["sha256"]) == 64 for item in profile["source_archives"])
    assert (ROOT / profile["lock_file"]).is_file()


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


def test_profile_registry_rejects_unregistered_historical_toolchain(tmp_path):
    with pytest.raises(ToolchainProfileError, match="Unknown BCFtools/HTSlib profile"):
        resolve_toolchain_profile(
            "bcftools-1.19-htslib-1.19-linux-64",
            bcftools_version="1.19",
            htslib_version="1.19",
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

    analysis = SimpleNamespace(
        toolchain_profile_id=PROFILE_ID,
        toolchain_bcftools_version="1.25",
        toolchain_htslib_version="1.25",
        toolchain_queue="bioinformatics.bcftools.1_25",
        toolchain_snapshot={
            "profile_id": PROFILE_ID,
            "bcftools_version": "1.25",
            "htslib_version": "1.25",
            "worker_queue": "bioinformatics.bcftools.1_25",
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
