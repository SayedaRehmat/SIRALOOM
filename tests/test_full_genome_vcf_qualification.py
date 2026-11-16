from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validation" / "run_full_genome_vcf_qualification.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_full_genome_vcf_qualification", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_genome_runner_requires_exact_gatk_version_and_records_binary_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load_runner()
    executable = tmp_path / "gatk"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda name: str(executable) if name == "gatk" else None)
    monkeypatch.setattr(
        module,
        "run_command",
        lambda command, timeout: {
            "command": command,
            "exit_code": 0,
            "stdout": "The Genome Analysis Toolkit (GATK) v4.6.2.0\\n",
            "stderr": "",
        },
    )
    monkeypatch.setattr(module, "sha256_file", lambda path: "a" * 64)

    result = module.require_gatk("4.6.2.0")

    assert result["observed_version"] == "4.6.2.0"
    assert result["expected_version"] == "4.6.2.0"
    assert result["executable_sha256"] == "a" * 64
    assert result["version_evidence"]["exit_code"] == 0


def test_full_genome_runner_rejects_gatk_version_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_runner()
    executable = tmp_path / "gatk"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(
        module,
        "run_command",
        lambda command, timeout: {
            "command": command,
            "exit_code": 0,
            "stdout": "The Genome Analysis Toolkit (GATK) v4.6.1.0",
            "stderr": "",
        },
    )

    with pytest.raises(module.QualificationBlocked, match="GATK_VERSION_MISMATCH"):
        module.require_gatk("4.6.2.0")


def test_full_genome_runner_blocks_when_gatk_is_not_installed(monkeypatch: pytest.MonkeyPatch):
    module = _load_runner()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    with pytest.raises(module.QualificationBlocked, match="GATK_VALIDATEVARIANTS_UNAVAILABLE"):
        module.require_gatk("4.6.2.0")


def _write_reference_package(tmp_path: Path, module):
    fasta = tmp_path / "reference.fa"
    sequence = "ACGTN"
    fasta.write_text(f">chr1\n{sequence}\n", encoding="ascii")
    fai = Path(str(fasta) + ".fai")
    fai.write_text("chr1\t5\t6\t5\t6\n", encoding="ascii")
    dictionary = fasta.with_suffix(".dict")
    sequence_md5 = hashlib.md5(sequence.encode("ascii")).hexdigest()
    dictionary.write_text(
        f"@HD\tVN:1.6\tSO:unsorted\n@SQ\tSN:chr1\tLN:5\tM5:{sequence_md5}\n",
        encoding="ascii",
    )
    sequence_identity = module.inspect_fasta_sequence_identity(fasta)
    contigs = module.validate_fasta_index_consistency(fasta, fai)
    manifest = {
        "schema_version": "1.2",
        "package_version": "ncbi-GCA_000001405.15-full-plus-hs38d1-test",
        "assembly_name": "GRCh38",
        "assembly_accession": "GCA_000001405.15",
        "reference_source": "NCBI_GENOMES_FTP",
        "sequence_scope": "FULL_PLUS_HS38D1_ANALYSIS_SET",
        "contig_policy": "EXACT",
        "fasta_path": str(fasta),
        "fasta_size_bytes": fasta.stat().st_size,
        "fasta_sha256": module.sha256_file(fasta),
        "fai_sha256": module.sha256_file(fai),
        "dictionary_path": str(dictionary),
        "dictionary_sha256": module.sha256_file(dictionary),
        "contigs": contigs,
        "contigs_sha256": module.contig_manifest_sha256(contigs),
        "sequence_manifest": sequence_identity["sequences"],
        "sequence_collection_digest": sequence_identity["sequence_collection_digest"],
    }
    manifest["package_checksum"] = module._reference_package_checksum(manifest)
    manifest_path = tmp_path / "reference-package.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return fasta, manifest_path, manifest


def test_full_genome_reference_loader_verifies_dictionary_refget_seqcol_and_package_checksum(
    tmp_path: Path,
):
    module = _load_runner()
    fasta, manifest_path, manifest = _write_reference_package(tmp_path, module)

    result = module.load_reference(manifest_path, fasta)

    assert result["identity_status"] == (
        "FASTA_FAI_DICTIONARY_REFGET_SEQCOL_AND_PACKAGE_CHECKSUM_VERIFIED"
    )
    assert result["dictionary_sha256"] == manifest["dictionary_sha256"]
    assert result["sequence_collection_digest"] == manifest["sequence_collection_digest"]
    assert result["package_checksum"] == manifest["package_checksum"]


def test_full_genome_reference_loader_rejects_dictionary_checksum_mismatch(tmp_path: Path):
    module = _load_runner()
    fasta, manifest_path, manifest = _write_reference_package(tmp_path, module)
    dictionary = Path(manifest["dictionary_path"])
    dictionary.write_text(dictionary.read_text(encoding="ascii") + "@SQ\tSN:extra\tLN:1\tM5:0\n", encoding="ascii")

    with pytest.raises(module.QualificationBlocked, match="REFERENCE_DICTIONARY_CHECKSUM_MISMATCH"):
        module.load_reference(manifest_path, fasta)


def test_full_genome_reference_loader_rejects_legacy_package_schema(tmp_path: Path):
    module = _load_runner()
    fasta, manifest_path, manifest = _write_reference_package(tmp_path, module)
    manifest["schema_version"] = "1.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.QualificationBlocked, match="REFERENCE_SEQUENCE_IDENTITY_SCHEMA_REQUIRED"):
        module.load_reference(manifest_path, fasta)


def test_giab_manifest_requires_exact_reference_and_validates_sample_contigs_and_bed(
    tmp_path: Path,
):
    module = _load_runner()
    fasta, reference_manifest_path, _ = _write_reference_package(tmp_path, module)
    reference = module.load_reference(reference_manifest_path, fasta)
    truth = tmp_path / "HG002.truth.vcf"
    truth.write_text(
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=5>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG002\n"
        "chr1\t1\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    bed = tmp_path / "HG002.confident.bed"
    bed.write_text("chr1\t0\t5\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "dataset_id": "GIAB-HG002",
        "dataset_version": "4.2.1",
        "sample_id": "HG002",
        "variant_scope": "GERMLINE_SNV_INDEL",
        "assembly_accession": reference["assembly_accession"],
        "reference_package_checksum": reference["package_checksum"],
        "reference_fasta_sha256": reference["fasta_sha256"],
        "sequence_collection_digest": reference["sequence_collection_digest"],
        "truth_vcf": {
            "filename": truth.name,
            "source_url": "https://example.org/HG002.truth.vcf",
            "sha256": module.sha256_file(truth),
        },
        "confident_bed": {
            "filename": bed.name,
            "source_url": "https://example.org/HG002.confident.bed",
            "sha256": module.sha256_file(bed),
        },
    }
    manifest_path = tmp_path / "giab-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = module.validate_giab_manifest(manifest_path, truth, bed, reference)

    assert result["technical_compatibility_status"] == "VERIFIED_AGAINST_EXACT_REFERENCE_PACKAGE"
    assert result["truth_vcf"]["sample_names"] == ["HG002"]
    assert result["confident_bed"]["interval_count"] == 1
    assert result["clinical_approval_status"] == "NOT_ESTABLISHED"


def test_giab_manifest_rejects_reference_package_mismatch(tmp_path: Path):
    module = _load_runner()
    fasta, reference_manifest_path, _ = _write_reference_package(tmp_path, module)
    reference = module.load_reference(reference_manifest_path, fasta)
    truth = tmp_path / "HG002.truth.vcf"
    truth.write_text(
        "##fileformat=VCFv4.2\n##contig=<ID=chr1,length=5>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG002\n",
        encoding="utf-8",
    )
    bed = tmp_path / "HG002.confident.bed"
    bed.write_text("chr1\t0\t5\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "dataset_id": "GIAB-HG002",
        "dataset_version": "4.2.1",
        "sample_id": "HG002",
        "variant_scope": "GERMLINE_SNV_INDEL",
        "assembly_accession": reference["assembly_accession"],
        "reference_package_checksum": "0" * 64,
        "reference_fasta_sha256": reference["fasta_sha256"],
        "sequence_collection_digest": reference["sequence_collection_digest"],
        "truth_vcf": {"filename": truth.name, "source_url": "https://example.org/truth.vcf", "sha256": module.sha256_file(truth)},
        "confident_bed": {"filename": bed.name, "source_url": "https://example.org/bed.bed", "sha256": module.sha256_file(bed)},
    }
    manifest_path = tmp_path / "giab-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.QualificationBlocked, match="GIAB_REFERENCE_PACKAGE_CHECKSUM_MISMATCH"):
        module.validate_giab_manifest(manifest_path, truth, bed, reference)
