from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.domain.reference_package import (
    CONTIG_POLICY_EXACT,
    REFERENCE_PACKAGE_SCHEMA_VERSION,
    ReferencePackageError,
    contig_manifest_sha256,
    contigs_from_fai,
    package_checksum,
    sha256_file,
    validate_reference_package,
)


def make_package(tmp_path: Path):
    fasta = tmp_path / "GRCh38.fa"
    sequence = "CAAAAAC"
    fasta.write_text(f">1\n{sequence}\n", encoding="utf-8")
    fai = tmp_path / "GRCh38.fa.fai"
    fai.write_text(f"1\t{len(sequence)}\t3\t{len(sequence)}\t{len(sequence)+1}\n", encoding="utf-8")
    contigs = contigs_from_fai(fai)
    fasta_sha = sha256_file(fasta)
    fai_sha = sha256_file(fai)
    contigs_sha = contig_manifest_sha256(contigs)
    checksum = package_checksum(
        genome_build="GRCh38",
        version="test-1",
        fasta_sha256=fasta_sha,
        fai_sha256=fai_sha,
        contigs_sha256=contigs_sha,
        assembly_name="GRCh38",
        assembly_accession="GCA_TEST_GRCH38",
        reference_source="TEST_FIXTURE",
        sequence_scope="TEST_CONTIG_SET",
    )
    resource = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        name="Test GRCh38 reference",
        provider="SIRALOOM_TEST",
        resource_type="REFERENCE_PACKAGE",
        version="test-1",
        genome_build="GRCh38",
        status="ACTIVE",
        checksum=checksum,
        metadata_json={
            "schema_version": REFERENCE_PACKAGE_SCHEMA_VERSION,
            "assembly_name": "GRCh38",
            "assembly_accession": "GCA_TEST_GRCH38",
            "reference_source": "TEST_FIXTURE",
            "sequence_scope": "TEST_CONTIG_SET",
            "contig_policy": CONTIG_POLICY_EXACT,
            "fasta_path": str(fasta),
            "fai_path": str(fai),
            "fasta_sha256": fasta_sha,
            "fai_sha256": fai_sha,
            "contigs_sha256": contigs_sha,
            "contigs": contigs,
        },
    )
    return resource, fasta, fai


def test_reference_package_contract_verifies_identity_and_contigs(tmp_path: Path):
    resource, _fasta, _fai = make_package(tmp_path)
    package = validate_reference_package(resource, expected_genome_build="GRCh38")
    assert package["genome_build"] == "GRCh38"
    assert package["contig_policy"] == "EXACT"
    assert package["package_checksum"] == resource.checksum


def test_reference_package_rejects_build_mismatch(tmp_path: Path):
    resource, _fasta, _fai = make_package(tmp_path)
    with pytest.raises(ReferencePackageError) as exc:
        validate_reference_package(resource, expected_genome_build="GRCh37")
    assert exc.value.code == "REFERENCE_BUILD_MISMATCH"


def test_reference_package_rejects_checksum_change(tmp_path: Path):
    resource, fasta, _fai = make_package(tmp_path)
    fasta.write_text(">1\nCAAAATC\n", encoding="utf-8")
    with pytest.raises(ReferencePackageError) as exc:
        validate_reference_package(resource, expected_genome_build="GRCh38")
    assert exc.value.code == "REFERENCE_CHECKSUM_MISMATCH"


def test_reference_package_allows_explicitly_pinned_superseded_version(tmp_path: Path):
    resource, _fasta, _fai = make_package(tmp_path)
    resource.status = "SUPERSEDED"
    package = validate_reference_package(resource, expected_genome_build="GRCh38")
    assert package["package_checksum"] == resource.checksum


def test_reference_package_supports_explicit_grch37_identity(tmp_path: Path):
    resource, _fasta, _fai = make_package(tmp_path)
    resource.genome_build = "GRCh37"
    resource.metadata_json["assembly_name"] = "GRCh37"
    resource.metadata_json["assembly_accession"] = "GCA_TEST_GRCH37"
    resource.metadata_json["reference_source"] = "TEST_FIXTURE"
    resource.metadata_json["sequence_scope"] = "TEST_CONTIG_SET"
    resource.checksum = package_checksum(
        genome_build="GRCh37",
        version=resource.version,
        fasta_sha256=resource.metadata_json["fasta_sha256"],
        fai_sha256=resource.metadata_json["fai_sha256"],
        contigs_sha256=resource.metadata_json["contigs_sha256"],
        assembly_name="GRCh37",
        assembly_accession="GCA_TEST_GRCH37",
        reference_source="TEST_FIXTURE",
        sequence_scope="TEST_CONTIG_SET",
    )
    package = validate_reference_package(resource, expected_genome_build="GRCh37")
    assert package["assembly_name"] == "GRCh37"
    assert package["genome_build"] == "GRCh37"


def test_reference_package_rejects_missing_assembly_identity(tmp_path: Path):
    resource, _fasta, _fai = make_package(tmp_path)
    del resource.metadata_json["assembly_accession"]
    with pytest.raises(ReferencePackageError) as exc:
        validate_reference_package(resource, expected_genome_build="GRCh38")
    assert exc.value.code == "REFERENCE_ASSEMBLY_IDENTITY_MISSING"
