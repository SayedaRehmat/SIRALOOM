from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.domain.reference import FastaReference, ReferenceError
from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_reference_alleles,
    validate_vcf_strict,
)
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


def test_strict_vcf_validation_accepts_only_explicit_reference_contig_aliases(tmp_path: Path):
    valid = tmp_path / "mitochondrial-explicit-alias.vcf"
    valid.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "NC_012920.1\t1\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    profile = validate_vcf_strict(valid, reference_contigs={"chrM"})
    assert profile["records"] == 1
    assert profile["reference_contig_policy"] == "EXACT_OR_EXPLICIT_ALIAS"
    with pytest.raises(ReferenceError, match="maps ambiguously"):
        FastaReference.resolve_contig_name("NC_012920.1", {"M", "chrM"})

    invalid = tmp_path / "mitochondrial-wrong-accession-version.vcf"
    invalid.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "NC_012920.2\t1\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(invalid, reference_contigs={"chrM"})
    assert getattr(exc.value, "code", None) == "REFERENCE_CONTIG_MISMATCH"


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
    assert result["resolved_contig_aliases"] == {"NC_012920.1": "chrM"}


def test_vcf_reference_validation_records_aliases_when_contig_header_is_absent(tmp_path: Path):
    fasta = tmp_path / "reference-no-contig-header.fa"
    fasta.write_text(">chrM\nACGT\n", encoding="utf-8")
    Path(f"{fasta}.fai").write_text("chrM\t4\t6\t4\t5\n", encoding="utf-8")
    vcf = tmp_path / "mitochondrial-accession-no-contig-header.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "NC_012920.1\t1\t.\tA\tG\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf_reference_alleles(vcf, fasta)

    assert result["checked_record_count"] == 1
    assert result["resolved_contig_aliases"] == {"NC_012920.1": "chrM"}


def test_reference_validation_records_aliases_resolved_from_breakend_mates(tmp_path: Path):
    fasta = tmp_path / "reference-breakend-alias.fa"
    fasta.write_text(">chrM\nACGT\n", encoding="utf-8")
    Path(f"{fasta}.fai").write_text("chrM\t4\t6\t4\t5\n", encoding="utf-8")
    vcf = tmp_path / "breakend-mate-alias.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chrM\t1\t.\tA\tA]NC_012920.1:2]\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    result = validate_vcf_reference_alleles(vcf, fasta)

    assert result["checked_record_count"] == 1
    assert result["checked_breakend_mate_count"] == 1
    assert result["resolved_contig_aliases"] == {"NC_012920.1": "chrM"}


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
    fields = fai.read_text(encoding="utf-8").strip().split("\t")
    fields[2] = str(int(fields[2]) + 1)
    fai.write_text("\t".join(fields) + "\\n", encoding="utf-8")
    with pytest.raises(ReferencePackageError) as exc:
        validate_reference_package(resource, expected_genome_build="GRCh38")
    assert exc.value.code == "REFERENCE_CHECKSUM_MISMATCH"


def test_fasta_index_consistency_rejects_sequence_length_mismatch(tmp_path: Path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1\nACGTAC\n", encoding="utf-8")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text("1\t5\t3\t6\t7\n", encoding="utf-8")
    with pytest.raises(ReferencePackageError) as exc:
        validate_fasta_index_consistency(fasta, fai)
    assert exc.value.code == "REFERENCE_FAI_MISMATCH"


def test_fasta_index_consistency_rejects_stale_byte_offset(tmp_path: Path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1 description\nACGT\n", encoding="utf-8")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text("1\t4\t4\t4\t5\n", encoding="utf-8")
    with pytest.raises(ReferencePackageError) as exc:
        validate_fasta_index_consistency(fasta, fai)
    assert exc.value.code == "REFERENCE_FAI_MISMATCH"


def test_fasta_index_consistency_rejects_oversized_final_sequence_line(tmp_path: Path):
    fasta = tmp_path / "reference.fa"
    fasta.write_text(">1\nACGT\nACGTA\n", encoding="utf-8")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text("1\t9\t3\t4\t5\n", encoding="utf-8")
    with pytest.raises(ReferencePackageError) as exc:
        validate_fasta_index_consistency(fasta, fai)
    assert exc.value.code == "REFERENCE_FASTA_INVALID"


def test_fasta_index_consistency_accepts_gzip_fasta_with_uncompressed_fai_offsets(tmp_path: Path):
    import gzip

    fasta = tmp_path / "reference.fa.gz"
    with gzip.open(fasta, "wb") as handle:
        handle.write(b">1 description\nACGT\nAC\n")
    fai = tmp_path / "reference.fa.gz.fai"
    fai.write_text("1\t6\t15\t4\t5\n", encoding="utf-8")
    result = validate_fasta_index_consistency(fasta, fai)
    assert result == [{"name": "1", "length": 6}]


def test_fasta_index_consistency_accepts_multiline_crlf_fasta(tmp_path: Path):
    fasta = tmp_path / "reference.fa"
    fasta.write_bytes(b">1 description\r\nACGT\r\nAC\r\n")
    fai = tmp_path / "reference.fa.fai"
    fai.write_text("1\t6\t16\t4\t6\n", encoding="utf-8")
    result = validate_fasta_index_consistency(fasta, fai)
    assert result == [{"name": "1", "length": 6}]


def _write_test_bgzf(path: Path, payload: bytes, *, block_size: int = 10_000) -> None:
    """Write valid BGZF members and a matching little-endian .gzi index."""
    import binascii
    import struct
    import zlib

    def make_block(data: bytes) -> bytes:
        compressor = zlib.compressobj(level=6, wbits=-15)
        compressed = compressor.compress(data) + compressor.flush()
        extra = b"BC" + struct.pack("<H", 2) + b"\\x00\\x00"
        header = (
            b"\\x1f\\x8b\\x08\\x04"
            + b"\\x00\\x00\\x00\\x00"
            + b"\\x00\\xff"
            + struct.pack("<H", len(extra))
            + extra
        )
        total_size = len(header) + len(compressed) + 8
        header = header[:-2] + struct.pack("<H", total_size - 1)
        trailer = struct.pack(
            "<II",
            binascii.crc32(data) & 0xFFFFFFFF,
            len(data) & 0xFFFFFFFF,
        )
        block = header + compressed + trailer
        assert len(block) == total_size <= 65536
        return block

    compressed_offset = 0
    uncompressed_offset = 0
    index_entries: list[tuple[int, int]] = []
    with path.open("wb") as handle:
        chunks = [
            payload[start : start + block_size]
            for start in range(0, len(payload), block_size)
        ]
        for block_index, chunk in enumerate(chunks):
            if block_index:
                index_entries.append((compressed_offset, uncompressed_offset))
            block = make_block(chunk)
            handle.write(block)
            compressed_offset += len(block)
            uncompressed_offset += len(chunk)
        handle.write(make_block(b""))

    gzi = Path(f"{path}.gzi")
    gzi.write_bytes(
        struct.pack("<Q", len(index_entries))
        + b"".join(struct.pack("<QQ", compressed, uncompressed) for compressed, uncompressed in index_entries)
    )


def _write_bgzf_reference(tmp_path: Path) -> tuple[Path, str]:
    sequence = "ACGT" * 30_000
    header = b">1 description\\n"
    sequence_lines = [
        sequence[start : start + 60].encode("ascii") + b"\\n"
        for start in range(0, len(sequence), 60)
    ]
    fasta_bytes = header + b"".join(sequence_lines)
    fasta = tmp_path / "reference.fa.bgz"
    _write_test_bgzf(fasta, fasta_bytes)
    fai = Path(f"{fasta}.fai")
    fai.write_text(
        f"1\\t{len(sequence)}\\t{len(header)}\\t60\\t61\\n",
        encoding="utf-8",
    )
    return fasta, sequence


def test_fasta_reference_reads_bgzf_with_uncompressed_fai_offsets_and_gzi(tmp_path: Path):
    fasta, sequence = _write_bgzf_reference(tmp_path)

    contigs = validate_fasta_index_consistency(fasta, Path(f"{fasta}.fai"))
    assert contigs == [{"name": "1", "length": len(sequence)}]

    with FastaReference(fasta) as reference:
        assert reference.fetch("1", 9_820, 9_860) == sequence[9_820:9_860]
        assert reference.fetch("1", 59_990, 60_030) == sequence[59_990:60_030]
        assert reference.base("1", 120_000) == sequence[-1]


def test_vcf_reference_validation_reads_bgzf_reference_across_block_boundary(tmp_path: Path):
    fasta, sequence = _write_bgzf_reference(tmp_path)
    position = 9_821
    ref = sequence[position - 1 : position + 4]
    alt = "T" if ref[0] != "T" else "C"
    vcf = tmp_path / "bgzf-reference.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.3\\n"
        f"##contig=<ID=1,length={len(sequence)}>\\n"
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\n"
        f"1\\t{position}\\t.\\t{ref}\\t{alt}\\t.\\tPASS\\t.\\n",
        encoding="utf-8",
    )

    result = validate_vcf_reference_alleles(vcf, fasta)

    assert result["checked_record_count"] == 1
    assert result["resolved_contig_aliases"] == {}


def test_fasta_reference_rejects_bgzf_without_matching_gzi(tmp_path: Path):
    fasta = tmp_path / "reference.fa.bgz"
    fasta.write_bytes(b"not-a-bgzf-stream")
    Path(f"{fasta}.fai").write_text("1\\t4\\t3\\t4\\t5\\n", encoding="utf-8")

    with pytest.raises(ReferenceError) as exc:
        FastaReference(fasta)

    assert exc.value.code == "REFERENCE_BGZF_INDEX_MISSING"
