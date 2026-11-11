from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.domain import runtime_attestation as runtime


class _FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1


class _FakeAudit:
    events = []

    def __init__(self, db):
        self.db = db

    def record(self, **kwargs):
        self.events.append(kwargs)


def _analysis():
    return SimpleNamespace(
        id="analysis-001",
        case_id="case-001",
        workflow_version="2.1",
        configuration={
            "assay_validation_snapshot": {
                "pipeline_components": [
                    {"name": "bcftools", "version": "1.25", "sha256": "a" * 64}
                ]
            }
        },
        status="RUNNING",
        completed_at=None,
    )


def test_runtime_manifest_measures_all_required_component_families(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "_bcftools_and_htslib",
        lambda: (Path("/worker/bcftools"), "1.25", "1.25", Path("/worker/libhts.so")),
    )
    monkeypatch.setattr(
        runtime,
        "resolve_registered_toolchain_profile",
        lambda profile_id: {
            "id": profile_id,
            "lock_file": "configs/bioinformatics/toolchain-profiles.v1.json",
        },
    )
    monkeypatch.setattr(runtime, "_sha256_file", lambda path: "a" * 64)
    monkeypatch.setattr(runtime, "_sha256_tree", lambda path: "b" * 64)
    monkeypatch.setattr(
        runtime, "_kubernetes_image_identity",
        lambda: ("sha256:" + "c" * 64, "c" * 64),
    )

    manifest = runtime.collect_runtime_component_manifest(workflow_version="2.1")
    assert {item["name"] for item in manifest} == {
        "bcftools",
        "htslib",
        "native_toolchain_lock",
        "python_dependency_lock",
        "siraloom_variant_workflow",
        "container_image",
    }
    assert next(item for item in manifest if item["name"] == "container_image")["sha256"] == "c" * 64


def test_environment_variable_cannot_substitute_for_orchestrator_image_identity(monkeypatch):
    for key in (
        "POD_NAME",
        "POD_NAMESPACE",
        "SIRALOOM_K8S_CONTAINER_NAME",
        "KUBERNETES_SERVICE_HOST",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SIRALOOM_RUNTIME_IMAGE_DIGEST", "sha256:" + "d" * 64)

    with pytest.raises(runtime.RuntimeAttestationError, match="environment-provided image digest"):
        runtime._kubernetes_image_identity()


def test_runtime_attestation_success_records_hash_chained_event(monkeypatch):
    from backend.app.infrastructure.audit import service

    _FakeAudit.events = []
    monkeypatch.setattr(service, "AuditService", _FakeAudit)
    monkeypatch.setattr(
        runtime,
        "collect_runtime_component_manifest",
        lambda *, workflow_version: [
            {"name": "bcftools", "version": "1.25", "sha256": "a" * 64}
        ],
    )
    monkeypatch.setattr(runtime, "assert_pipeline_components_match_runtime", lambda snapshot, observed: None)

    db = _FakeDB()
    analysis = _analysis()
    accepted, reason = runtime.attest_clinical_analysis_runtime(
        db, analysis, redelivered=False, retry=False
    )

    assert accepted is True
    assert reason is None
    assert db.commits == 1
    assert _FakeAudit.events[0]["event_type"] == "CLINICAL_RUNTIME_ATTESTED"
    assert _FakeAudit.events[0]["payload"]["manifest_sha256"] == runtime.runtime_manifest_sha256(
        [{"name": "bcftools", "version": "1.25", "sha256": "a" * 64}]
    )


def test_runtime_attestation_failure_blocks_analysis_and_records_reason(monkeypatch):
    from backend.app.infrastructure.audit import service

    _FakeAudit.events = []
    monkeypatch.setattr(service, "AuditService", _FakeAudit)

    def missing_image(*, workflow_version):
        raise runtime.RuntimeAttestationError("trusted container image identity is missing")

    monkeypatch.setattr(runtime, "collect_runtime_component_manifest", missing_image)
    db = _FakeDB()
    analysis = _analysis()

    accepted, reason = runtime.attest_clinical_analysis_runtime(
        db, analysis, redelivered=True, retry=True
    )

    assert accepted is False
    assert "trusted container image identity is missing" in reason
    assert analysis.status == "BLOCKED"
    assert analysis.configuration["runtime_attestation_block"] == reason
    assert db.commits == 1
    assert _FakeAudit.events[0]["event_type"] == "CLINICAL_RUNTIME_ATTESTATION_BLOCKED"
    assert _FakeAudit.events[0]["payload"] == {"redelivered": True, "retry": True}
