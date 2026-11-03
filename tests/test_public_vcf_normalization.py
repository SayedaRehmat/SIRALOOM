"""Downloaded upstream VCF interoperability and reference-aware normalization test.

The VCF fixture is pinned to the BCFtools 1.25 source tree. The reference is
Ensembl release 115 GRCh38 chromosome 1, verified against Ensembl's MD5SUM.
The downloaded data remains in the ephemeral GitHub Actions runner workspace.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools
from backend.app.domain.vcf_validation import validate_vcf_strict


PUBLIC_VCF_SHA256 = "4ca6d9e8eb53301e5a89e4bec8ca512a0367a2dd338c9c7e2f99d9ded305b369"
PUBLIC_VCF_SOURCE = (
    "https://github.com/samtools/bcftools/blob/1.25/test/filter.39.out"
)


def _build_single_contig_fai(fasta_path: Path) -> Path:
    """Build a standards-compatible FAI for a one-contig, line-wrapped FASTA."""
    with fasta_path.open("rb") as handle:
        header = handle.readline()
        if not header.startswith(b">"):
            raise AssertionError("Downloaded reference FASTA has no header.")
        name = header[1:].split(None, 1)[0].decode("ascii")
        sequence_offset = handle.tell()
        first_sequence_line = handle.readline()
        if not first_sequence_line or first_sequence_line.startswith(b">"):
            raise AssertionError("Downloaded reference FASTA has no sequence.")
        line_bases = len(first_sequence_line.rstrip(b"\r\n"))
        line_width = len(first_sequence_line)
        if line_bases <= 0:
            raise AssertionError("Downloaded reference FASTA has an empty sequence line.")
        sequence_length = line_bases
        previous_line_bases = line_bases
        while True:
            line = handle.readline()
            if not line:
                break
            if line.startswith(b">"):
                raise AssertionError("Expected exactly one chromosome in the reference FASTA.")
            bases = len(line.rstrip(b"\r\n"))
            if bases <= 0:
                raise AssertionError("Downloaded reference FASTA contains an empty sequence line.")
            if previous_line_bases != line_bases:
                raise AssertionError("Only the final FASTA sequence line may be shorter.")
            if bases > line_bases:
                raise AssertionError("FASTA sequence line exceeds the indexed line width.")
            sequence_length += bases
            previous_line_bases = bases
    fai_path = Path(f"{fasta_path}.fai")
    fai_path.write_text(
        f"{name}\t{sequence_length}\t{sequence_offset}\t{line_bases}\t{line_width}\n",
        encoding="ascii",
    )
    return fai_path


def test_downloaded_public_vcf_validates_and_normalizes_against_grch38(
    tmp_path: Path,
):
    source_value = os.getenv("SIRALOOM_PUBLIC_VCF_PATH")
    reference_value = os.getenv("SIRALOOM_PUBLIC_REFERENCE_PATH")
    if not source_value or not reference_value:
        pytest.skip("Pinned public VCF/reference acquisition is enabled in GitHub Actions only.")

    source = Path(source_value)
    reference = Path(reference_value)
    assert source.is_file(), f"Missing downloaded upstream VCF from {PUBLIC_VCF_SOURCE}"
    assert reference.is_file(), "Missing downloaded Ensembl GRCh38 chromosome 1 FASTA"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == PUBLIC_VCF_SHA256

    source_validation = validate_vcf_strict(source, reference_contigs={"1"})
    assert source_validation["fileformat"] == "VCFv4.3"
    assert source_validation["records"] == 1
    assert source_validation["sample_count"] == 1

    _build_single_contig_fai(reference)
    output = tmp_path / "bcftools-upstream-fixture.normalized.vcf.gz"
    execution = normalize_vcf_with_bcftools(
        source,
        output,
        reference_fasta=reference,
        expected_bcftools_version="1.25",
    )

    output_validation = validate_vcf_strict(output, reference_contigs={"1"})
    assert output_validation["fileformat"] == "VCFv4.3"
    assert output_validation["records"] == 1
    assert execution["tool_version"] == "bcftools 1.25"
    assert execution["reference_check"] == "error"
    assert execution["compression"] == "BGZF"
    assert execution["index"] == "CSI"
    assert Path(execution["index_path"]).is_file()
    assert execution["executable_integrity_status"] == "MEASURED_UNPINNED"
    assert len(execution["executable_sha256"]) == 64
    assert execution["reference_identity"]["sha256"]
