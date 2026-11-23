from uuid import uuid4

import pytest

from backend.app.api.v1 import analyses as analysis_routes
from backend.app.application import analysis as analysis_application
from backend.app.auth.principal import Principal
from backend.app.domain.toolchain_profiles import (
    ToolchainProfileError,
    enabled_toolchain_profile_ids,
)

DEFAULT = "bcftools-1.25-htslib-1.25-linux-64"
PROFILE_124 = "bcftools-1.24.1-htslib-1.24.1-linux-64-source"
PROFILE_123 = "bcftools-1.23.3-htslib-1.23.3-linux-64-source"


def test_enabled_profiles_always_include_default_and_only_explicit_additions():
    assert enabled_toolchain_profile_ids(DEFAULT, f"{PROFILE_124},{PROFILE_123}") == (
        DEFAULT,
        PROFILE_124,
        PROFILE_123,
    )
    assert enabled_toolchain_profile_ids(DEFAULT, "") == (DEFAULT,)


def test_unqualified_profile_cannot_be_enabled():
    with pytest.raises(ToolchainProfileError, match="not software-qualified"):
        enabled_toolchain_profile_ids(DEFAULT, "bcftools-1.21.3-htslib-1.21.3-linux-64-source")


def test_default_profile_repeated_in_allowlist_is_deduplicated():
    assert enabled_toolchain_profile_ids(DEFAULT, f"{DEFAULT},{PROFILE_124}") == (
        DEFAULT,
        PROFILE_124,
    )


def test_profile_discovery_returns_only_deployment_enabled_profiles(monkeypatch):
    monkeypatch.setattr(analysis_routes.settings, "bcftools_profile_id", DEFAULT)
    monkeypatch.setattr(analysis_routes.settings, "bcftools_enabled_profile_ids", PROFILE_124)
    result = analysis_routes.list_toolchain_profiles(
        Principal(user_id=uuid4(), organization_id=uuid4(), role="bioinformatician", subject="test")
    )
    assert [item["id"] for item in result] == [DEFAULT, PROFILE_124]
    assert result[0]["is_default"] is True
    assert result[1]["is_default"] is False
    assert result[1]["bcftools_version"] == "1.24.1"
    assert "lock_file" not in result[1]


def _create_analysis_with_fake_db(monkeypatch, requested_profile):
    from types import SimpleNamespace

    from backend.app.infrastructure.db.models import Artifact, Specimen

    case_id, artifact_id, specimen_id = uuid4(), uuid4(), uuid4()
    artifact = SimpleNamespace(case_id=case_id, specimen_id=specimen_id)
    specimen = SimpleNamespace(id=specimen_id, case_id=case_id, metadata_json={"vcf_sample_name": "SAMPLE"})

    class FakeDB:
        def get(self, model, _identifier):
            return artifact if model is Artifact else specimen if model is Specimen else None

        def add(self, _record):
            return None

    monkeypatch.setattr(analysis_application, "validate_analysis_input_artifact", lambda *_args: None)
    monkeypatch.setattr(analysis_routes.settings, "bcftools_profile_id", DEFAULT)
    monkeypatch.setattr(analysis_routes.settings, "bcftools_enabled_profile_ids", PROFILE_124)
    return analysis_application.create_analysis(
        FakeDB(),
        case_id=case_id,
        input_artifact_id=artifact_id,
        assay_id=None,
        analysis_type="VARIANT_INTERPRETATION",
        workflow_id="variant-v1",
        workflow_version="2.1",
        reference_build="GRCh38",
        configuration={},
        created_by=None,
        toolchain_profile_id=requested_profile,
        commit=False,
    )


def test_analysis_creation_rejects_non_deployment_profile(monkeypatch):
    with pytest.raises(ValueError, match="not enabled in this laboratory deployment"):
        _create_analysis_with_fake_db(monkeypatch, PROFILE_123)


def test_analysis_creation_persists_selected_profile_and_queue(monkeypatch):
    analysis = _create_analysis_with_fake_db(monkeypatch, PROFILE_124)
    assert analysis.toolchain_profile_id == PROFILE_124
    assert analysis.toolchain_snapshot["profile_id"] == PROFILE_124
    assert analysis.toolchain_queue == "bioinformatics.bcftools.1_24_1"
