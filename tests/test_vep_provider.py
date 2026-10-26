import hashlib
import json
from types import SimpleNamespace

import pytest

from backend.app.adapters.annotation.normalizer import normalize_annotation_payload
from backend.app.adapters.annotation.vep import VEPProvider, VEPProviderError
from backend.app.domain.provider_contract import ProviderRawResult
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.schemas import CanonicalVariant


def _contract(*, access_method="LOCAL", toolchain=None, vep_binary="/opt/vep/vep"):
    return ResourceExecutionContract(
        provider_id="VEP",
        provider_version="115",
        access_method=access_method,
        endpoint=None,
        location="/resources/vep/115",
        dataset="vep-cache",
        execution_scope="ORGANIZATION_MANAGED",
        toolchain=toolchain if toolchain is not None else {
            "vep_binary": vep_binary,
            "cache_dir": "/resources/vep/115",
            "cache_version": "115",
            "assembly": "GRCh38",
            "fasta": "/resources/GRCh38.fa",
            "cache_manifest": "/resources/vep/115.manifest.json",
            "cache_manifest_sha256": "a" * 64,
            "cache_artifact_sha256": "b" * 64,
            "vep_binary_sha256": "c" * 64,
        },
    )


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
    ["--input_file=/tmp/unapproved.vcf", "--help", "--plugin", "--refseq"],
)
def test_vep_provider_rejects_extra_args_that_override_governed_paths(argument):
    toolchain = {
        "vep_binary": "/opt/vep/vep",
        "cache_dir": "/resources/vep/115",
        "cache_version": "115",
        "assembly": "GRCh38",
        "cache_manifest": "/resources/vep/115.manifest.json",
        "cache_manifest_sha256": "a" * 64,
        "cache_artifact_sha256": "b" * 64,
        "vep_binary_sha256": "c" * 64,
        "extra_args": [argument],
    }
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
    toolchain = {
        "vep_binary": "/opt/vep/vep",
        "cache_dir": "/resources/vep/115",
        "cache_version": "115",
        "assembly": "GRCh38",
        "cache_manifest": "/resources/vep/115.manifest.json",
        "cache_manifest_sha256": "a" * 64,
        "cache_artifact_sha256": "b" * 64,
        "vep_binary_sha256": "c" * 64,
    }
    toolchain[field] = value

    with pytest.raises(VEPProviderError, match=message):
        VEPProvider.from_execution_contract(_contract(toolchain=toolchain))


def _normalize_consequences(transcripts):
    provider = VEPProvider.from_execution_contract(_contract())
    variant = CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=100, reference="A", alternate="G"
    )
    record = {
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


def test_vep_annotation_verifies_pinned_binary_and_offline_cache(monkeypatch, tmp_path):
    binary = tmp_path / "vep"
    binary.write_text("fixture VEP executable identity", encoding="utf-8")
    toolchain, _cache_file = _manifested_toolchain(tmp_path, binary)
    provider = VEPProvider.from_execution_contract(_contract(toolchain=toolchain))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="ensembl-vep 115.2", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="Cache version 115; species homo_sapiens; assembly GRCh38",
            stderr="",
        )

    monkeypatch.setattr("backend.app.adapters.annotation.vep.subprocess.run", fake_run)
    monkeypatch.setattr(
        provider,
        "execute",
        lambda request: ProviderRawResult(
            "annotate",
            [{
                "start": 100,
                "seq_region_name": "1",
                "allele_string": "A/G",
                "transcript_consequences": [{"transcript_id": "ENST1", "canonical": 1}],
            }],
            "fixture-response-digest",
            {},
        ),
    )
    variant = CanonicalVariant(
        genome_build="GRCh38", chromosome="1", position=100, reference="A", alternate="G"
    )

    output = provider.annotate([variant], {"genome": "hg38"})

    assert len(calls) == 2
    assert "--offline" in calls[1]
    assert "--cache" in calls[1]
    assert calls[1][calls[1].index("--assembly") + 1] == "GRCh38"
    assert output[0]["_siraloom_annotation_provenance"]["runtime_check"]["status"] == "VERIFIED"
    assert output[0]["_siraloom_annotation_provenance"]["runtime_check"]["vep_version"] == "115.2"
    assert output[0]["_siraloom_annotation_provenance"]["runtime_check"]["vep_binary_sha256"]
    assert output[0]["_siraloom_annotation_provenance"]["runtime_check"]["cache_tree_sha256"]
    assert output[0]["_siraloom_annotation_provenance"]["runtime_check"]["cache_manifest_sha256"]


def test_vep_rejects_binary_release_mismatch_before_loading_cache(monkeypatch, tmp_path):
    binary = tmp_path / "vep"
    binary.write_text("fixture VEP executable identity", encoding="utf-8")
    toolchain, _cache_file = _manifested_toolchain(tmp_path, binary)
    provider = VEPProvider.from_execution_contract(_contract(toolchain=toolchain))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="ensembl-vep 114.9", stderr="")

    monkeypatch.setattr("backend.app.adapters.annotation.vep.subprocess.run", fake_run)

    with pytest.raises(VEPProviderError, match="does not match governed release"):
        provider.verify_local_runtime("GRCh38")

    assert len(calls) == 1


def test_vep_honors_full_binary_patch_version_when_configured(monkeypatch, tmp_path):
    binary = tmp_path / "vep"
    binary.write_text("fixture VEP executable identity", encoding="utf-8")
    toolchain, _cache_file = _manifested_toolchain(tmp_path, binary, vep_version="115.1")
    provider = VEPProvider.from_execution_contract(_contract(toolchain=toolchain))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="ensembl-vep 115.2", stderr="")

    monkeypatch.setattr("backend.app.adapters.annotation.vep.subprocess.run", fake_run)

    with pytest.raises(VEPProviderError, match="does not match governed release"):
        provider.verify_local_runtime("GRCh38")

    assert len(calls) == 1


def test_vep_blocks_when_offline_cache_cannot_be_loaded(monkeypatch, tmp_path):
    binary = tmp_path / "vep"
    binary.write_text("fixture VEP executable identity", encoding="utf-8")
    toolchain, _cache_file = _manifested_toolchain(tmp_path, binary)
    provider = VEPProvider.from_execution_contract(_contract(toolchain=toolchain))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="ensembl-vep 115.2", stderr="")
        return SimpleNamespace(returncode=1, stdout="cache release missing", stderr="")

    monkeypatch.setattr("backend.app.adapters.annotation.vep.subprocess.run", fake_run)

    with pytest.raises(VEPProviderError, match="could not load the governed cache offline"):
        provider.verify_local_runtime("GRCh38")

    assert len(calls) == 2


def test_vep_blocks_cache_file_modified_after_manifest_creation(monkeypatch, tmp_path):
    binary = tmp_path / "vep"
    binary.write_text("fixture VEP executable identity", encoding="utf-8")
    toolchain, cache_file = _manifested_toolchain(tmp_path, binary)
    cache_file.write_bytes(b"changed after approval")
    provider = VEPProvider.from_execution_contract(_contract(toolchain=toolchain))
    monkeypatch.setattr(
        "backend.app.adapters.annotation.vep.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("VEP must not execute when cache integrity fails"),
    )

    with pytest.raises(VEPProviderError, match="does not match its manifest"):
        provider.verify_local_runtime("GRCh38")


def test_vep_blocks_binary_changed_after_contract_pinning(monkeypatch, tmp_path):
    binary = tmp_path / "vep"
    binary.write_text("pinned binary bytes", encoding="utf-8")
    toolchain, _cache_file = _manifested_toolchain(tmp_path, binary)
    provider = VEPProvider.from_execution_contract(_contract(toolchain=toolchain))
    binary.write_text("different binary bytes", encoding="utf-8")
    monkeypatch.setattr(
        "backend.app.adapters.annotation.vep.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("VEP must not run when binary digest differs"),
    )

    with pytest.raises(VEPProviderError, match="binary SHA-256 does not match"):
        provider.verify_local_runtime("GRCh38")


def test_vep_blocks_unlisted_cache_file(monkeypatch, tmp_path):
    binary = tmp_path / "vep"
    binary.write_text("fixture VEP executable identity", encoding="utf-8")
    toolchain, cache_file = _manifested_toolchain(tmp_path, binary)
    (cache_file.parent / "unlisted.dat").write_bytes(b"unqualified cache data")
    provider = VEPProvider.from_execution_contract(_contract(toolchain=toolchain))
    monkeypatch.setattr(
        "backend.app.adapters.annotation.vep.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("VEP must not execute when cache manifest is incomplete"),
    )

    with pytest.raises(VEPProviderError, match="contains an unlisted file"):
        provider.verify_local_runtime("GRCh38")


def test_vep_rejects_symlinked_cache_root(monkeypatch, tmp_path):
    binary = tmp_path / "vep"
    binary.write_text("fixture VEP executable identity", encoding="utf-8")
    toolchain, cache_file = _manifested_toolchain(tmp_path, binary)
    actual_cache = cache_file.parent
    cache_link = tmp_path / "cache-link"
    cache_link.symlink_to(actual_cache, target_is_directory=True)
    toolchain["cache_dir"] = str(cache_link)
    provider = VEPProvider.from_execution_contract(_contract(toolchain=toolchain))
    monkeypatch.setattr(
        "backend.app.adapters.annotation.vep.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("VEP must not run with a symlinked cache root"),
    )

    with pytest.raises(VEPProviderError, match="cache directory cannot be a symlink"):
        provider.verify_local_runtime("GRCh38")


def test_vep_rejects_analysis_assembly_different_from_resource_assembly(monkeypatch):
    provider = VEPProvider.from_execution_contract(_contract())
    calls = []
    monkeypatch.setattr(
        "backend.app.adapters.annotation.vep.subprocess.run",
        lambda *args, **kwargs: calls.append(args),
    )

    with pytest.raises(VEPProviderError, match="does not match analysis assembly"):
        provider.verify_local_runtime("GRCh37")

    assert calls == []
