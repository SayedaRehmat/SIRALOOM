from gzip import open as gzip_open
from pathlib import Path

from backend.app.domain.resource_qualification import qualify_resource
from backend.app.infrastructure.db.models import Resource


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
        }},
    )


def test_qualification_computes_integrity_and_structure(tmp_path):
    result = qualify_resource(_resource(tmp_path, checksum=None, checksum_status="NOT_PUBLISHED"))
    assert result.passed is False
    assert "AUTHORITATIVE_CHECKSUM_UNVERIFIED" in result.blockers
    assert result.checks["artifact_validation"] == "GZIP_XML_PREFIX_VALID"


def test_published_checksum_mismatch_is_blocking(tmp_path):
    result = qualify_resource(_resource(tmp_path, checksum="0" * 64))
    assert result.passed is False
    assert "CHECKSUM_MISMATCH" in result.blockers


def test_license_review_is_blocking(tmp_path):
    result = qualify_resource(_resource(tmp_path, checksum=None, license_status="REVIEW_REQUIRED", checksum_status="NOT_PUBLISHED"))
    assert result.passed is False
    assert "LICENSE_REVIEW_REQUIRED" in result.blockers


def test_missing_staging_is_actionable(tmp_path):
    resource = _resource(tmp_path, checksum="1" * 64)
    resource.location = "/var/lib/siraloom/staged/missing.xml.gz"
    result = qualify_resource(resource)
    assert result.passed is False
    assert "STAGED_ARTIFACT_MISSING" in result.blockers
    assert result.checks["qualification_outcome"] == "BLOCKED"

def test_clinvar_release_filename_mismatch_blocks_qualification(tmp_path):
    resource = _resource(tmp_path, checksum=None, checksum_status="NOT_PUBLISHED")
    metadata = dict(resource.metadata_json or {})
    contract = dict(metadata["source_contract"])
    contract["artifact_url"] = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/xml/ClinVarVCVRelease_2026-08.xml.gz"
    metadata["source_contract"] = contract
    resource.metadata_json = metadata

    result = qualify_resource(resource)

    assert result.passed is False
    assert result.checks["artifact_filename_match"] is False
    assert "ARTIFACT_RELEASE_FILENAME_MISMATCH" in result.blockers
