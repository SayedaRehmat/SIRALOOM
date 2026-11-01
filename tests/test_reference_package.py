from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.domain.reference import FastaReference, ReferenceError
from backend.app.domain.vcf_validation import validate_vcf_reference_alleles
from backend.app.domain.reference_package import (
    CONTIG_POLICY_EXACT,
    REFERENCE_PACKAGE_SCHEMA_VERSION,
    ReferencePackageError,
    contig_manifest_sha256,
    contigs_from_fai,
    package_checksum,
    sha256_file,
    validate_reference_package,
    validate_fasta_index_consistency,
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

def test_reference_package_allows_qualified_status_only_when_governed_fallback_is_explicit(tmp_path: Path):
    resource, _fasta, _fai = make_package(tmp_path)
    resource.status = "QUALIFIED"
    with pytest.raises(ReferencePackageError) as exc:
        validate_reference_package(resource, expected_genome_build="GRCh38")
    assert exc.value.code == "REFERENCE_PACKAGE_NOT_ACTIVE"

    package = validate_reference_package(
        resource,
        expected_genome_build="GRCh38",
        allow_approved_qualified=True,
    )
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


def test_vcf_reference_validation_resolves_human_mitochondrial_refseq_accession(
    tmp_path: Path,
):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">chrM\nACGT\n", encoding="utf-8")
    Path(f"{fasta}.fai").write_text("chrM\t4\t6\t4\t5\n", encoding="utf-8")
    vcf = tmp_path / "mitochondrial-accession.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.3\n"
        '##contig=<ID=NC_012920.1,length=4>\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "NC_012920.1\t1\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with FastaReference(fasta) as reference:
        assert reference.resolve_contig("NC_012920.1") == "chrM"

    result = validate_vcf_reference_alleles(vcf, fasta)

    assert result["checked_record_count"] == 1


def test_reference_does_not_alias_unqualified_mitochondrial_accession_versions(
    tmp_path: Path,
):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">chrM\nACGT\n", encoding="utf-8")
    Path(f"{fasta}.fai").write_text("chrM\t4\t6\t4\t5\n", encoding="utf-8")

    with FastaReference(fasta) as reference:
        with pytest.raises(ReferenceError):
            reference.resolve_contig("NC_012920.2")


def test_reference_package_rejects_stale_fai_offset(tmp_path: Path):
    resource, _fasta, fai = make_package(tmp_path)
    fields = fai.read_text(encoding="utf-8").strip().split("\\t")
    fields[2] = str(int(fields[2]) + 1)
    fai.write_text("\\t".join(fields) + "\\n", encoding="utf-8")
    with pytest.raises(ReferencePackageError) as exc:
        validate_reference_package(resource, expected_genome_build="GRCh38")
    assert exc.value.code == "REFERENCE_CHECKSUM_MISMATCH"


def test_fasta_index_consistency_rejects_sequence_length_mismatch(tmp_path: Path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1\\nACGTAC\\n", encoding="utf-8")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text("1\\t5\\t3\\t6\\t7\\n", encoding="utf-8")
    with pytest.raises(ReferencePackageError) as exc:
        validate_fasta_index_consistency(fasta, fai)
    assert exc.value.code == "REFERENCE_FAI_MISMATCH"


def test_fasta_index_consistency_rejects_stale_byte_offset(tmp_path: Path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1 description\\nACGT\\n", encoding="utf-8")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text("1\\t4\\t4\\t4\\t5\\n", encoding="utf-8")
    with pytest.raises(ReferencePackageError) as exc:
        validate_fasta_index_consistency(fasta, fai)
    assert exc.value.code == "REFERENCE_FAI_MISMATCH"


def test_fasta_index_consistency_accepts_multiline_crlf_fasta(tmp_path: Path):
    fasta = tmp_path / "reference.fa"
    fasta.write_bytes(b">1 description\\r\\nACGT\\r\\nAC\\r\\n")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text("1\\t6\\t16\\t4\\t6\\n", encoding="utf-8")
    result = validate_fasta_index_consistency(fasta, fai)
    assert result == [{"name": "1", "length": 6}]
