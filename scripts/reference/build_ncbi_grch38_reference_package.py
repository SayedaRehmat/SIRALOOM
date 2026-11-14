#!/usr/bin/env python3
"""Acquire and build the pinned NCBI GRCh38 full_plus_hs38d1 reference package.

This builder downloads the publisher FASTA and its publisher checksum manifest,
verifies the compressed source bytes, expands to a stable plain FASTA, builds
FAI and SAM/GATK sequence dictionary indexes, and emits a SIRALOOM package
manifest. It does not silently register or activate the package in a database.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Sequence

from backend.app.domain.reference_identity import (
    inspect_fasta_sequence_identity,
    validate_sequence_dictionary,
)
from backend.app.domain.reference_package import (
    REFERENCE_PACKAGE_SCHEMA_VERSION,
    contig_manifest_sha256,
    contigs_from_fai,
    package_checksum,
    sha256_file,
)

BASE_URL = (
    "https://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/"
    "GCA_000001405.15_GRCh38/seqs_for_alignment_pipelines.ucsc_ids/"
)
FASTA_FILENAME = "GCA_000001405.15_GRCh38_full_plus_hs38d1_analysis_set.fna.gz"
CHECKSUM_FILENAME = "md5checksums.txt"
ASSEMBLY_ACCESSION = "GCA_000001405.15"
SEQUENCE_SCOPE = "FULL_PLUS_HS38D1_ANALYSIS_SET"


class BuildError(RuntimeError):
    pass


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "SIRALOOM-reference-builder/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _publisher_md5(checksum_file: Path, filename: str) -> str:
    matches: list[str] = []
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        fields = line.strip().lstrip("*").split()
        if len(fields) >= 2 and Path(fields[-1]).name == filename:
            matches.append(fields[0].lower())
    if len(matches) != 1 or len(matches[0]) != 32:
        raise BuildError(
            f"publisher checksum manifest must contain exactly one MD5 entry for {filename}; "
            f"found {len(matches)}"
        )
    return matches[0]


def _run(command: Sequence[str], *, timeout: int = 3600) -> str:
    result = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise BuildError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout: {result.stdout[-4000:]}\nstderr: {result.stderr[-4000:]}"
        )
    return (result.stdout + "\n" + result.stderr).strip()


def build_package(output_dir: Path, *, samtools: str, picard_jar: Path, bcftools: str = "bcftools") -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_fasta = output_dir / "source" / FASTA_FILENAME
    checksum_file = output_dir / "source" / CHECKSUM_FILENAME
    fasta_path = output_dir / "sequences" / "GRCh38_full_plus_hs38d1.fa"
    fai_path = Path(str(fasta_path) + ".fai")
    dictionary_path = fasta_path.with_suffix(".dict")

    _download(BASE_URL + FASTA_FILENAME, source_fasta)
    _download(BASE_URL + CHECKSUM_FILENAME, checksum_file)

    publisher_md5 = _publisher_md5(checksum_file, FASTA_FILENAME)
    observed_md5 = hashlib.md5(usedforsecurity=False)
    with source_fasta.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            observed_md5.update(chunk)
    if observed_md5.hexdigest() != publisher_md5:
        raise BuildError(
            f"NCBI publisher MD5 mismatch for {FASTA_FILENAME}: "
            f"expected {publisher_md5}, observed {observed_md5.hexdigest()}"
        )

    fasta_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_fasta = fasta_path.with_suffix(fasta_path.suffix + ".partial")
    try:
        with gzip.open(source_fasta, "rb") as source, temporary_fasta.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        temporary_fasta.replace(fasta_path)
    except Exception:
        temporary_fasta.unlink(missing_ok=True)
        raise

    samtools_output = _run([samtools, "faidx", str(fasta_path)], timeout=3600)
    samtools_version = _run([samtools, "--version"])
    bcftools_version = _run([bcftools, "--version"])
    picard_output = _run(
        ["java", "-jar", str(picard_jar), "CreateSequenceDictionary",
         f"R={fasta_path}", f"O={dictionary_path}"],
        timeout=3600,
    )
    if not fai_path.is_file() or not dictionary_path.is_file():
        raise BuildError("samtools/Picard completed without producing required FAI and DICT assets")

    contigs = contigs_from_fai(fai_path)
    sequence_identity = inspect_fasta_sequence_identity(fasta_path)
    dictionary_identity = validate_sequence_dictionary(
        dictionary_path,
        sequence_identity["sequences"],
    )
    if [
        {"name": item["name"], "length": item["length"]}
        for item in sequence_identity["sequences"]
    ] != contigs:
        raise BuildError("FASTA sequence identity and FAI contig order/length disagree")

    fasta_sha = sha256_file(fasta_path)
    fai_sha = sha256_file(fai_path)
    dictionary_sha = sha256_file(dictionary_path)
    contigs_sha = contig_manifest_sha256(contigs)
    package_version = f"ncbi-{ASSEMBLY_ACCESSION}-full-plus-hs38d1-{publisher_md5[:12]}"
    checksum = package_checksum(
        genome_build="GRCh38",
        version=package_version,
        fasta_sha256=fasta_sha,
        fai_sha256=fai_sha,
        contigs_sha256=contigs_sha,
        assembly_name="GRCh38",
        assembly_accession=ASSEMBLY_ACCESSION,
        reference_source="NCBI_GENOMES_FTP",
        sequence_scope=SEQUENCE_SCOPE,
        schema_version=REFERENCE_PACKAGE_SCHEMA_VERSION,
        dictionary_sha256=dictionary_sha,
        sequence_collection_digest=sequence_identity["sequence_collection_digest"],
    )
    manifest = {
        "package_version": package_version,
        "schema_version": REFERENCE_PACKAGE_SCHEMA_VERSION,
        "assembly_name": "GRCh38",
        "assembly_accession": ASSEMBLY_ACCESSION,
        "reference_source": "NCBI_GENOMES_FTP",
        "sequence_scope": SEQUENCE_SCOPE,
        "contig_policy": "EXACT",
        "fasta_path": str(fasta_path.resolve()),
        "fai_path": str(fai_path.resolve()),
        "dictionary_path": str(dictionary_path.resolve()),
        "fasta_sha256": fasta_sha,
        "fai_sha256": fai_sha,
        "dictionary_sha256": dictionary_sha,
        "contigs_sha256": contigs_sha,
        "contigs": contigs,
        "sequence_manifest": sequence_identity["sequences"],
        "sequence_collection_digest": sequence_identity["sequence_collection_digest"],
        "package_checksum": checksum,
        "source_contract": {
            "publisher": "NCBI",
            "canonical_source_url": "https://www.ncbi.nlm.nih.gov/genome/",
            "artifact_url": BASE_URL + FASTA_FILENAME,
            "release_identity": package_version,
            "access_mode": "PUBLIC",
            "license_status": "NOT_REQUIRED",
            "checksum_status": "PUBLISHED_AND_VERIFIED",
            "authority_evidence_url": "https://www.ncbi.nlm.nih.gov/datasets/docs/v2/data-processing/policies-annotation/genomeftp/",
            "publisher_checksum_evidence": {
                "algorithm": "md5",
                "expected_digest": publisher_md5,
                "evidence_file_path": str(checksum_file.resolve()),
                "evidence_file_url": BASE_URL + CHECKSUM_FILENAME,
                "evidence_file_sha256": sha256_file(checksum_file),
                "artifact_filename": FASTA_FILENAME,
                "verified_artifact_path": str(source_fasta.resolve()),
            },
        },
        "execution": {
            "provider_id": "SIRALOOM_REFERENCE",
            "provider_version": "reference-builder-1.2",
            "access_method": "LOCAL",
            "location": str(fasta_path.resolve()),
            "execution_scope": "SIRALOOM_MANAGED",
            "toolchain": {
                "samtools": samtools_version.splitlines()[0] if samtools_version else "EXECUTED",
                "samtools_faidx": {
                    "status": "EXECUTED",
                    "output": samtools_output[-1000:],
                },
                "bcftools": {"version": bcftools_version.splitlines()[0] if bcftools_version else "UNKNOWN"},
                "picard": picard_output.splitlines()[0] if picard_output else "EXECUTED",
            },
        },
        "qualification_preview": {
            "sequence_dictionary": dictionary_identity,
            "publisher_checksum": "VERIFIED",
            "source_artifact_md5": publisher_md5,
        },
    }
    manifest_path = output_dir / "reference-package.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samtools", default="samtools")
    parser.add_argument("--bcftools", default="bcftools")
    parser.add_argument("--picard-jar", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_package(
        args.output_dir,
        samtools=args.samtools,
        picard_jar=args.picard_jar,
        bcftools=args.bcftools,
    )
    print(json.dumps({
        "status": "BUILT_NOT_REGISTERED",
        "manifest_path": str(args.output_dir / "reference-package.json"),
        "package_version": manifest["package_version"],
        "package_checksum": manifest["package_checksum"],
        "sequence_collection_digest": manifest["sequence_collection_digest"],
        "contig_count": len(manifest["contigs"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
