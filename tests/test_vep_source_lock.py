from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "configs/bioinformatics/profiles/vep-115.2-source.lock.json"
sys.path.insert(0, str(ROOT / "scripts"))
from validate_vep_source_lock import validate_lock


def test_vep_source_lock_pins_software_and_api_release_commits():
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    validate_lock(document)
    repos = {item["name"]: item["commit"] for item in document["upstream_repositories"]}
    assert repos["ensembl-vep"] == "2beada0d57ca6234f467b14a6c60280f4a082717"
    assert len(repos) == 5


def test_vep_software_version_is_not_confused_with_cache_release():
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert document["software_version"] == "115.2"
    assert document["cache_release"] == "115"


def test_vep_source_lock_does_not_claim_environment_qualification():
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert document["lock_scope"] == "upstream_source_identity_only"
    assert document["qualification_status"] == "CANDIDATE"
    assert document["unresolved_lock_inputs"]


def test_vep_source_lock_rejects_moving_or_untrusted_git_refs():
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    document["upstream_repositories"][0]["commit"] = "release/115.2"
    with pytest.raises(ValueError, match="immutable Git commit"):
        validate_lock(document)


def test_vep_source_lock_rejects_missing_architecture():
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    document["target_architectures"] = ["x86_64"]
    with pytest.raises(ValueError, match="both native architectures"):
        validate_lock(document)
