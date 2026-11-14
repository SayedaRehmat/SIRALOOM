import gzip
import hashlib

import pytest
from pathlib import Path
from types import SimpleNamespace

from backend.app.domain.reference_identity import inspect_fasta_sequence_identity
from backend.app.domain.reference_package import validate_reference_package
from backend.app.domain.reference_provenance import PublisherChecksumError, verify_publisher_checksum_evidence
from scripts.reference import build_ncbi_grch38_reference_package as builder
from scripts.reference.register_and_qualify_reference_package import register_and_qualify


def test_ncbi_builder_verifies_publisher_md5_and_emits_qualified_package_manifest(tmp_path, monkeypatch):
    fasta_payload = b">chr1\nACAAAAGT\n>chrM\nTGCA\n"
    compressed = gzip.compress(fasta_payload)
    publisher_md5 = hashlib.md5(compressed, usedforsecurity=False).hexdigest()

    def fake_download(url, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(builder.FASTA_FILENAME):
            destination.write_bytes(compressed)
        else:
            destination.write_text(
                f"{publisher_md5}  {builder.FASTA_FILENAME}\n",
                encoding="ascii",
            )

    def fake_run(command, *, timeout=3600):
        if command[0] == "samtools" and command[1] == "faidx":
            fasta_path = Path(command[2])
            data = fasta_path.read_bytes()
            first_offset = data.index(b"ACGT")
            second_offset = data.index(b"TGCA")
            Path(str(fasta_path) + ".fai").write_text(
                f"chr1\t4\t{first_offset}\t4\t5\n"
                f"chrM\t4\t{second_offset}\t4\t5\n",
                encoding="ascii",
            )
            return "FAIDX OK"
        if command[0] == "java":
            fasta_path = Path(command[4].split("=", 1)[1])
            dictionary_path = Path(command[5].split("=", 1)[1])
            identity = inspect_fasta_sequence_identity(fasta_path)
            dictionary_path.write_text(
                "@HD\tVN:1.6\tSO:unsorted\n"
                + "".join(
                    f"@SQ\tSN:{item['name']}\tLN:{item['length']}\tM5:{item['md5']}\n"
                    for item in identity["sequences"]
                ),
                encoding="ascii",
            )
            return "PICARD OK"
        if command[0] == "samtools":
            return "samtools 1.21"
        if command[0] == "bcftools":
            return "bcftools 1.21"
        raise AssertionError(command)

    monkeypatch.setattr(builder, "_download", fake_download)
    monkeypatch.setattr(builder, "_run", fake_run)

    manifest = builder.build_package(
        tmp_path / "built",
        samtools="samtools",
        picard_jar=tmp_path / "picard.jar",
        bcftools="bcftools",
    )

    assert manifest["assembly_accession"] == "GCA_000001405.15"
    assert manifest["sequence_scope"] == "FULL_PLUS_HS38D1_ANALYSIS_SET"
    assert manifest["schema_version"] == "1.2"
    assert manifest["package_version"].startswith("ncbi-GCA_000001405.15")
    assert manifest["execution"]["toolchain"]["bcftools"]["version"] == "bcftools 1.21"
    assert manifest["qualification_preview"]["publisher_checksum"] == "VERIFIED"

    source_contract = manifest["source_contract"]
    evidence = verify_publisher_checksum_evidence(
        source_contract,
        artifact_path=manifest["fasta_path"],
    )
    assert evidence["status"] == "VERIFIED"
    assert evidence["observed_artifact_digest"] == publisher_md5

    resource = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        name="NCBI GRCh38 full plus hs38d1",
        provider="SIRALOOM_REFERENCE",
        resource_type="REFERENCE_PACKAGE",
        version=manifest["package_version"],
        genome_build="GRCh38",
        status="CANDIDATE",
        checksum=manifest["package_checksum"],
        metadata_json=manifest,
    )
    package = validate_reference_package(
        resource,
        expected_genome_build="GRCh38",
        allow_candidate_for_qualification=True,
    )
    assert package["sequence_collection_digest"] == manifest["sequence_collection_digest"]
    assert package["dictionary_identity"]["status"] == "VERIFIED"

    registry_report = register_and_qualify(
        tmp_path / "built" / "reference-package.json",
        f"sqlite+pysqlite:///{tmp_path / 'registry.sqlite'}",
    )
    assert registry_report["passed"] is True
    assert registry_report["resource_status"] == "QUALIFIED"
    assert registry_report["qualification_status"] == "QUALIFIED"
    assert registry_report["checks"]["bcftools_execution"]["status"] == "VERIFIED"
    assert registry_report["checks"]["bcftools_execution"]["tests"]["incorrect_ref_rejected"]["reference_mismatch_reported"] is True
    assert registry_report["activation"] == "NOT_REQUESTED_REQUIRES_SEPARATE_GOVERNANCE_APPROVAL"



def test_publisher_verified_source_must_decompress_to_registered_fasta(tmp_path):
    source_payload = b">chr1" + bytes((10,)) + b"ACGT" + bytes((10,))
    compressed = gzip.compress(source_payload)
    source_path = tmp_path / builder.FASTA_FILENAME
    source_path.write_bytes(compressed)
    checksum_path = tmp_path / "md5checksums.txt"
    source_md5 = hashlib.md5(compressed, usedforsecurity=False).hexdigest()
    checksum_path.write_text(f"{source_md5}  {builder.FASTA_FILENAME}" + chr(10), encoding="ascii")
    processed_fasta = tmp_path / "processed.fa"
    processed_fasta.write_bytes(b">chr1" + bytes((10,)) + b"TTTT" + bytes((10,)))
    evidence = {
        "publisher_checksum_evidence": {
            "algorithm": "md5",
            "expected_digest": source_md5,
            "evidence_file_path": str(checksum_path),
            "evidence_file_url": "https://ftp.ncbi.nlm.nih.gov/test/md5checksums.txt",
            "evidence_file_sha256": hashlib.sha256(checksum_path.read_bytes()).hexdigest(),
            "artifact_filename": builder.FASTA_FILENAME,
            "verified_artifact_path": str(source_path),
        },
        "artifact_url": builder.BASE_URL + builder.FASTA_FILENAME,
    }

    with pytest.raises(PublisherChecksumError) as exc:
        verify_publisher_checksum_evidence(evidence, artifact_path=processed_fasta)

    assert exc.value.code == "PUBLISHER_ARTIFACT_TRANSFORM_MISMATCH"



def test_publisher_verified_corrupt_gzip_is_a_blocking_qualification_error(tmp_path):
    compressed = bytearray(gzip.compress(b"A" * 100000))
    compressed[12] ^= 0xFF
    compressed = bytes(compressed)
    source_path = tmp_path / builder.FASTA_FILENAME
    source_path.write_bytes(compressed)
    checksum_path = tmp_path / "md5checksums.txt"
    source_md5 = hashlib.md5(compressed, usedforsecurity=False).hexdigest()
    checksum_path.write_text(f"{source_md5}  {builder.FASTA_FILENAME}" + chr(10), encoding="ascii")
    processed_fasta = tmp_path / "processed.fa"
    processed_fasta.write_bytes(b">chr1" + bytes((10,)) + b"ACGT" + bytes((10,)))
    evidence = {
        "publisher_checksum_evidence": {
            "algorithm": "md5",
            "expected_digest": source_md5,
            "evidence_file_path": str(checksum_path),
            "evidence_file_url": "https://ftp.ncbi.nlm.nih.gov/test/md5checksums.txt",
            "evidence_file_sha256": hashlib.sha256(checksum_path.read_bytes()).hexdigest(),
            "artifact_filename": builder.FASTA_FILENAME,
            "verified_artifact_path": str(source_path),
        },
        "artifact_url": builder.BASE_URL + builder.FASTA_FILENAME,
    }

    with pytest.raises(PublisherChecksumError) as exc:
        verify_publisher_checksum_evidence(evidence, artifact_path=processed_fasta)

    assert exc.value.code == "PUBLISHER_ARTIFACT_TRANSFORM_INVALID"
