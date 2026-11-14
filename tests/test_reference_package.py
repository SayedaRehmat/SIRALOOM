import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.domain.reference import FastaReference, ReferenceError, validate_bgzf_gzi_index
from backend.app.domain.reference_package import (
    CONTIG_POLICY_EXACT,
    REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION,
    REFERENCE_PACKAGE_SCHEMA_VERSION,
    ReferencePackageError,
    contig_manifest_sha256,
    contigs_from_fai,
    package_checksum,
    sha256_file,
    validate_fasta_index_consistency,
    validate_reference_package,
)
from backend.app.domain.reference_identity import inspect_fasta_sequence_identity\nfrom backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_reference_alleles,
    validate_vcf_strict,
)


def _write_sequence_dictionary(path: Path, identity: dict):
    path.write_text(
        "@HD\tVN:1.6\tSO:unsorted\n"
        + "".join(
            f"@SQ\tSN:{item['name']}\tLN:{item['length']}\tM5:{item['md5']}\n"
            for item in identity["sequences"]
        ),
        encoding="ascii",
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
    sequence_identity = inspect_fasta_sequence_identity(fasta)
    dictionary = tmp_path / "GRCh38.dict"
    _write_sequence_dictionary(dictionary, sequence_identity)
    dictionary_sha = sha256_file(dictionary)
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
        dictionary_sha256=dictionary_sha,
        sequence_collection_digest=sequence_identity["sequence_collection_digest"],
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
            "dictionary_path": str(dictionary),
            "dictionary_sha256": dictionary_sha,
            "sequence_manifest": sequence_identity["sequences"],
            "sequence_collection_digest": sequence_identity["sequence_collection_digest"],
            "fasta_sha256": fasta_sha,
            "fai_sha256": fai_sha,
            "contigs_sha256": contigs_sha,
            "contigs": contigs,
        },
    )
    return resource, fasta, fai


def _bgzf_block(data: bytes) -> bytes:
    compressor = zlib.compressobj(level=6, wbits=-15)
    payload = compressor.compress(data) + compressor.flush()
    prefix = b"\x1f\x8b\x08\x04" + b"\0" * 4 + b"\0\xff" + struct.pack("<H", 6) + b"BC\x02\0"
    block_size = len(prefix) + 2 + len(payload) + 8
    return (
        prefix
        + struct.pack("<H", block_size - 1)
        + payload
        + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))
    )


def _write_bgzf_with_gzi(path: Path, data: bytes, *, chunk_size: int = 9) -> Path:
    chunks = [data[offset:offset + chunk_size] for offset in range(0, len(data), chunk_size)]
    blocks = [_bgzf_block(chunk) for chunk in chunks]
    gzi_pairs = []
    compressed_offset = 0
    uncompressed_offset = 0
    for index, (chunk, block) in enumerate(zip(chunks, blocks)):
        if index:
            gzi_pairs.append((compressed_offset, uncompressed_offset))
        compressed_offset += len(block)
        uncompressed_offset += len(chunk)
    blocks.append(_bgzf_block(b""))
    path.write_bytes(b"".join(blocks))
    gzi_path = Path(f"{path}.gzi")
    gzi_path.write_bytes(
        struct.pack("<Q", len(gzi_pairs))
        + b"".join(struct.pack("<QQ", compressed, uncompressed) for compressed, uncompressed in gzi_pairs)
    )
    return gzi_path


def make_bgzf_package(tmp_path: Path):
    resource, _plain_fasta, _plain_fai = make_package(tmp_path)
    fasta_bytes = b">1 description\nACGT\nACGT\nAC\n"
    fasta = tmp_path / "GRCh38.fa.bgz"
    gzi = _write_bgzf_with_gzi(fasta, fasta_bytes)
    fai = Path(f"{fasta}.fai")
    fai.write_text("1\t10\t15\t4\t5\n", encoding="utf-8")
    contigs = contigs_from_fai(fai)
    fasta_sha = sha256_file(fasta)
    fai_sha = sha256_file(fai)
    gzi_sha = sha256_file(gzi)
    contigs_sha = contig_manifest_sha256(contigs)
    sequence_identity = inspect_fasta_sequence_identity(fasta)
    dictionary = tmp_path / "GRCh38-bgzf.dict"
    _write_sequence_dictionary(dictionary, sequence_identity)
    dictionary_sha = sha256_file(dictionary)
    metadata = resource.metadata_json
    metadata.update({
        "schema_version": REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION,
        "dictionary_path": str(dictionary),
        "dictionary_sha256": dictionary_sha,
        "sequence_manifest": sequence_identity["sequences"],
        "sequence_collection_digest": sequence_identity["sequence_collection_digest"],
        "fasta_path": str(fasta),
        "fai_path": str(fai),
        "gzi_path": str(gzi),
        "fasta_sha256": fasta_sha,
        "fai_sha256": fai_sha,
        "gzi_sha256": gzi_sha,
        "contigs_sha256": contigs_sha,
        "contigs": contigs,
    })
    resource.checksum = package_checksum(
        genome_build="GRCh38",
        version=resource.version,
        fasta_sha256=fasta_sha,
        fai_sha256=fai_sha,
        gzi_sha256=gzi_sha,
        contigs_sha256=contigs_sha,
        assembly_name="GRCh38",
        assembly_accession="GCA_TEST_GRCH38",
        reference_source="TEST_FIXTURE",
        sequence_scope="TEST_CONTIG_SET",
        schema_version=REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION,
        dictionary_sha256=dictionary_sha,
        sequence_collection_digest=sequence_identity["sequence_collection_digest"],
    )
    return resource, fasta, fai, gzi


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


def test_reference_package_verifies_bgzf_gzi_and_random_access_reads(tmp_path: Path):
    resource, fasta, _fai, gzi = make_bgzf_package(tmp_path)

    package = validate_reference_package(resource, expected_genome_build="GRCh38")
    with FastaReference(fasta) as reference:
        observed = reference.fetch("1", 2, 9)

    assert observed == "GTACGTA"
    assert package["gzi_path"] == str(gzi)
    assert package["gzi_sha256"] == sha256_file(gzi)
    assert package["package_checksum"] == resource.checksum


def test_reference_package_rejects_missing_bgzf_gzi(tmp_path: Path):
    resource, _fasta, _fai, _gzi = make_bgzf_package(tmp_path)
    resource.metadata_json["gzi_path"] = str(tmp_path / "missing.gzi")

    with pytest.raises(ReferencePackageError) as exc:
        validate_reference_package(resource, expected_genome_build="GRCh38")

    assert exc.value.code == "REFERENCE_GZI_MISSING"


def test_reference_package_rejects_gzi_that_does_not_match_bgzf(tmp_path: Path):
    resource, _fasta, _fai, gzi = make_bgzf_package(tmp_path)
    gzi.write_bytes(struct.pack("<Q", 0))
    resource.metadata_json["gzi_sha256"] = sha256_file(gzi)

    with pytest.raises(ReferencePackageError) as exc:
        validate_reference_package(resource, expected_genome_build="GRCh38")

    assert exc.value.code == "REFERENCE_GZI_MISMATCH"


def test_reference_reader_interoperates_with_htslib_generated_bgzf_gzi(tmp_path: Path):
    bgzip = shutil.which("bgzip")
    if bgzip is None:
        pytest.skip("HTSlib bgzip executable is not installed")

    sequence = "ACGT" * 25_000
    line_bases = 60
    header = b">ctg1 description\n"
    fasta_content = header + b"".join(
        (sequence[offset:offset + line_bases] + "\n").encode("ascii")
        for offset in range(0, len(sequence), line_bases)
    )
    plain_fasta = tmp_path / "reference.fa"
    plain_fasta.write_bytes(fasta_content)
    fasta = tmp_path / "reference.fa.bgz"
    gzi = Path(f"{fasta}.gzi")

    with fasta.open("wb") as output:
        subprocess.run(
            [bgzip, "-i", "-c", "-I", str(gzi), "-s", "1000", str(plain_fasta)],
            stdout=output,
            stderr=subprocess.PIPE,
            check=True,
            timeout=30,
        )

    fai = Path(f"{fasta}.fai")
    fai.write_text(
        f"ctg1\t{len(sequence)}\t{len(header)}\t{line_bases}\t{line_bases + 1}\n",
        encoding="ascii",
    )
    assert validate_bgzf_gzi_index(fasta, gzi)["gzi_entry_count"] >= 1
    with FastaReference(fasta, fai, gzi) as reference:
        for start, end in ((0, 1), (999, 1002), (59_990, 60_070), (65_530, 65_580), (99_000, 100_000)):
            assert reference.fetch("ctg1", start, end) == sequence[start:end]


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
        dictionary_sha256=resource.metadata_json["dictionary_sha256"],
        sequence_collection_digest=resource.metadata_json["sequence_collection_digest"],
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

    with FastaReference(fasta) as reference, pytest.raises(ReferenceError):
        reference.resolve_contig("NC_012920.2")


def test_reference_package_rejects_stale_fai_offset(tmp_path: Path):
    resource, _fasta, fai = make_package(tmp_path)
    fields = fai.read_text(encoding="utf-8").strip().split("\t")
    fields[2] = str(int(fields[2]) + 1)
    fai.write_text("\t".join(fields) + "\n", encoding="utf-8")
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


def test_fasta_index_consistency_accepts_iupac_bases_and_rejects_invalid_symbols(tmp_path: Path):
    fasta = tmp_path / "reference.fa"
    fai = tmp_path / "reference.fa.fai"
    fasta.write_bytes(b">1\nACGTRYSWKMBDHVNacgtryswkmbdhvn\n")
    fai.write_text("1\t30\t3\t30\t31\n", encoding="utf-8")
    assert validate_fasta_index_consistency(fasta, fai) == [{"name": "1", "length": 30}]

    fasta.write_bytes(b">1\nACGTX\n")
    fai.write_text("1\t5\t3\t5\t6\n", encoding="utf-8")
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
