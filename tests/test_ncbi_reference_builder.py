import gzip
import hashlib
from pathlib import Path
from types import SimpleNamespace

from backend.app.domain.reference_identity import inspect_fasta_sequence_identity
from backend.app.domain.reference_package import validate_reference_package
from backend.app.domain.reference_provenance import verify_publisher_checksum_evidence
from scripts.reference import build_ncbi_grch38_reference_package as builder


def test_ncbi_builder_verifies_publisher_md5_and_emits_qualified_package_manifest(tmp_path, monkeypatch):
    fasta_payload = b">chr1\nACGT\n>chrM\nTGCA\n"
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
            fasta_path = Path(command[2].split("=", 1)[1])
            dictionary_path = Path(command[3].split("=", 1)[1])
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
