from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain.reference_package import (
    REFERENCE_PACKAGE_SCHEMA_VERSION,
    contig_manifest_sha256,
    contigs_from_fai,
    package_checksum,
    sha256_file,
)
from backend.app.domain.reference_registry import (
    ReferenceRegistryError,
    validate_reference_registration,
)
from backend.app.domain.resource_qualification import qualify_resource


def _reference_candidate(tmp_path: Path):
    fasta = tmp_path / "GRCh38.fa"
    fasta.write_text(">chr1\nACGTACGT\n>chrM\nACGT\n", encoding="ascii")
    fai = tmp_path / "GRCh38.fa.fai"
    fai.write_text("chr1\t8\t6\t8\t9\nchrM\t4\t21\t4\t5\n", encoding="ascii")
    contigs = contigs_from_fai(fai)
    fasta_sha = sha256_file(fasta)
    fai_sha = sha256_file(fai)
    contigs_sha = contig_manifest_sha256(contigs)
    version = "GRCh38-refseq-test.1"
    checksum = package_checksum(
        genome_build="GRCh38",
        version=version,
        fasta_sha256=fasta_sha,
        fai_sha256=fai_sha,
        contigs_sha256=contigs_sha,
        assembly_name="GRCh38",
        assembly_accession="GCF_000001405.40",
        reference_source="NCBI_REFSEQ",
        sequence_scope="FULL_GENOMIC_FASTA",
    )
    resource_id = uuid4()
    resource = SimpleNamespace(
        id=resource_id,
        name="GRCh38 RefSeq test package",
        provider="SIRALOOM_REFERENCE",
        resource_type="REFERENCE_PACKAGE",
        version=version,
        genome_build="GRCh38",
        status="CANDIDATE",
        access_method="LOCAL",
        organization_id=None,
        checksum=checksum,
        location=str(fasta),
        metadata_json={
            "schema_version": REFERENCE_PACKAGE_SCHEMA_VERSION,
            "assembly_name": "GRCh38",
            "assembly_accession": "GCF_000001405.40",
            "reference_source": "NCBI_REFSEQ",
            "sequence_scope": "FULL_GENOMIC_FASTA",
            "contig_policy": "EXACT",
            "fasta_path": str(fasta),
            "fai_path": str(fai),
            "fasta_sha256": fasta_sha,
            "fai_sha256": fai_sha,
            "contigs_sha256": contigs_sha,
            "contigs": contigs,
            "source_contract": {
                "publisher": "NCBI",
                "canonical_source_url": "https://www.ncbi.nlm.nih.gov/datasets/",
                "artifact_url": "https://ftp.ncbi.nlm.nih.gov/genomes/all/test/GRCh38.fa",
                "release_identity": version,
                "access_mode": "PUBLIC",
                "license_status": "NOT_REQUIRED",
                "checksum_status": "PUBLISHED_AND_VERIFIED",
                "authority_evidence_url": "https://www.ncbi.nlm.nih.gov/datasets/docs/",
            },
            "execution": {
                "provider_id": "SIRALOOM_REFERENCE",
                "provider_version": "reference-package-v1",
                "access_method": "LOCAL",
                "location": str(fasta),
                "toolchain": {"bcftools": {"version": "1.25"}},
            },
        },
    )
    staging = SimpleNamespace(
        id=uuid4(),
        resource_id=resource_id,
        resource_version=version,
        staging_key="test:reference",
        source_uri="https://ftp.ncbi.nlm.nih.gov/genomes/all/test/GRCh38.fa",
        destination_uri=str(fasta),
        storage_backend="LOCAL_FILESYSTEM",
        status="STAGED",
        expected_sha256=fasta_sha,
        observed_sha256=fasta_sha,
        expected_size_bytes=fasta.stat().st_size,
        observed_size_bytes=fasta.stat().st_size,
    )
    return resource, staging


def test_reference_candidate_must_pass_full_package_validation(tmp_path):
    resource, staging = _reference_candidate(tmp_path)

    result = qualify_resource(
        resource,
        staging=staging,
        qualification_version="siraloom-reference-package-v1",
    )

    assert result.passed is True
    assert result.checks["reference_package"]["status"] == "VERIFIED"
    assert result.checks["reference_package"]["assembly_accession"] == "GCF_000001405.40"
    assert result.checks["reference_package"]["contig_count"] == 2
    assert result.checks["checksum_match"] is True
    assert result.checks["staging_expected_checksum_match"] is True


def test_reference_candidate_is_blocked_when_fasta_bytes_change(tmp_path):
    resource, staging = _reference_candidate(tmp_path)
    Path(resource.location).write_text(">chr1\nACGTTCGT\n>chrM\nACGT\n", encoding="ascii")

    result = qualify_resource(resource, staging=staging)

    assert result.passed is False
    assert "REFERENCE_PACKAGE_VALIDATION_FAILED" in result.blockers
    assert result.checks["reference_package"]["error_code"] == "REFERENCE_CHECKSUM_MISMATCH"
    assert "CHECKSUM_MISMATCH" in result.blockers
    assert "STAGING_CHECKSUM_MISMATCH" in result.blockers


def test_reference_candidate_is_blocked_when_index_bytes_change(tmp_path):
    resource, staging = _reference_candidate(tmp_path)
    Path(resource.metadata_json["fai_path"]).write_text(
        "chr1\t8\t7\t8\t9\nchrM\t4\t21\t4\t5\n",
        encoding="ascii",
    )

    result = qualify_resource(resource, staging=staging)

    assert result.passed is False
    assert "REFERENCE_PACKAGE_VALIDATION_FAILED" in result.blockers
    assert result.checks["reference_package"]["error_code"] == "REFERENCE_CHECKSUM_MISMATCH"


def test_reference_registration_rejects_implicit_contig_alias_policy(tmp_path):
    resource, _staging = _reference_candidate(tmp_path)
    manifest = {
        key: value for key, value in resource.metadata_json.items()
        if key not in {"source_contract", "execution"}
    }
    manifest["contig_policy"] = "ALIAS"
    with pytest.raises(ReferenceRegistryError) as exc:
        validate_reference_registration(
            manifest,
            genome_build="GRCh38",
            package_checksum=resource.checksum,
        )
    assert exc.value.code == "REFERENCE_CONTIG_POLICY_INVALID"


def test_reference_registration_rejects_build_and_assembly_name_disagreement(tmp_path):
    resource, _staging = _reference_candidate(tmp_path)
    manifest = {
        key: value for key, value in resource.metadata_json.items()
        if key not in {"source_contract", "execution"}
    }
    with pytest.raises(ReferenceRegistryError) as exc:
        validate_reference_registration(
            manifest,
            genome_build="GRCh37",
            package_checksum=resource.checksum,
        )
    assert exc.value.code == "REFERENCE_BUILD_IDENTITY_MISMATCH"


def test_reference_registration_requires_ordered_contig_manifest(tmp_path):
    resource, _staging = _reference_candidate(tmp_path)
    manifest = {
        key: value for key, value in resource.metadata_json.items()
        if key not in {"source_contract", "execution"}
    }
    manifest["contigs"] = [{"name": "chr1", "length": 8}, {"name": "chr1", "length": 8}]
    with pytest.raises(ReferenceRegistryError) as exc:
        validate_reference_registration(
            manifest,
            genome_build="GRCh38",
            package_checksum=resource.checksum,
        )
    assert exc.value.code == "REFERENCE_CONTIG_MANIFEST_INVALID"
