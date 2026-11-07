import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.adapters.annotation.normalizer import normalize_annotation_payload
from backend.app.adapters.annotation.vep import VEPProvider, VEPProviderError
from backend.app.domain.provider_contract import ProviderRawResult
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.schemas import CanonicalVariant
from backend.app.domain.tool_execution import (
    ToolExecutionContractError,
    ToolExecutionError,
    ToolExecutionProvenance,
    ToolExecutionResult,
    current_platform_id,
    sha256_file,
)
from backend.app.config import settings


def _base_toolchain(*, vep_binary="/opt/vep/vep"):
    return {
        "vep_binary": vep_binary,
        "cache_dir": "/resources/vep/115",
        "cache_version": "115",
        "assembly": "GRCh38",
        "fasta": "/resources/GRCh38.fa",
        "fasta_sha256": "e" * 64,
        "cache_manifest": "/resources/vep/115.manifest.json",
        "cache_manifest_sha256": "a" * 64,
        "cache_artifact_sha256": "b" * 64,
        "vep_binary_sha256": "c" * 64,
        "vep_version": "115.2",
        "tool_profile_id": "vep-115.2-linux-64",
        "platform": current_platform_id(),
        "qualification_status": "SOFTWARE_QUALIFIED",
        "runtime_image_digest": "sha256:" + "d" * 64,
        "runtime_path": [str(Path(sys.executable).parent), "/usr/bin", "/bin"],
        "runtime_environment": {"PERL5LIB": "/opt/vep/modules", "PERL_HASH_SEED": "0", "PERL_PERTURB_KEYS": "0"},
        "execution_timeout_seconds": 1800,
        "max_output_bytes": 65536,
        "scratch_root": str(settings.worker_scratch_root),
    }


def _contract(*, access_method="LOCAL", toolchain=None, vep_binary="/opt/vep/vep"):
    return ResourceExecutionContract(
        provider_id="VEP",
        provider_version="115",
        access_method=access_method,
        endpoint=None,
        location="/resources/vep/115",
        dataset="vep-cache",
        execution_scope="ORGANIZATION_MANAGED",
        toolchain=toolchain if toolchain is not None else _base_toolchain(vep_binary=vep_binary),
    )


def _reference_package(toolchain):
    fasta_path = Path(toolchain["fasta"])
    fai_path = Path(toolchain["fai"])
    return {
        "resource_id": "reference-grch38",
        "version": "reference-v1",
        "assembly_name": toolchain["assembly"],
        "package_checksum": "f" * 64,
        "fasta_path": str(fasta_path),
        "fasta_sha256": toolchain["fasta_sha256"],
        "fai_path": str(fai_path),
        "fai_sha256": toolchain["fai_sha256"],
        "gzi_path": None,
        "gzi_sha256": None,
    }


class _FakeToolExecutor:
    """Contract-faithful test executor; it still validates paths and resource bytes."""

    def __init__(self, *, version_output="ensembl-vep 115.2", cache_error=False):
        self.version_output = version_output
        self.cache_error = cache_error
        self.requests = []

    @staticmethod
    def _provenance(profile, request, *, stdout="", stderr=""):
        now = datetime.now(timezone.utc).isoformat()
        return ToolExecutionProvenance(
            execution_id=request.execution_id,
            organization_id=request.organization_id,
            workflow_id=request.workflow_id,
            operation=request.operation,
            tool_id=profile.tool_id,
            tool_version=profile.version,
            profile_id=profile.profile_id,
            executable_sha256=profile.executable_sha256,
            resource_bindings=tuple({
                "resource_id": item.resource_id,
                "version": item.version,
                "sha256": item.sha256,
                "assembly": item.assembly,
            } for item in request.resources),
            input_sha256=tuple({"name": item.name, "sha256": item.sha256} for item in request.inputs),
            output_sha256=tuple({
                "name": item.name,
                "sha256": sha256_file(Path(item.path)),
            } for item in request.outputs),
            argv=(profile.executable, *request.argv),
            exit_code=0,
            started_at=now,
            completed_at=now,
            duration_seconds=0.001,
            stdout_sha256=hashlib.sha256(stdout.encode()).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr.encode()).hexdigest(),
            platform=profile.platform,
            runtime_image_digest=profile.runtime_image_digest,
            environment_sha256=hashlib.sha256(b"fixture-environment").hexdigest(),
        )

    def execute(self, profile, request):
        profile.validate()
        if sha256_file(Path(profile.executable)) != profile.executable_sha256:
            raise ToolExecutionContractError("Tool executable SHA-256 does not match the approved profile.")
        if profile.version_output_contains not in self.version_output:
            raise ToolExecutionContractError("Runtime executable version does not match the approved tool profile.")
        request.validate(profile)
        self.requests.append(request)

        if request.operation == "verify_cache":
            if self.cache_error:
                raise ToolExecutionError("VEP cache could not be loaded offline.", retryable=False)
            stdout = "Cache version 115; species homo_sapiens; assembly GRCh38"
            return ToolExecutionResult(
                provenance=self._provenance(profile, request, stdout=stdout),
                stdout=stdout,
                stderr="",
            )

        if request.operation != "annotate":
            raise AssertionError(f"Unexpected operation: {request.operation}")
        input_path = Path(request.inputs[0].path)
        output_path = Path(request.outputs[0].path)
        records = []
        for line in input_path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\\t")
            records.append({
                "start": int(fields[1]),
                "seq_region_name": fields[0],
                "allele_string": f"{fields[3]}/{fields[4]}",
                "assembly_name": next(
                    request.argv[index + 1]
                    for index, value in enumerate(request.argv[:-1])
                    if value == "--assembly"
                ),
                "most_severe_consequence": "missense_variant",
                "variant_class": "SNV",
                "transcript_consequences": [{
                    "transcript_id": "ENST00000000001.1",
                    "gene_id": "ENSG00000000001",
                    "gene_symbol": "GENE1",
                    "canonical": 1,
                    "mane_select": "NM_000001.1" if "--mane" in request.argv else None,
                    "consequence_terms": ["missense_variant"],
                    "hgvsc": "ENST00000000001.1:c.1A>G",
                    "hgvsp": "ENSP00000000001.1:p.Lys1Arg",
                }],
            })
        output_path.write_text(
            "".join(json.dumps(item, separators=(",", ":")) + "\\n" for item in records),
            encoding="utf-8",
        )
        return ToolExecutionResult(
            provenance=self._provenance(profile, request),
            stdout="",
            stderr="",
        )


def _manifested_toolchain(tmp_path, binary, *, vep_version=None, assembly="GRCh38"):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "fixture.dat"
    cache_file.write_bytes(b"qualified fixture cache bytes")
    cache_artifact_sha256 = "b" * 64
    document = {
        "schema": "siraloom.vep-cache-manifest.v1",
        "cache_version": "115",
        "species": "homo_sapiens",
        "assembly": assembly,
        "source_artifact_sha256": cache_artifact_sha256,
        "files": [{
            "path": "fixture.dat",
            "sha256": hashlib.sha256(cache_file.read_bytes()).hexdigest(),
            "size_bytes": cache_file.stat().st_size,
        }],
    }
    manifest = tmp_path / "vep-cache-manifest.json"
    manifest.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1\\nACGTACGT\\n", encoding="utf-8")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text("1\\t8\\t3\\t8\\t9\\n", encoding="utf-8")
    toolchain = _base_toolchain(vep_binary=str(binary))
    toolchain.update({
        "cache_dir": str(cache_dir),
        "assembly": assembly,
        "cache_manifest": str(manifest),
        "cache_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "cache_artifact_sha256": cache_artifact_sha256,
        "vep_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "fasta": str(fasta),
        "fasta_sha256": hashlib.sha256(fasta.read_bytes()).hexdigest(),
        "fai": str(fai),
        "fai_sha256": hashlib.sha256(fai.read_bytes()).hexdigest(),
    })
    if vep_version:
        toolchain["vep_version"] = vep_version
    toolchain["tool_profile_id"] = f"vep-{toolchain['vep_version']}-{toolchain['platform']}"
    return toolchain, cache_file


def _runtime_context(monkeypatch, tmp_path, toolchain):
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    monkeypatch.setattr(settings, "worker_scratch_root", str(scratch))
    toolchain["scratch_root"] = str(scratch)
    monkeypatch.setenv("SIRALOOM_RUNTIME_IMAGE_DIGEST", toolchain["runtime_image_digest"])
    monkeypatch.setattr(
        VEPProvider,
        "_require_read_only_mount",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    return {
        "genome": toolchain["assembly"],
        "reference_package": _reference_package(toolchain),
        "organization_id": "org-001",
        "workflow_id": "analysis-001",
    }


def test_vep_provider_uses_only_the_governed_local_toolchain():
    provider = VEPProvider.from_execution_contract(_contract())

    assert provider.binary == "/opt/vep/vep"
    assert provider.cache_dir == "/resources/vep/115"
    assert provider.cache_version == "115"
    assert provider.assembly == "GRCh38"
    assert provider.fasta == "/resources/GRCh38.fa"
    assert provider.contract.provider_version == "115"


def test_vep_provider_rejects_nonlocal_execution():
    with pytest.raises(VEPProviderError, match="requires LOCAL/FILE/LOCAL_ONLY"):
        VEPProvider.from_execution_contract(
            _contract(access_method="HTTPS")
        )


def test_vep_provider_requires_explicit_cache_version():
    toolchain = {
        "vep_binary": "/opt/vep/vep",
        "cache_dir": "/resources/vep/115",
        "assembly": "GRCh38",
    }
    with pytest.raises(VEPProviderError, match="must declare cache_version"):
        VEPProvider.from_execution_contract(_contract(toolchain=toolchain))


@pytest.mark.parametrize(
    "argument",
    [
        "--input_file=/tmp/unapproved.vcf", "--help", "--plugin", "--refseq",
        "--symbol", "--transcript_version", "--hgvs", "--hgvsg", "--mane_select",
    ],
)
def test_vep_provider_rejects_extra_args_that_override_governed_paths(argument):
    toolchain = _base_toolchain()
    toolchain.update({
        "cache_manifest": "/resources/vep/115.manifest.json",
        "extra_args": [argument],
    })
    with pytest.raises(VEPProviderError, match="may not override governed"):
        VEPProvider.from_execution_contract(_contract(toolchain=toolchain))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("vep_binary", "vep", "absolute vep_binary"),
        ("cache_dir", "vep-cache", "absolute cache_dir"),
        ("assembly", "", "pin assembly"),
    ],
)
def test_vep_requires_absolute_paths_and_explicit_assembly(field, value, message):
    toolchain = _base_toolchain()
    toolchain.update({
        "cache_manifest": "/resources/vep/115.manifest.json",
    })
    toolchain[field] = value

    with pytest.raises(VEPProviderError, match=message):
        VEPProvider.from_execution_contract(_contract(toolchain=toolchain))


def _normalize_consequences(transcripts):
    provider = VEPProvider.from_execution_contract(_contract())
    variant = CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=100, reference="A", alternate="G"
    )
    record = {
        "input": "1 100 SIRALOOM_0 A G . PASS .",
        "start": 100,
        "seq_region_name": "1",
        "allele_string": "A/G",
        "transcript_consequences": transcripts,
    }
    result = ProviderRawResult("annotate", [record], "fixture-sha256", {})
    return provider.normalize_result(
        result,
        inputs={"variants": [variant], "genome_build": "GRCh38"},
    ).observations[0]


def _manifested_toolchain(tmp_path, binary, *, vep_version=None):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "fixture.dat"
    cache_file.write_bytes(b"qualified fixture cache bytes")
    cache_artifact_sha256 = "b" * 64
    document = {
        "schema": "siraloom.vep-cache-manifest.v1",
        "cache_version": "115",
        "species": "homo_sapiens",
        "assembly": "GRCh38",
        "source_artifact_sha256": cache_artifact_sha256,
        "files": [{
            "path": "fixture.dat",
            "sha256": hashlib.sha256(cache_file.read_bytes()).hexdigest(),
            "size_bytes": cache_file.stat().st_size,
        }],
    }
    manifest = tmp_path / "vep-cache-manifest.json"
    manifest.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    toolchain = {
        "vep_binary": str(binary),
        "cache_dir": str(cache_dir),
        "cache_version": "115",
        "assembly": "GRCh38",
        "cache_manifest": str(manifest),
        "cache_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "cache_artifact_sha256": cache_artifact_sha256,
        "vep_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }
    if vep_version:
        toolchain["vep_version"] = vep_version
    return toolchain, cache_file


def test_vep_prefers_one_mane_select_transcript_over_canonical():
    consequence = _normalize_consequences([
        {"transcript_id": "ENST_CANONICAL", "canonical": 1, "gene_symbol": "GENE1"},
        {
            "transcript_id": "ENST_MANE",
            "mane_select": "NM_000001.1",
            "gene_symbol": "GENE1",
            "consequence_terms": ["missense_variant"],
        },
    ])

    assert consequence["transcript"] == "ENST_MANE"
    assert consequence["transcript_selection"] == {
        "status": "SELECTED_MANE_SELECT",
        "policy": "UNIQUE_MANE_SELECT_THEN_UNIQUE_CANONICAL",
        "selected_transcript_id": "ENST_MANE",
    }
    assert normalize_annotation_payload("VEP", consequence)["transcript_selection"] == consequence[
        "transcript_selection"
    ]


@pytest.mark.parametrize(
    ("transcripts", "expected_status"),
    [
        ([{"transcript_id": "ENST_FIRST", "gene_symbol": "GENE1"}], "NO_PREFERRED_TRANSCRIPT"),
        (
            [
                {"transcript_id": "ENST_CANONICAL_1", "canonical": 1},
                {"transcript_id": "ENST_CANONICAL_2", "canonical": 1},
            ],
            "AMBIGUOUS_CANONICAL",
        ),
        (
            [
                {"transcript_id": "ENST_MANE_1", "mane_select": "NM_1"},
                {"transcript_id": "ENST_MANE_2", "mane_select": "NM_2"},
            ],
            "AMBIGUOUS_MANE_SELECT",
        ),
    ],
)
def test_vep_does_not_select_first_or_ambiguous_transcript(transcripts, expected_status):
    consequence = _normalize_consequences(transcripts)

    assert consequence["transcript"] is None
    assert consequence["gene_symbol"] is None
    assert consequence["effect"] == ""
    assert consequence["consequences"] == transcripts
    assert consequence["transcript_selection"]["status"] == expected_status


def test_vep_rejects_malformed_transcript_consequence_response():
    provider = VEPProvider.from_execution_contract(_contract())
    result = ProviderRawResult(
        "annotate",
        [{"transcript_consequences": {"transcript_id": "ENST1"}}],
        "fixture-sha256",
        {},
    )

    with pytest.raises(VEPProviderError, match="list of objects"):
        provider.validate_response(result)


def _build_runtime_provider(
    monkeypatch,
    tmp_path,
    *,
    assembly="GRCh38",
    vep_version="115.2",
    version_output=None,
    cache_error=False,
):
    binary = tmp_path / "vep"
    binary.write_text("fixture VEP executable identity", encoding="utf-8")
    binary.chmod(0o755)
    toolchain, cache_file = _manifested_toolchain(
        tmp_path,
        binary,
        vep_version=vep_version,
        assembly=assembly,
    )
    context = _runtime_context(monkeypatch, tmp_path, toolchain)
    executor = _FakeToolExecutor(
        version_output=version_output or f"ensembl-vep {vep_version}",
        cache_error=cache_error,
    )
    provider = VEPProvider.from_execution_contract(_contract(toolchain=toolchain), executor=executor)
    return provider, context, executor, toolchain, cache_file, binary


def test_vep_annotation_verifies_pinned_runtime_and_uses_shared_executor(monkeypatch, tmp_path):
    provider, context, executor, _toolchain, _cache_file, _binary = _build_runtime_provider(
        monkeypatch, tmp_path
    )
    variant = CanonicalVariant(
        genome_build="GRCh38",
        chromosome="1",
        position=100,
        reference="A",
        alternate="G",
    )

    output = provider.annotate([variant], context)

    assert len(output) == 1
    assert [item.operation for item in executor.requests] == ["verify_cache", "annotate"]
    assert "--offline" in executor.requests[0].argv
    assert "--show_cache_info" in executor.requests[0].argv
    assert "--offline" in executor.requests[1].argv
    assert "--cache" in executor.requests[1].argv
    provenance = output[0]["_siraloom_annotation_provenance"]
    assert provenance["runtime_check"]["status"] == "VERIFIED"
    assert provenance["runtime_check"]["vep_version"] == "115.2"
    assert provenance["runtime_check"]["reference_package"]["package_checksum"] == "f" * 64
    assert provenance["tool_execution_provenance"]["tool_version"] == "115.2"
    assert provenance["raw_response_sha256"] == provenance["response_sha256"]
    shutil.rmtree(provenance["workspace_path"])


@pytest.mark.parametrize(
    ("assembly", "expected_options"),
    [
        (
            "GRCh38",
            {"--canonical", "--symbol", "--transcript_version", "--mane", "--hgvs", "--hgvsg", "--check_ref"},
        ),
        (
            "GRCh37",
            {"--canonical", "--symbol", "--transcript_version", "--hgvs", "--hgvsg", "--check_ref"},
        ),
    ],
)
def test_vep_execution_requests_and_records_versioned_transcript_annotations(
    monkeypatch, tmp_path, assembly, expected_options
):
    provider, context, executor, _toolchain, _cache_file, _binary = _build_runtime_provider(
        monkeypatch, tmp_path, assembly=assembly
    )
    variant = CanonicalVariant(
        genome_build=assembly,
        chromosome="1",
        position=100,
        reference="A",
        alternate="G",
    )
    request = provider.prepare_request(
        "annotate",
        {
            "variants": [variant],
            "genome_build": assembly,
            "reference_package": context["reference_package"],
            "organization_id": context["organization_id"],
            "workflow_id": context["workflow_id"],
        },
    )

    result = provider.execute(request)
    command = executor.requests[-1].argv
    command_options = set(command)
    assert expected_options <= command_options
    assert "--fasta" in command_options
    assert command[command.index("--assembly") + 1] == assembly
    assert command[command.index("--fasta") + 1] == context["reference_package"]["fasta_path"]
    assert result.metadata["annotation_options"] == [
        option for option in (
            "--offline", "--cache", "--format", "--json", "--check_ref",
            "--hgvs", "--hgvsg", "--canonical", "--symbol",
            "--transcript_version", "--mane",
        ) if option in expected_options or option in {"--offline", "--cache", "--format", "--json"}
    ]
    assert result.payload[0]["allele_string"] == "A/G"
    assert result.metadata["tool_execution_provenance"]["tool_version"] == "115.2"
    normalized = provider.normalize_result(result, inputs=request.payload)
    assert normalized.observations[0]["transcript_consequences"][0]["transcript_id"] == "ENST00000000001.1"
    shutil.rmtree(result.metadata["workspace_path"])


def test_vep_rejects_binary_release_mismatch_before_cache_load(monkeypatch, tmp_path):
    provider, context, executor, _toolchain, _cache_file, _binary = _build_runtime_provider(
        monkeypatch,
        tmp_path,
        version_output="ensembl-vep 114.9",
    )

    with pytest.raises(VEPProviderError, match="Runtime executable version does not match"):
        provider.verify_local_runtime(
            "GRCh38",
            reference_package=context["reference_package"],
            context=context,
        )

    assert executor.requests == []


def test_vep_honors_exact_binary_patch_version_when_configured(monkeypatch, tmp_path):
    provider, context, executor, _toolchain, _cache_file, _binary = _build_runtime_provider(
        monkeypatch,
        tmp_path,
        vep_version="115.1",
        version_output="ensembl-vep 115.1",
    )

    runtime = provider.verify_local_runtime(
        "GRCh38",
        reference_package=context["reference_package"],
        context=context,
    )

    assert runtime["vep_version"] == "115.1"
    assert runtime["tool_execution_provenance"]["tool_version"] == "115.1"
    assert len(executor.requests) == 1


def test_vep_blocks_when_offline_cache_cannot_be_loaded(monkeypatch, tmp_path):
    provider, context, executor, _toolchain, _cache_file, _binary = _build_runtime_provider(
        monkeypatch,
        tmp_path,
        cache_error=True,
    )

    with pytest.raises(VEPProviderError, match="offline cache verification failed"):
        provider.verify_local_runtime(
            "GRCh38",
            reference_package=context["reference_package"],
            context=context,
        )

    assert len(executor.requests) == 1
    assert executor.requests[0].operation == "verify_cache"


def test_vep_blocks_cache_file_modified_after_manifest_creation(monkeypatch, tmp_path):
    provider, context, executor, _toolchain, cache_file, _binary = _build_runtime_provider(
        monkeypatch, tmp_path
    )
    cache_file.write_bytes(b"changed after approval")

    with pytest.raises(VEPProviderError, match="does not match its manifest"):
        provider.verify_local_runtime(
            "GRCh38",
            reference_package=context["reference_package"],
            context=context,
        )

    assert executor.requests == []


def test_vep_blocks_binary_changed_after_contract_pinning(monkeypatch, tmp_path):
    provider, context, executor, _toolchain, _cache_file, binary = _build_runtime_provider(
        monkeypatch, tmp_path
    )
    binary.write_text("different binary bytes", encoding="utf-8")

    with pytest.raises(VEPProviderError, match="Tool executable SHA-256 does not match"):
        provider.verify_local_runtime(
            "GRCh38",
            reference_package=context["reference_package"],
            context=context,
        )

    assert executor.requests == []


def test_vep_blocks_unlisted_cache_file(monkeypatch, tmp_path):
    provider, context, executor, _toolchain, cache_file, _binary = _build_runtime_provider(
        monkeypatch, tmp_path
    )
    (cache_file.parent / "unlisted.dat").write_bytes(b"unqualified cache data")

    with pytest.raises(VEPProviderError, match="contains an unlisted file"):
        provider.verify_local_runtime(
            "GRCh38",
            reference_package=context["reference_package"],
            context=context,
        )

    assert executor.requests == []


def test_vep_rejects_symlinked_cache_root(monkeypatch, tmp_path):
    binary = tmp_path / "vep"
    binary.write_text("fixture VEP executable identity", encoding="utf-8")
    toolchain, cache_file = _manifested_toolchain(tmp_path, binary)
    actual_cache = cache_file.parent
    cache_link = tmp_path / "cache-link"
    cache_link.symlink_to(actual_cache, target_is_directory=True)
    toolchain["cache_dir"] = str(cache_link)

    with pytest.raises(VEPProviderError, match="cache directory cannot be a symlink"):
        VEPProvider.from_execution_contract(_contract(toolchain=toolchain))


def test_vep_rejects_analysis_assembly_different_from_resource_assembly(monkeypatch, tmp_path):
    provider, context, executor, _toolchain, _cache_file, _binary = _build_runtime_provider(
        monkeypatch, tmp_path, assembly="GRCh38"
    )

    with pytest.raises(VEPProviderError, match="does not match analysis assembly"):
        provider.verify_local_runtime(
            "GRCh37",
            reference_package=context["reference_package"],
            context=context,
        )

    assert executor.requests == []


def test_vep_rejects_runtime_image_digest_mismatch(monkeypatch, tmp_path):
    provider, context, executor, toolchain, _cache_file, _binary = _build_runtime_provider(
        monkeypatch, tmp_path
    )
    monkeypatch.setenv("SIRALOOM_RUNTIME_IMAGE_DIGEST", "sha256:" + "0" * 64)

    with pytest.raises(VEPProviderError, match="worker image digest"):
        provider.verify_local_runtime(
            "GRCh38",
            reference_package=context["reference_package"],
            context=context,
        )

    assert executor.requests == []


def test_vep_requires_read_only_reference_resources(tmp_path):
    with pytest.raises(VEPProviderError, match="must be mounted read-only"):
        VEPProvider._require_read_only_mount(tmp_path, label="test reference")
