import hashlib
import json
import shutil
from pathlib import Path

import pytest

from backend.app.domain.normalization import NormalizationError, normalize_vcf_file
from backend.app.domain.reference import FastaReference
from backend.app.domain.reference_registry import load_reference_package


def make_reference(tmp_path: Path) -> tuple[Path, Path]:
    fasta = tmp_path / "ref.fa"
    seq = "CAAAAAC"
    fasta.write_text(">1\n" + seq + "\n", encoding="utf-8")
    fai = tmp_path / "ref.fa.fai"
    fai.write_text(
        f"1\t{len(seq)}\t3\t{len(seq)}\t{len(seq)+1}\n",
        encoding="utf-8",
    )
    return fasta, fai


def make_manifest(tmp_path: Path, fasta: Path, fai: Path) -> Path:
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "assembly": "GRCh38",
                "fasta_sha256": sha(fasta),
                "fai_sha256": sha(fai),
            }
        ),
        encoding="utf-8",
    )
    return manifest


@pytest.mark.skipif(shutil.which("bcftools") is None, reason="bcftools is required for normalization tests")
def test_bcftools_reference_aware_left_normalization(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf"

    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t4\t.\tAA\tA\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with FastaReference(fasta, fai) as ref:
        result = normalize_vcf_file(
            input_vcf,
            output_vcf,
            genome_build="GRCh38",
            reference=ref,
            collect_variants=True,
        )

    assert result["tool"] == "bcftools"
    assert result["record_count"] == 1
    assert result["variants"][0].position == 1
    assert result["variants"][0].reference == "CA"
    assert result["variants"][0].alternate == "C"


@pytest.mark.skipif(shutil.which("bcftools") is None, reason="bcftools is required for normalization tests")
def test_bcftools_splits_multiallelic_sites(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf"

    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with FastaReference(fasta, fai) as ref:
        result = normalize_vcf_file(
            input_vcf,
            output_vcf,
            genome_build="GRCh38",
            reference=ref,
            collect_variants=True,
        )

    assert result["record_count"] == 2
    assert {v.alternate for v in result["variants"]} == {"C", "G"}


@pytest.mark.skipif(shutil.which("bcftools") is None, reason="bcftools is required for normalization tests")
def test_reference_mismatch_fails_closed(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    input_vcf = tmp_path / "input.vcf"
    output_vcf = tmp_path / "normalized.vcf"

    input_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tC\tA\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with FastaReference(fasta, fai) as ref:
        with pytest.raises(NormalizationError):
            normalize_vcf_file(
                input_vcf,
                output_vcf,
                genome_build="GRCh38",
                reference=ref,
                collect_variants=False,
            )


def test_reference_package_manifest_is_qualified(tmp_path: Path):
    fasta, fai = make_reference(tmp_path)
    manifest = make_manifest(tmp_path, fasta, fai)

    package = load_reference_package(
        build="GRCh38",
        fasta_path=fasta,
        fai_path=fai,
        manifest_path=manifest,
    )

    assert package.build == "GRCh38"
    assert package.fasta_sha256 == hashlib.sha256(fasta.read_bytes()).hexdigest()
    assert package.fai_sha256 == hashlib.sha256(fai.read_bytes()).hexdigest()
