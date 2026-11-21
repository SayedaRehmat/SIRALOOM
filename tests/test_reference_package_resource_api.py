from __future__ import annotations

import gzip
import hashlib
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1 import resources as resources_api
from backend.app.config import settings
from backend.app.domain.reference_identity import inspect_fasta_sequence_identity
from backend.app.domain.reference_package import (
    REFERENCE_PACKAGE_SCHEMA_VERSION,
    contig_manifest_sha256,
    contigs_from_fai,
    package_checksum,
    sha256_file,
)
from backend.app.domain.resource_staging import stage_resource_release
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, Resource, ResourceStaging


def _principal(organization_id):
    return SimpleNamespace(organization_id=organization_id, user_id=uuid4(), role="lab_director")


def _reference_manifest(root: Path, organization_id, *, package_version="fixture-1"):
    fasta = root / str(organization_id) / "NCBI" / package_version / "GRCh38.fa"
    fasta.parent.mkdir(parents=True, exist_ok=True)
    fasta.write_text(">1\nCAAAAACGT\n", encoding="ascii")
    fai = Path(f"{fasta}.fai")
    fai.write_text("1\t9\t3\t9\t10\n", encoding="ascii")
    contigs = contigs_from_fai(fai)
    sequence_identity = inspect_fasta_sequence_identity(fasta)
    dictionary = fasta.with_suffix(".dict")
    dictionary.write_text(
        "@HD\tVN:1.6\tSO:unsorted\n"
        + "".join(
            f"@SQ\tSN:{item['name']}\tLN:{item['length']}\tM5:{item['md5']}\n"
            for item in sequence_identity["sequences"]
        ),
        encoding="ascii",
    )
    fasta_sha = sha256_file(fasta)
    fai_sha = sha256_file(fai)
    dictionary_sha = sha256_file(dictionary)
    contigs_sha = contig_manifest_sha256(contigs)
    sequence_collection_digest = sequence_identity["sequence_collection_digest"]
    checksum = package_checksum(
        genome_build="GRCh38",
        version=package_version,
        fasta_sha256=fasta_sha,
        fai_sha256=fai_sha,
        contigs_sha256=contigs_sha,
        assembly_name="GRCh38",
        assembly_accession="GCA_TEST_GRCH38",
        reference_source="TEST_FIXTURE",
        sequence_scope="TEST_CONTIG_SET",
        schema_version=REFERENCE_PACKAGE_SCHEMA_VERSION,
        dictionary_sha256=dictionary_sha,
        sequence_collection_digest=sequence_collection_digest,
    )
    return {
        "package_version": package_version,
        "schema_version": REFERENCE_PACKAGE_SCHEMA_VERSION,
        "assembly_name": "GRCh38",
        "assembly_accession": "GCA_TEST_GRCH38",
        "reference_source": "TEST_FIXTURE",
        "sequence_scope": "TEST_CONTIG_SET",
        "contig_policy": "EXACT",
        "fasta_path": str(fasta),
        "fai_path": str(fai),
        "dictionary_path": str(dictionary),
        "fasta_sha256": fasta_sha,
        "fasta_size_bytes": fasta.stat().st_size,
        "fai_sha256": fai_sha,
        "dictionary_sha256": dictionary_sha,
        "contigs_sha256": contigs_sha,
        "contigs": contigs,
        "sequence_manifest": sequence_identity["sequences"],
        "sequence_collection_digest": sequence_collection_digest,
        "package_checksum": checksum,
        "source_contract": {
            "publisher": "NCBI",
            "canonical_source_url": "https://ncbi.example.test/genomes/",
            "artifact_url": "https://ncbi.example.test/genomes/GRCh38.fa.gz",
            "release_identity": package_version,
            "access_mode": "PUBLIC",
            "license_status": "NOT_REQUIRED",
            "checksum_status": "PUBLISHED_AND_VERIFIED",
            "authority_evidence_url": "https://ncbi.example.test/policy",
            "publisher_checksum_evidence": {
                "algorithm": "md5",
                "expected_digest": "a" * 32,
                "evidence_file_path": str(root / "md5checksums.txt"),
                "evidence_file_url": "https://ncbi.example.test/md5checksums.txt",
                "evidence_file_sha256": "b" * 64,
                "artifact_filename": "GRCh38.fa.gz",
            },
        },
        "execution": {
            "provider_id": "SIRALOOM_REFERENCE",
            "provider_version": "reference-builder-test",
            "access_method": "LOCAL",
            "location": str(fasta),
            "execution_scope": "ORGANIZATION_MANAGED",
            "toolchain": {"bcftools": {"version": "1.25"}, "samtools": "1.25"},
        },
    }


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_lab_reference_package_registration_and_preacquired_staging(monkeypatch, tmp_path):
    bcftools = shutil.which("bcftools")
    samtools = shutil.which("samtools")
    if not bcftools or not samtools:
        pytest.skip("reference qualification API requires the pinned BCFtools/SAMtools toolchain")
    engine, db = _db()
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Reference Lab", external_identifier="reference-lab"))
        db.commit()
        cache_root = tmp_path / "resource-cache"
        monkeypatch.setattr(settings, "resource_cache_root", str(cache_root))
        manifest = _reference_manifest(cache_root, organization_id)
        fasta_path = Path(manifest["fasta_path"])
        source_artifact = cache_root / "GRCh38.fa.gz"
        with source_artifact.open("wb") as raw_handle:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as gzip_handle:
                gzip_handle.write(fasta_path.read_bytes())
        source_digest = hashlib.md5(source_artifact.read_bytes(), usedforsecurity=False).hexdigest()
        evidence_file = cache_root / "md5checksums.txt"
        evidence_file.write_text(f"{source_digest}  GRCh38.fa.gz\n", encoding="ascii")
        manifest["source_contract"]["publisher_checksum_evidence"].update(
            {
                "expected_digest": source_digest,
                "evidence_file_path": str(evidence_file),
                "evidence_file_sha256": sha256(evidence_file.read_bytes()).hexdigest(),
                "verified_artifact_path": str(source_artifact),
            }
        )
        manifest["execution"]["toolchain"] = {
            "bcftools": {"version": subprocess.check_output([bcftools, "--version"], text=True).splitlines()[0].split()[-1]},
            "samtools": subprocess.check_output([samtools, "--version"], text=True).splitlines()[0].split()[-1],
        }
        result = resources_api.register_resource(
            {
                "name": "GRCh38 package",
                "provider": "SIRALOOM_REFERENCE",
                "resource_type": "REFERENCE_PACKAGE",
                "version": manifest["package_version"],
                "genome_build": "GRCh38",
                "access_method": "LOCAL",
                "location": manifest["fasta_path"],
                "checksum": manifest["package_checksum"],
                "status": "CANDIDATE",
                "metadata": manifest,
            },
            db,
            _principal(organization_id),
        )

        resource = db.get(Resource, UUID(result["resource_id"]))
        assert resource.organization_id == organization_id
        assert resource.status == "CANDIDATE"
        assert resource.location == manifest["fasta_path"]
        assert resource.checksum == manifest["package_checksum"]

        staging_payload = resources_api.ResourceStagingCreateRequest(
            source_uri=resource.location,
        )
        staging_result = resources_api.create_resource_staging(
            resource.id,
            staging_payload,
            db,
            _principal(organization_id),
        )
        staging = db.get(ResourceStaging, UUID(staging_result["staging_id"]))
        assert staging.status == "READY_TO_STAGE"
        assert staging.expected_sha256 == manifest["fasta_sha256"]
        assert staging.expected_size_bytes == manifest["fasta_size_bytes"]
        assert staging.metadata_json["storage_preflight"]["required_bytes"] == 0

        staged = stage_resource_release(
            db,
            staging,
            local_source_path=resource.location,
        )
        assert staged.status == "STAGED"
        assert staged.observed_sha256 == manifest["fasta_sha256"]
        assert staged.observed_size_bytes == manifest["fasta_size_bytes"]
        assert Path(resource.location).read_bytes().startswith(b">1\n")
        assert not list(Path(resource.location).parent.glob(".*.staging-*"))

        qualification = resources_api.qualify_resource(
            resource.id,
            {"qualification_version": "siraloom-reference-package-api-test-v1"},
            db,
            _principal(organization_id),
        )
        db.refresh(resource)
        assert qualification["passed"] is True, qualification["checks"].get("bcftools_execution")
        assert qualification["status"] == "QUALIFIED"
        assert qualification["checks"]["bcftools_execution"]["tests"]["valid_snv"]["status"] == "PASS"
        assert qualification["checks"]["bcftools_execution"]["tests"]["valid_small_indel"]["left_aligned"] is True
        assert qualification["checks"]["bcftools_execution"]["tests"]["incorrect_ref_rejected"]["reference_mismatch_reported"] is True
        assert resource.status == "QUALIFIED"
    finally:
        db.close()
        engine.dispose()


def test_lab_reference_package_registration_rejects_paths_outside_org_root(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Reference Lab", external_identifier="reference-lab"))
        db.commit()
        cache_root = tmp_path / "resource-cache"
        monkeypatch.setattr(settings, "resource_cache_root", str(cache_root))
        manifest = _reference_manifest(tmp_path / "outside", organization_id)
        with pytest.raises(HTTPException) as exc:
            resources_api.register_resource(
                {
                    "name": "External reference package",
                    "provider": "SIRALOOM_REFERENCE",
                    "resource_type": "REFERENCE_PACKAGE",
                    "version": manifest["package_version"],
                    "genome_build": "GRCh38",
                    "access_method": "LOCAL",
                    "location": manifest["fasta_path"],
                    "checksum": manifest["package_checksum"],
                    "status": "CANDIDATE",
                    "metadata": manifest,
                },
                db,
                _principal(organization_id),
            )
        assert exc.value.status_code == 400
        assert db.query(Resource).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_reference_package_staging_rejects_manifest_checksum_override(monkeypatch, tmp_path):
    engine, db = _db()
    try:
        organization_id = uuid4()
        db.add(Organization(id=organization_id, name="Reference Lab", external_identifier="reference-lab"))
        db.commit()
        cache_root = tmp_path / "resource-cache"
        monkeypatch.setattr(settings, "resource_cache_root", str(cache_root))
        manifest = _reference_manifest(cache_root, organization_id)
        result = resources_api.register_resource(
            {
                "name": "GRCh38 package",
                "provider": "SIRALOOM_REFERENCE",
                "resource_type": "REFERENCE_PACKAGE",
                "version": manifest["package_version"],
                "genome_build": "GRCh38",
                "access_method": "LOCAL",
                "location": manifest["fasta_path"],
                "checksum": manifest["package_checksum"],
                "status": "CANDIDATE",
                "metadata": manifest,
            },
            db,
            _principal(organization_id),
        )
        with pytest.raises(HTTPException) as exc:
            resources_api.create_resource_staging(
                UUID(result["resource_id"]),
                resources_api.ResourceStagingCreateRequest(
                    source_uri=manifest["fasta_path"],
                    expected_sha256=sha256(b"wrong").hexdigest(),
                ),
                db,
                _principal(organization_id),
            )
        assert exc.value.status_code == 409
        assert db.query(ResourceStaging).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_staging_worker_verifies_reference_package_in_org_root_without_copy(monkeypatch, tmp_path):
    from importlib import import_module

    from backend.app.infrastructure.db.models import ResourceStaging
    from backend.app.infrastructure.queue import celery_app as queue

    organization_id = uuid4()
    cache_root = tmp_path / "resource-cache"
    fasta = cache_root / str(organization_id) / "NCBI" / "v1" / "GRCh38.fa"
    fasta.parent.mkdir(parents=True)
    fasta.write_bytes(b">1\nACGT\n")
    staging_id, resource_id = uuid4(), uuid4()
    expected_sha = sha256(fasta.read_bytes()).hexdigest()
    resource = SimpleNamespace(
        id=resource_id,
        organization_id=organization_id,
        version="v1",
        resource_type="REFERENCE_PACKAGE",
        location=str(fasta),
        access_method="LOCAL",
        metadata_json={},
    )
    row = SimpleNamespace(
        id=staging_id,
        resource_id=resource_id,
        resource_version="v1",
        source_uri=str(fasta),
        destination_uri=str(fasta),
        storage_backend="ORGANIZATION_LOCAL_FILESYSTEM",
        status="READY_TO_STAGE",
        expected_sha256=expected_sha,
        expected_size_bytes=fasta.stat().st_size,
        observed_sha256=None,
        observed_size_bytes=None,
        attempt=0,
        error_code=None,
        error_message=None,
        metadata_json={
            "staging_mode": "VERIFY_EXISTING_REFERENCE_PACKAGE",
            "staging_dispatch": {"status": "PUBLISHED", "task_id": "dispatch-reference"},
        },
        started_at=None,
        completed_at=None,
    )

    class Engine:
        dialect = SimpleNamespace(name="sqlite")

    class DB:
        closed = False

        def get(self, model, object_id, **_kwargs):
            if model is ResourceStaging and object_id == staging_id:
                return row
            if model is Resource and object_id == resource_id:
                return resource
            raise AssertionError(f"Unexpected lookup: {model!r} {object_id!r}")

        def add(self, _row):
            pass

        def flush(self):
            pass

        def commit(self):
            pass

        def refresh(self, _row):
            pass

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    session_module = import_module("backend.app.infrastructure.db.session")
    db = DB()
    monkeypatch.setattr(session_module, "engine", Engine())
    monkeypatch.setattr(session_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(settings, "resource_cache_root", str(cache_root))
    monkeypatch.setattr(settings, "resource_staging_local_source_roots", str(tmp_path / "incoming-only"))

    task = queue.run_resource_staging_task
    task.push_request(id="dispatch-reference", retries=0, delivery_info={"redelivered": False})
    try:
        result = task.run(str(staging_id))
    finally:
        task.pop_request()

    assert result["status"] == "STAGED"
    assert result["observed_sha256"] == expected_sha
    assert row.status == "STAGED"
    assert row.attempt == 1
    assert row.metadata_json["staging_dispatch"]["status"] == "COMPLETED"
    assert fasta.read_bytes() == b">1\nACGT\n"
    assert db.closed is True
