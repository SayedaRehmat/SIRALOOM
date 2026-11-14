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
    register_reference_package,
    validate_reference_registration,
)
from backend.app.domain.resource_qualification import qualify_resource
from backend.app.domain.reference_identity import inspect_fasta_sequence_identity


def _reference_candidate(tmp_path: Path):
    fasta = tmp_path / "GRCh38.fa"
    fasta.write_text(">chr1\nACGTACGT\n>chrM\nACGT\n", encoding="ascii")
    fai = tmp_path / "GRCh38.fa.fai"
    fai.write_text("chr1\t8\t6\t8\t9\nchrM\t4\t21\t4\t5\n", encoding="ascii")
    contigs = contigs_from_fai(fai)
    fasta_sha = sha256_file(fasta)
    fai_sha = sha256_file(fai)
    contigs_sha = contig_manifest_sha256(contigs)
    sequence_identity = inspect_fasta_sequence_identity(fasta)
    dictionary = tmp_path / "GRCh38.dict"
    dictionary.write_text(
        "@HD\tVN:1.6\tSO:unsorted\n"
        + "".join(
            f"@SQ\tSN:{item['name']}\tLN:{item['length']}\tM5:{item['md5']}\n"
            for item in sequence_identity["sequences"]
        ),
        encoding="ascii",
    )
    dictionary_sha = sha256_file(dictionary)
    version = "GRCh38-refseq-test.1"
    checksum = package_checksum(
        genome_build="GRCh38",
        version=version,
        fasta_sha256=fasta_sha,
        fai_sha256=fai_sha,
        contigs_sha256=contigs_sha,
        assembly_name="GRCh38",
        assembly_accession="GCF_TEST_GRCH38_FIXTURE",
        reference_source="NCBI_REFSEQ",
        sequence_scope="FULL_GENOMIC_FASTA",
        dictionary_sha256=dictionary_sha,
        sequence_collection_digest=sequence_identity["sequence_collection_digest"],
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
            "assembly_accession": "GCF_TEST_GRCH38_FIXTURE",
            "reference_source": "NCBI_REFSEQ",
            "sequence_scope": "FULL_GENOMIC_FASTA",
            "contig_policy": "EXACT",
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
            "source_contract": {
                "publisher": "NCBI",
                "canonical_source_url": "https://www.ncbi.nlm.nih.gov/datasets/",
                "artifact_url": "https://ftp.ncbi.nlm.nih.gov/genomes/all/test/GRCh38.fa",
                "release_identity": version,
                "access_mode": "PUBLIC",
                "license_status": "NOT_REQUIRED",
                "checksum_status": "PUBLISHED_AND_VERIFIED",
                "publisher_checksum_evidence": {
                    "algorithm": "md5",
                    "expected_digest": __import__("hashlib").md5(fasta.read_bytes(), usedforsecurity=False).hexdigest(),
                    "evidence_file_path": str(tmp_path / "publisher.md5"),
                    "evidence_file_url": "https://ftp.ncbi.nlm.nih.gov/genomes/all/test/md5checksums.txt",
                    "evidence_file_sha256": "",
                    "artifact_filename": fasta.name,
                    "verified_artifact_path": str(fasta),
                },
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
    publisher_evidence = Path(resource.metadata_json["source_contract"]["publisher_checksum_evidence"]["evidence_file_path"])
    expected_md5 = resource.metadata_json["source_contract"]["publisher_checksum_evidence"]["expected_digest"]
    publisher_evidence.write_text(f"{expected_md5}  {fasta.name}\n", encoding="ascii")
    resource.metadata_json["source_contract"]["publisher_checksum_evidence"]["evidence_file_sha256"] = sha256_file(publisher_evidence)
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
    assert result.checks["reference_package"]["assembly_accession"] == "GCF_TEST_GRCH38_FIXTURE"
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
            package_version=resource.version,
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
            package_version=resource.version,
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
            package_version=resource.version,
            package_checksum=resource.checksum,
        )
    assert exc.value.code == "REFERENCE_CONTIG_MANIFEST_INVALID"



class _RegistryDB:
    def __init__(self):
        self.rows = []

    def scalar(self, _query):
        return None

    def scalars(self, _query):
        class _Rows:
            @staticmethod
            def all():
                return []
        return _Rows()

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        return None


def test_reference_registration_creates_candidate_in_existing_resource_registry(tmp_path):
    resource, _staging = _reference_candidate(tmp_path)
    metadata = resource.metadata_json
    manifest = {
        key: value for key, value in metadata.items()
        if key not in {"source_contract", "execution"}
    }
    db = _RegistryDB()

    registered, created = register_reference_package(
        db,
        name=resource.name,
        provider=resource.provider,
        version=resource.version,
        genome_build=resource.genome_build,
        manifest=manifest,
        package_checksum=resource.checksum,
        source_contract=metadata["source_contract"],
        execution_contract=metadata["execution"],
    )

    assert created is True
    assert registered.resource_type == "REFERENCE_PACKAGE"
    assert registered.status == "CANDIDATE"
    assert registered.checksum == resource.checksum
    assert registered.location == metadata["fasta_path"]
    assert registered.metadata_json["registry_contract"] == "siraloom.reference-registry.v1"
    assert registered in db.rows
