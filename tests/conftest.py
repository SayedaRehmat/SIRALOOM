import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ARTIFACT_ROOT", str(Path(tempfile.gettempdir()) / "siraloom-tests"))
os.environ.setdefault("GENEBE_ENABLED", "false")

from backend.app.main import app  # noqa: E402, I001


class _TestPersistentExecution:
    """Explicit local executor used only by focused scientific unit tests.

    Production code still rejects a missing case-bound execution service. This
    harness gives unit tests a deterministic injected execution boundary while
    the separate container integration suite exercises the real OCI adapter.
    """

    def __init__(self):
        self.organization_id = uuid4()
        self.analysis_id = uuid4()
        self.environment_registration_id = uuid4()
        self.case_id = uuid4()
        self.worker_id = "pytest-local-executor"
        self.execution_record_ids = []
        self.db = SimpleNamespace(
            get=lambda *_args, **_kwargs: SimpleNamespace(profile_json={})
        )

    def execute(self, profile, request, *, artifact_publisher=None):
        executable = str(profile.executable)
        argv = [executable, *list(request.argv)]
        environment = dict(os.environ)
        environment.update(dict(getattr(request, "environment", {}) or {}))
        completed = subprocess.run(
            argv,
            cwd=str(request.workspace),
            env=environment,
            capture_output=True,
            text=True,
            timeout=max(1, int(request.timeout_seconds)),
            check=False,
        )
        record_id = uuid4()
        self.execution_record_ids.append(record_id)
        return SimpleNamespace(
            result=SimpleNamespace(
                provenance=SimpleNamespace(exit_code=completed.returncode, output_sha256=[]),
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
            ),
            record_id=record_id,
        )


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _inject_explicit_local_execution_for_scientific_unit_tests(monkeypatch, request):
    """Inject a test executor only into unit tests that intentionally run local tools."""
    module = request.module
    module_name = module.__name__.rsplit(".", 1)[-1]
    eligible = {
        "test_vcf_tools",
        "test_bcftools_normalization",
        "test_csi_index_integrity",
        "test_ingestion",
        "test_vcf_scale_benchmark",
        "test_giab_benchmark_runner",
        "test_artifact_validation",
        "test_unsupported_vcf_worker_routing",
        "test_resource_qualification",
    }
    if module_name not in eligible:
        return

    execution = _TestPersistentExecution()

    def inject(function):
        def wrapped(*args, **kwargs):
            kwargs.setdefault("persistent_execution", execution)
            return function(*args, **kwargs)
        return wrapped

    from backend.app.domain import ingestion, vcf_tools

    for name in (
        "normalize_vcf_with_bcftools",
        "split_multiallelic_vcf",
        "validate_vcf_index_concordance",
    ):
        if hasattr(vcf_tools, name):
            monkeypatch.setattr(vcf_tools, name, inject(getattr(vcf_tools, name)))
        if hasattr(module, name):
            monkeypatch.setattr(module, name, inject(getattr(module, name)))

    if module_name in {"test_ingestion", "test_vcf_scale_benchmark", "test_artifact_validation"}:
        original_validate = ingestion.validate_vcf
        monkeypatch.setattr(ingestion, "validate_vcf", inject(original_validate))
        if hasattr(module, "validate_vcf"):
            monkeypatch.setattr(module, "validate_vcf", inject(module.validate_vcf))
        if module_name == "test_artifact_validation":
            monkeypatch.setattr(
                module.validation,
                "validate_vcf",
                inject(module.validation.validate_vcf),
            )

    if module_name == "test_artifact_validation":
        monkeypatch.setattr(
            module.validation,
            "persistent_execution_for_case",
            lambda *_args, **_kwargs: execution,
        )

    if module_name == "test_unsupported_vcf_worker_routing":
        from backend.app.workflows import variant as variant_workflow
        monkeypatch.setattr(
            variant_workflow,
            "_persistent_tool_execution_service",
            lambda *_args, **_kwargs: execution,
        )

    if module_name == "test_resource_qualification":
        from backend.app.adapters.annotation.vep import VEPProvider
        original_factory = VEPProvider.from_execution_contract

        def qualified_test_provider(contract):
            provider = original_factory(contract)
            provider.persistent_execution_service = execution
            return provider

        monkeypatch.setattr(
            VEPProvider,
            "from_execution_contract",
            staticmethod(qualified_test_provider),
        )
