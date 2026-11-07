import json
from gzip import open as gzip_open
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from backend.app.domain.resource_qualification import qualify_resource
from backend.app.adapters.annotation.vep import VEPProvider, VEPProviderError
from backend.app.config import settings
from backend.app.domain.tool_execution import current_platform_id
import sys
from backend.app.infrastructure.db.models import Resource, ResourceStaging


def _resource(tmp_path: Path, *, checksum: str | None, license_status: str = "NOT_REQUIRED", checksum_status: str = "PUBLISHED_AND_VERIFIED"):
    artifact = tmp_path / "ClinVarVCVRelease_2026-09.xml.gz"
    with gzip_open(artifact, "wb") as handle:
        handle.write(b"<Release><ClinVarVariationRelease/></Release>")
    return Resource(
        name="ClinVar", provider="NCBI ClinVar", resource_type="EVIDENCE",
        version="2026-09", genome_build=None, access_method="HTTPS",
        license_text=None, checksum=checksum, location=str(artifact),
        population_definition=None, metadata_json={"source_contract": {
            "publisher": "NCBI ClinVar",
            "canonical_source_url": "https://www.ncbi.nlm.nih.gov/clinvar/",
            "artifact_url": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/xml/ClinVarVCVRelease_2026-09.xml.gz",
            "release_identity": "2026-09", "access_mode": "PUBLIC",
            "license_status": license_status, "checksum_status": checksum_status,
            "authority_evidence_url": "https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/",
        }, "execution": {
            "provider_id": "NCBI ClinVar",
            "provider_version": "release-xml-v1",
            "access_method": "HTTPS",
            "endpoint": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/xml/ClinVarVCVRelease_2026-09.xml.gz",
            "dataset": "ClinVar VCV XML",
        }},
    )


def _staging(resource: Resource, *, status: str = "STAGED") -> ResourceStaging:
    return ResourceStaging(
        id=uuid4(),
        resource_id=resource.id,
        resource_version=resource.version,
        staging_key=f"test:{resource.version}",
        source_uri="test-source",
        destination_uri=str(resource.location),
        storage_backend="LOCAL_FILESYSTEM",
        status=status,
        expected_sha256=resource.checksum,
        expected_size_bytes=None,
        metadata_json={},
    )


def test_qualification_computes_integrity_and_structure(tmp_path):
    result = qualify_resource((resource := _resource(tmp_path, checksum=None, checksum_status="NOT_PUBLISHED")), staging=_staging(resource))
    assert result.passed is False
    assert "AUTHORITATIVE_CHECKSUM_UNVERIFIED" in result.blockers
    assert result.checks["artifact_validation"] == "GZIP_XML_WELL_FORMED"
    assert result.checks["xml_element_count"] == 2


def test_published_checksum_mismatch_is_blocking(tmp_path):
    result = qualify_resource((resource := _resource(tmp_path, checksum="0" * 64)), staging=_staging(resource))
    assert result.passed is False
    assert "CHECKSUM_MISMATCH" in result.blockers


def test_license_review_is_blocking(tmp_path):
    result = qualify_resource((resource := _resource(tmp_path, checksum=None, license_status="REVIEW_REQUIRED", checksum_status="NOT_PUBLISHED")), staging=_staging(resource))
    assert result.passed is False
    assert "LICENSE_REVIEW_REQUIRED" in result.blockers


def test_missing_staging_is_actionable(tmp_path):
    resource = _resource(tmp_path, checksum="1" * 64)
    resource.location = "/var/lib/siraloom/staged/missing.xml.gz"
    result = qualify_resource(resource)
    assert result.passed is False
    assert "STAGING_RECORD_REQUIRED" in result.blockers
    assert result.checks["qualification_outcome"] == "BLOCKED"

def test_qualification_requires_execution_contract(tmp_path):
    resource = _resource(tmp_path, checksum=None, checksum_status="NOT_PUBLISHED")
    resource.metadata_json.pop("execution")
    result = qualify_resource(resource, staging=_staging(resource))
    assert result.passed is False
    assert "EXECUTION_CONTRACT_INVALID" in result.blockers


def test_qualification_records_execution_contract(tmp_path):
    result = qualify_resource(_resource(tmp_path, checksum=None, checksum_status="NOT_PUBLISHED"))
    assert result.checks["execution_contract"]["provider_id"] == "NCBI ClinVar"


def test_clinvar_qualification_validates_beyond_first_megabyte(tmp_path):
    artifact = tmp_path / "ClinVarVCVRelease_2026-09.xml.gz"
    payload = b"<Release><ClinVarVariationRelease>" + (b"x" * (1024 * 1024 + 128)) + b"</broken>"
    with gzip_open(artifact, "wb") as handle:
        handle.write(payload)

    resource = _resource(tmp_path, checksum=None, checksum_status="NOT_PUBLISHED")
    artifact = Path(resource.location)
    with gzip_open(artifact, "wb") as handle:
        handle.write(payload)

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is False
    assert result.checks["artifact_validation"].startswith("INVALID:")
    assert "ARTIFACT_STRUCTURE_NOT_VALIDATED" in result.blockers


def _reference_resource(tmp_path: Path, *, toolchain):
    fasta = tmp_path / "GRCh38.fa"
    fasta.write_text(">1\nCAAAAAC\n", encoding="utf-8")
    return Resource(
        name="GRCh38 reference",
        provider="ReferenceProvider",
        resource_type="REFERENCE_PACKAGE",
        version="GRCh38-v1",
        genome_build="GRCh38",
        access_method="LOCAL",
        license_text=None,
        checksum=None,
        location=str(fasta),
        population_definition=None,
        organization_id=None,
        metadata_json={
            "source_contract": {
                "publisher": "Reference Authority",
                "canonical_source_url": "https://example.org/reference",
                "artifact_url": "https://example.org/reference/GRCh38.fa",
                "release_identity": "GRCh38-v1",
                "access_mode": "PUBLIC",
                "license_status": "NOT_REQUIRED",
                "checksum_status": "NOT_PUBLISHED",
                "authority_evidence_url": "https://example.org/reference/docs",
            },
            "execution": {
                "provider_id": "ReferenceProvider",
                "provider_version": "reference-v1",
                "access_method": "LOCAL",
                "location": str(fasta),
                "toolchain": toolchain,
            },
        },
    )


def test_reference_qualification_requires_governed_bcftools_version(tmp_path):
    result = qualify_resource((resource := _reference_resource(tmp_path, toolchain=None)), staging=_staging(resource))
    assert result.passed is False
    assert "BCFTOOLS_TOOLCHAIN_NOT_DECLARED" in result.blockers


def test_reference_qualification_records_governed_bcftools_version(tmp_path):
    resource = _reference_resource(tmp_path, toolchain={"bcftools": {"version": "1.19"}})
    result = qualify_resource(resource, staging=_staging(resource))
    assert result.checks["bcftools_tool"] == "bcftools"
    assert result.checks["bcftools_version"] == "1.19"
    assert result.checks["bcftools_execution"] == "GOVERNED"


def test_qualification_blocks_unverified_staging(tmp_path):
    resource = _resource(tmp_path, checksum="1" * 64)
    result = qualify_resource(resource, staging=_staging(resource, status="INTEGRITY_FAILED"))
    assert result.passed is False
    assert "STAGING_NOT_VERIFIED" in result.blockers


def test_qualification_blocks_staging_identity_mismatch(tmp_path):
    resource = _resource(tmp_path, checksum="1" * 64)
    staging = _staging(resource)
    staging.resource_version = "different-version"
    result = qualify_resource(resource, staging=staging)
    assert result.passed is False
    assert "STAGING_RESOURCE_IDENTITY_MISMATCH" in result.blockers


def _vep_resource(tmp_path: Path):
    binary = tmp_path / "vep"
    binary.write_text("fixture binary", encoding="utf-8")
    cache_archive = tmp_path / "vep-cache-115.tar.gz"
    cache_archive.write_bytes(b"fixture cache archive")
    cache_dir = tmp_path / "installed-vep-cache"
    cache_dir.mkdir()
    cache_file = cache_dir / "fixture.dat"
    cache_file.write_bytes(b"qualified fixture cache bytes")
    cache_sha256 = sha256(cache_archive.read_bytes()).hexdigest()
    manifest = tmp_path / "vep-cache-manifest.json"
    manifest.write_text(json.dumps({
        "schema": "siraloom.vep-cache-manifest.v1",
        "cache_version": "115",
        "species": "homo_sapiens",
        "assembly": "GRCh38",
        "source_artifact_sha256": cache_sha256,
        "files": [{
            "path": "fixture.dat",
            "sha256": sha256(cache_file.read_bytes()).hexdigest(),
            "size_bytes": cache_file.stat().st_size,
        }],
    }, sort_keys=True), encoding="utf-8")
    fasta = tmp_path / "GRCh38.fa"
    fasta.write_text(">1\\nACGTACGT\\n", encoding="utf-8")
    fai = tmp_path / "GRCh38.fa.fai"
    fai.write_text("1\\t8\\t3\\t8\\t9\\n", encoding="utf-8")
    reference_package = {
        "resource_id": "reference-grch38",
        "version": "reference-v1",
        "assembly_name": "GRCh38",
        "package_checksum": "f" * 64,
        "fasta_path": str(fasta),
        "fasta_sha256": sha256(fasta.read_bytes()).hexdigest(),
        "fai_path": str(fai),
        "fai_sha256": sha256(fai.read_bytes()).hexdigest(),
        "gzi_path": None,
        "gzi_sha256": None,
    }
    resource = Resource(
        name="VEP 115 GRCh38",
        provider="VEP",
        resource_type="ANNOTATION",
        version="115",
        genome_build="GRCh38",
        access_method="LOCAL",
        license_text=None,
        checksum=cache_sha256,
        location=str(cache_archive),
        population_definition=None,
        organization_id=None,
        metadata_json={
            "source_contract": {
                "publisher": "Ensembl",
                "canonical_source_url": "https://www.ensembl.org/info/docs/tools/vep/",
                "artifact_url": "https://ftp.ensembl.org/pub/release-115/variation/vep-cache/",
                "release_identity": "115",
                "access_mode": "LOCAL_ONLY",
                "license_status": "NOT_REQUIRED",
                "checksum_status": "PUBLISHED_AND_VERIFIED",
                "authority_evidence_url": "https://www.ensembl.org/info/docs/tools/vep/script/vep_cache.html",
            },
            "execution": {
                "provider_id": "VEP",
                "provider_version": "115",
                "access_method": "LOCAL",
                "location": str(cache_archive),
                "dataset": "Ensembl VEP cache",
                "toolchain": {
                    "vep_binary": str(binary),
                    "cache_dir": str(cache_dir),
                    "cache_version": "115",
                    "assembly": "GRCh38",
                    "fasta": str(fasta),
                    "fasta_sha256": reference_package["fasta_sha256"],
                    "cache_manifest": str(manifest),
                    "cache_manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
                    "cache_artifact_sha256": cache_sha256,
                    "vep_binary_sha256": sha256(binary.read_bytes()).hexdigest(),
                    "vep_version": "115.2",
                    "tool_profile_id": "vep-115.2-" + current_platform_id(),
                    "platform": current_platform_id(),
                    "qualification_status": "SOFTWARE_QUALIFIED",
                    "runtime_image_digest": "sha256:" + "d" * 64,
                    "runtime_path": [str(Path(sys.executable).parent), "/usr/bin", "/bin"],
                    "runtime_environment": {
                        "PERL5LIB": "/opt/vep/modules",
                        "PERL_HASH_SEED": "0",
                        "PERL_PERTURB_KEYS": "0",
                    },
                    "execution_timeout_seconds": 1800,
                    "max_output_bytes": 65536,
                    "scratch_root": str(settings.worker_scratch_root),
                    "reference_package": reference_package,
                },
            },
        },
    )
    return resource, binary


def test_vep_qualification_executes_governed_preflight_with_reference_context(monkeypatch, tmp_path):
    resource, _binary = _vep_resource(tmp_path)
    captured = {}

    def fake_verify(self, build, *, reference_package, context):
        captured.update({
            "build": build,
            "reference_package": reference_package,
            "context": context,
        })
        return {
            "status": "VERIFIED",
            "assembly": build,
            "cache_artifact_sha256": self.cache_artifact_sha256,
        }

    monkeypatch.setattr(VEPProvider, "verify_local_runtime", fake_verify)
    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is True
    assert result.checks["vep_runtime"]["status"] == "VERIFIED"
    assert result.checks["vep_runtime"]["assembly"] == "GRCh38"
    assert result.checks["vep_runtime"]["cache_artifact_sha256"] == resource.checksum
    assert captured["reference_package"]["assembly_name"] == "GRCh38"
    assert captured["context"]["organization_id"] == "system-resource-qualification"
    assert captured["context"]["workflow_id"].startswith("resource-qualification:")


def test_vep_qualification_blocks_runtime_preflight_failure(monkeypatch, tmp_path):
    resource, _binary = _vep_resource(tmp_path)

    def reject_runtime(self, build, *, reference_package, context):
        raise VEPProviderError("Runtime executable version does not match the approved profile.")

    monkeypatch.setattr(VEPProvider, "verify_local_runtime", reject_runtime)
    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is False
    assert "VEP_RUNTIME_PREFLIGHT_FAILED" in result.blockers
    assert result.checks["vep_runtime"]["status"] == "BLOCKED"


def test_vep_qualification_blocks_manifest_artifact_digest_mismatch(monkeypatch, tmp_path):
    resource, _binary = _vep_resource(tmp_path)
    execution = resource.metadata_json["execution"]
    execution["toolchain"]["cache_artifact_sha256"] = "0" * 64
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(settings, "worker_scratch_root", str(scratch))
    monkeypatch.setenv(
        "SIRALOOM_RUNTIME_IMAGE_DIGEST",
        execution["toolchain"]["runtime_image_digest"],
    )
    monkeypatch.setattr(
        VEPProvider,
        "_require_read_only_mount",
        staticmethod(lambda *_args, **_kwargs: None),
    )

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is False
    assert "VEP_CACHE_ARTIFACT_DIGEST_MISMATCH" in result.blockers
    assert "VEP_RUNTIME_PREFLIGHT_FAILED" in result.blockers
    assert "manifest does not identify the governed cache artifact digest" in result.checks["vep_runtime"]["error"]


def test_vep_qualification_requires_staged_resource_artifact(tmp_path):
    resource, _binary = _vep_resource(tmp_path)
    result = qualify_resource(resource)

    assert result.passed is False
    assert "VEP_RESOURCE_ARTIFACT_NOT_STAGED" in result.blockers
    assert result.checks["vep_runtime"]["status"] == "NOT_RUN"
