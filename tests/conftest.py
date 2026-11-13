import hashlib
import os
import shutil
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
        def registration():
            from backend.app.config import settings
            from backend.app.domain.execution_environments import (
                ExecutionCapacity,
                ExecutionEnvironmentProfile,
                ExecutionJobLimits,
            )
            from backend.app.domain.tool_execution import current_platform_id

            executable = settings.bcftools_executable
            if not Path(executable).is_absolute():
                executable = shutil.which(executable) or ""
            if not executable or not Path(executable).is_file():
                executable = shutil.which("bcftools") or ""
            if not executable:
                raise RuntimeError("Scientific unit-test executor requires the pinned BCFtools test binary.")
            executable_sha256 = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
            image_digest = "sha256:" + ("1" * 64)
            profile = ExecutionEnvironmentProfile(
                environment_id="pytest-qualified-oci",
                profile_version="1",
                owner_scope="SIRALOOM",
                organization_id=None,
                executor_kind="CONTAINER",
                platform=current_platform_id(),
                operating_system="linux",
                architecture="x86_64",
                kernel_release="pytest",
                runtime_kind="DOCKER",
                runtime_version="pytest-docker",
                runtime_image_digest=image_digest,
                runtime_image_reference=f"registry.example/siraloom-test@{image_digest}",
                scheduler="DOCKER_COMPOSE",
                capacity=ExecutionCapacity(
                    cpu_cores=4,
                    memory_bytes=8 * 1024**3,
                    scratch_bytes=8 * 1024**3,
                    max_concurrency=2,
                ),
                job_limits=ExecutionJobLimits(
                    cpu_cores=1,
                    memory_bytes=2 * 1024**3,
                    pids_limit=256,
                    container_user="10001:10001",
                ),
                workspace_root="/tmp",
                storage_profile_ids=("pytest-artifacts",),
                supported_tool_profile_ids=(settings.bcftools_profile_id,),
                tool_executable_sha256=((settings.bcftools_profile_id, executable_sha256),),
                network_policy="OFFLINE",
                qualification_status="ENVIRONMENT_QUALIFIED",
            )
            return SimpleNamespace(profile_json=profile.snapshot())

        self.db = SimpleNamespace(get=lambda *_args, **_kwargs: registration())

    def execute(self, profile, request, *, artifact_publisher=None):
        executable = str(profile.executable)
        argv = [executable, *list(request.argv)]
        environment = dict(os.environ)
        environment.update(dict(getattr(request, "environment", {}) or {}))
        if request.operation == "annotate":
            process = subprocess.Popen(
                argv,
                cwd=str(request.workspace),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            stdout, stderr = process.communicate(timeout=max(1, int(request.timeout_seconds)))
            completed = SimpleNamespace(
                returncode=process.returncode,
                stdout=stdout or "",
                stderr=stderr or "",
            )
        else:
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
        "test_vep_provider",
    }
    if module_name not in eligible:
        return

    execution = _TestPersistentExecution()
    from backend.app.config import settings
    executable = shutil.which(settings.bcftools_executable) or shutil.which("bcftools")
    if executable:
        monkeypatch.setattr(settings, "bcftools_executable", executable)

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

    if module_name in {"test_resource_qualification", "test_vep_provider"}:
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
