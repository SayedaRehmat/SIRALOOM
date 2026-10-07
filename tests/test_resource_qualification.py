from gzip import open as gzip_open
from pathlib import Path
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
