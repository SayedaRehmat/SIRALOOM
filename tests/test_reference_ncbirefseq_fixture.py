from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.domain.reference_package import (
    REFERENCE_PACKAGE_LEGACY_BGZF_SCHEMA_VERSION,
    contig_manifest_sha256,
    contigs_from_fai,
    package_checksum,
    sha256_file,
    validate_reference_package,
)
from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_reference_alleles


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reference"
FASTA_SHA256 = "9a9eaab99264754b6afe617d3817db84f2256cce2b59b913d385a4b5e82804cc"
FAI_SHA256 = "bf544e276d397b4bc6f6e0e83bd9b8637439ebe2990a8580a9ea12d9f8ede283"
GZI_SHA256 = "067cbc024a24e2254ca591ea5022001639bb7ca11e089e70633db66b7c3b9dd9"
REFERENCE_VERSION = "NC_000007.14:140253336-141253335"


def _pinned_ncbi_reference_resource():
    fasta = FIXTURE_DIR / "reference.fa.bgz"
    fai = Path(f"{fasta}.fai")
    gzi = Path(f"{fasta}.gzi")
    assert sha256_file(fasta) == FASTA_SHA256
    assert sha256_file(fai) == FAI_SHA256
    assert sha256_file(gzi) == GZI_SHA256

    contigs = contigs_from_fai(fai)
    contigs_sha256 = contig_manifest_sha256(contigs)
    checksum = package_checksum(
        genome_build="GRCh38",
        version=REFERENCE_VERSION,
        fasta_sha256=FASTA_SHA256,
        fai_sha256=FAI_SHA256,
        gzi_sha256=GZI_SHA256,
        contigs_sha256=contigs_sha256,
        assembly_name="GRCh38.p14",
        assembly_accession="GCF_000001405.40",
        reference_source="NCBI RefSeq EFetch NC_000007.14",
        sequence_scope=REFERENCE_VERSION,
        schema_version=REFERENCE_PACKAGE_LEGACY_BGZF_SCHEMA_VERSION,
    )
    return SimpleNamespace(
        id="22222222-2222-2222-2222-222222222222",
        name="NCBI GRCh38.p14 chromosome 7 regional test fixture",
        provider="NCBI_REFSEQ",
        resource_type="REFERENCE_PACKAGE",
        version=REFERENCE_VERSION,
        genome_build="GRCh38",
        status="ACTIVE",
        checksum=checksum,
        metadata_json={
            "schema_version": REFERENCE_PACKAGE_LEGACY_BGZF_SCHEMA_VERSION,
            "assembly_name": "GRCh38.p14",
            "assembly_accession": "GCF_000001405.40",
            "reference_source": "NCBI RefSeq EFetch NC_000007.14",
            "sequence_scope": REFERENCE_VERSION,
            "contig_policy": "EXACT",
            "fasta_path": str(fasta),
            "fai_path": str(fai),
            "gzi_path": str(gzi),
            "fasta_sha256": FASTA_SHA256,
            "fai_sha256": FAI_SHA256,
            "gzi_sha256": GZI_SHA256,
            "contigs_sha256": contigs_sha256,
            "contigs": contigs,
        },
    )


def test_ncbi_grch38p14_bgzf_region_package_and_braf_ref_allele(tmp_path: Path):
    resource = _pinned_ncbi_reference_resource()
    package = validate_reference_package(resource, expected_genome_build="GRCh38")
    assert package["assembly_name"] == "GRCh38.p14"
    assert package["assembly_accession"] == "GCF_000001405.40"
    assert package["contigs"] == [{"name": "7", "length": 1_000_000}]

    vcf = tmp_path / "braf-v600e-region.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=7,length=1000000>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "7\t500001\t.\tA\tT\t.\tPASS\t.\n",
        encoding="ascii",
    )
    result = validate_vcf_reference_alleles(vcf, package["fasta_path"])
    assert result["result"] == "PASS"
    assert result["checked_record_count"] == 1

    vcf.write_text(vcf.read_text(encoding="ascii").replace("\tA\tT\t", "\tG\tT\t"), encoding="ascii")
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_reference_alleles(vcf, package["fasta_path"])
    assert exc.value.code == "VCF_REFERENCE_MISMATCH"
