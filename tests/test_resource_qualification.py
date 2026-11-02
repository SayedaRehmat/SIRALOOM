import json
from gzip import open as gzip_open
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from backend.app.domain.resource_qualification import qualify_resource
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
                    "cache_manifest": str(manifest),
                    "cache_manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
                    "cache_artifact_sha256": cache_sha256,
                    "vep_binary_sha256": sha256(binary.read_bytes()).hexdigest(),
                },
            },
        },
    )
    return resource, binary


def test_vep_qualification_executes_version_and_offline_cache_preflight(monkeypatch, tmp_path):
    resource, _binary = _vep_resource(tmp_path)
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

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is True
    assert result.checks["vep_runtime"]["status"] == "VERIFIED"
    assert result.checks["vep_runtime"]["assembly"] == "GRCh38"
    assert result.checks["vep_runtime"]["cache_artifact_sha256"] == resource.checksum
    assert len(calls) == 2
    assert "--offline" in calls[1]
    assert "--show_cache_info" in calls[1]


def test_vep_qualification_blocks_binary_release_mismatch(monkeypatch, tmp_path):
    resource, _binary = _vep_resource(tmp_path)
    monkeypatch.setattr(
        "backend.app.adapters.annotation.vep.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="ensembl-vep 114.9", stderr=""
        ),
    )

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is False
    assert "VEP_RUNTIME_PREFLIGHT_FAILED" in result.blockers
    assert result.checks["vep_runtime"]["status"] == "BLOCKED"


def test_vep_qualification_blocks_manifest_artifact_digest_mismatch(monkeypatch, tmp_path):
    resource, _binary = _vep_resource(tmp_path)
    execution = resource.metadata_json["execution"]
    execution["toolchain"]["cache_artifact_sha256"] = "0" * 64
    monkeypatch.setattr(
        "backend.app.adapters.annotation.vep.subprocess.run",
        lambda command, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="ensembl-vep 115.2" if command[-1] == "--version" else "cache info",
            stderr="",
        ),
    )

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is False
    assert "VEP_CACHE_ARTIFACT_DIGEST_MISMATCH" in result.blockers
    assert "VEP_RUNTIME_PREFLIGHT_FAILED" in result.blockers


def test_vep_qualification_requires_staged_resource_artifact(tmp_path):
    resource, _binary = _vep_resource(tmp_path)
    result = qualify_resource(resource)

    assert result.passed is False
    assert "VEP_RESOURCE_ARTIFACT_NOT_STAGED" in result.blockers
    assert result.checks["vep_runtime"]["status"] == "NOT_RUN"


def _normalization_resource(tmp_path: Path, *, provider: str = "bcftools", version: str = "1.25"):
    artifact = tmp_path / f"{provider}-{version}.tar.gz"
    artifact.write_bytes(b"verified staged normalization release fixture")
    executable = tmp_path / "bin" / provider
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    digest = sha256(artifact.read_bytes()).hexdigest()
    return Resource(
        id=uuid4(),
        name=f"{provider} {version}",
        provider=provider,
        resource_type="NORMALIZATION",
        version=version,
        genome_build=None,
        access_method="HTTPS",
        license_text=None,
        checksum=digest,
        location=str(artifact),
        population_definition=None,
        organization_id=None,
        metadata_json={
            "source_contract": {
                "publisher": "Samtools" if provider == "bcftools" else "Broad Institute",
                "canonical_source_url": "https://github.com/samtools/bcftools" if provider == "bcftools" else "https://github.com/broadinstitute/gatk",
                "artifact_url": f"https://example.org/{provider}/{version}.tar.gz",
                "release_identity": version,
                "access_mode": "PUBLIC",
                "license_status": "NOT_REQUIRED",
                "checksum_status": "PUBLISHED_AND_VERIFIED",
                "authority_evidence_url": "https://samtools.github.io/bcftools/" if provider == "bcftools" else "https://gatk.broadinstitute.org/",
            },
            "execution": {
                "provider_id": provider,
                "provider_version": version,
                "access_method": "HTTPS",
                "endpoint": f"https://example.org/{provider}/{version}.tar.gz",
                "toolchain": {
                    "bcftools": {"executable": str(executable)}
                } if provider == "bcftools" else {
                    "gatk": {"executable": str(executable)}
                },
            },
        },
    )


def test_bcftools_qualification_checks_exact_version_and_normalization_contract(monkeypatch, tmp_path):
    resource = _normalization_resource(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="bcftools 1.25\nUsing htslib 1.25", stderr="")
        output_path = Path(command[command.index("-o") + 1])
        input_path = Path(command[-1])
        if input_path.name == "source.vcf":
            output_path.write_text(
                "##fileformat=VCFv4.2\n"
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                "chr1\t1\t.\tCA\tC\t.\tPASS\t.\n"
                "chr1\t7\t.\tC\tT\t.\tPASS\t.\n"
                "chr1\t7\t.\tC\tG\t.\tPASS\t.\n",
                encoding="ascii",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="REF mismatch")

    monkeypatch.setattr("backend.app.domain.resource_qualification.subprocess.run", fake_run)

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is True
    assert result.checks["normalization_runtime"]["status"] == "QUALIFIED"
    assert result.checks["normalization_runtime"]["observed_version"] == "1.25"
    assert result.checks["normalization_runtime"]["left_alignment"] == "PASS"
    assert result.checks["normalization_runtime"]["multiallelic_decomposition"] == "PASS"
    assert result.checks["normalization_runtime"]["ref_mismatch_rejection"] == "PASS"
    assert len(calls) == 3
    assert calls[1][1:8] == ["norm", "-f", calls[1][3], "-c", "e", "-m", "-any"]


def test_bcftools_qualification_blocks_exact_version_mismatch(monkeypatch, tmp_path):
    resource = _normalization_resource(tmp_path)
    monkeypatch.setattr(
        "backend.app.domain.resource_qualification.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="bcftools 1.26\nUsing htslib 1.26", stderr=""
        ),
    )

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is False
    assert "BCFTOOLS_VERSION_MISMATCH" in result.blockers
    assert result.checks["normalization_runtime"]["status"] == "BLOCKED"


def test_gatk_is_not_qualified_through_the_bcftools_adapter(tmp_path):
    resource = _normalization_resource(tmp_path, provider="GATK", version="4.6.0.0")

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is False
    assert "NORMALIZATION_PROVIDER_ADAPTER_NOT_IMPLEMENTED" in result.blockers
    assert result.checks["normalization_runtime"]["status"] == "BLOCKED"

def _vcf_specification_resource(tmp_path: Path, *, include_conformance: bool):
    document = tmp_path / "VCFv4.6.pdf"
    document.write_bytes(b"%PDF-1.7\nSynthetic official-specification PDF fixture\n%%EOF\n")
    report = tmp_path / "vcf-conformance-report.json"
    report.write_text('{"suite":"siraloom-vcf-v4.6","passed":12,"failed":0}', encoding="utf-8")
    document_sha256 = sha256(document.read_bytes()).hexdigest()
    report_sha256 = sha256(report.read_bytes()).hexdigest()
    metadata = {
        "source_contract": {
            "publisher": "Samtools HTS Specifications maintainers",
            "canonical_source_url": "https://github.com/samtools/hts-specs",
            "artifact_url": "https://samtools.github.io/hts-specs/VCFv4.6.pdf",
            "release_identity": "VCFv4.6",
            "access_mode": "PUBLIC",
            "license_status": "NOT_REQUIRED",
            "checksum_status": "PUBLISHED_AND_VERIFIED",
            "authority_evidence_url": "https://samtools.github.io/hts-specs/",
        },
        "execution": {
            "provider_id": "HTS-Specifications",
            "provider_version": "VCFv4.6",
            "access_method": "HTTPS",
            "endpoint": "https://samtools.github.io/hts-specs/VCFv4.6.pdf",
        },
        "specification_version": "VCFv4.6",
        "official_document_url": "https://samtools.github.io/hts-specs/VCFv4.6.pdf",
    }
    if include_conformance:
        metadata["specification_conformance"] = {
            "profile_id": "siraloom-vcf-v4.6-profile-1",
            "suite_version": "siraloom-vcf-conformance-1",
            "execution_status": "PASSED",
            "normative_clause_ids": ["VCFv4.6-4.2", "VCFv4.6-5.1"],
            "unsupported_constructs": [],
            "unsupported_policy": "FAIL_CLOSED",
            "test_case_count": 12,
            "failed_test_count": 0,
            "report_path": str(report.resolve()),
            "report_sha256": report_sha256,
        }
    resource = Resource(
        id=uuid4(),
        name="VCF specification VCFv4.6",
        provider="HTS-Specifications",
        resource_type="VCF_SPECIFICATION",
        version="VCFv4.6",
        genome_build=None,
        access_method="HTTPS",
        license_text=None,
        checksum=document_sha256,
        location=str(document.resolve()),
        population_definition=None,
        organization_id=None,
        metadata_json=metadata,
    )
    return resource, report


def test_new_vcf_specification_cannot_qualify_without_parser_conformance_evidence(tmp_path):
    resource, _report = _vcf_specification_resource(tmp_path, include_conformance=False)

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is False
    assert "VCF_SPECIFICATION_CONFORMANCE_NOT_QUALIFIED" in result.blockers
    assert result.checks["vcf_specification"]["status"] == "BLOCKED"


def test_new_vcf_specification_qualification_verifies_pdf_and_conformance_report_hash(tmp_path):
    resource, report = _vcf_specification_resource(tmp_path, include_conformance=True)

    result = qualify_resource(resource, staging=_staging(resource))

    assert result.passed is True
    assert result.checks["vcf_specification"]["status"] == "QUALIFIED"
    assert result.checks["vcf_specification"]["document_pdf_integrity"] == "PASS"
    assert result.checks["vcf_specification"]["conformance_report_sha256"] == sha256(report.read_bytes()).hexdigest()

    report.write_text("tampered", encoding="utf-8")
    rerun = qualify_resource(resource, staging=_staging(resource))
    assert rerun.passed is False
    assert "VCF_SPECIFICATION_CONFORMANCE_NOT_QUALIFIED" in rerun.blockers

